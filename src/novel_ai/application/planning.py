from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_ai.application.chapter_workflow import WORK_PLANNING_ASSISTANT_V1
from novel_ai.application.generation import GenerationConflictError, GenerationHandle
from novel_ai.application.writing import WritingNotFoundError
from novel_ai.config import Settings, get_settings
from novel_ai.db.models import (
    Artifact,
    ContextSnapshot,
    GenerationRun,
    Work,
    WorkflowRun,
    WorkflowStep,
)
from novel_ai.db.session import session_factory
from novel_ai.domain.artifacts import JSONValue, canonical_json, content_hash
from novel_ai.prompts.catalog import get_prompt_catalog
from novel_ai.providers.audit import provider_audit_metadata
from novel_ai.providers.errors import ProviderError
from novel_ai.providers.factory import build_model_gateway, default_model_route
from novel_ai.storage import LocalObjectStore

WORK_PLANNING_KIND = "WORK_PLANNING_ASSISTANT_V1"


async def create_work_planning_run(
    session: AsyncSession,
    *,
    work_id: UUID,
    idempotency_key: str,
    author_intent: str,
    prior_core_pitches: list[str],
    prior_candidate_hashes: list[str],
) -> GenerationHandle:
    work = await session.get(Work, work_id)
    if work is None:
        raise WritingNotFoundError("作品不存在")
    existing = await session.scalar(
        select(WorkflowRun).where(
            WorkflowRun.work_id == work_id,
            WorkflowRun.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return GenerationHandle(existing.id, existing.status, False)
    active = await session.scalar(
        select(WorkflowRun).where(
            WorkflowRun.work_id == work_id,
            WorkflowRun.kind == WORK_PLANNING_KIND,
            WorkflowRun.status.in_(("PLANNED", "RUNNING")),
        )
    )
    if active is not None:
        raise GenerationConflictError("该作品已有正在执行的大纲生成任务")

    run = WorkflowRun(
        work_id=work_id,
        chapter_id=None,
        kind=WORK_PLANNING_KIND,
        status="PLANNED",
        baseline_commit_sequence=work.commit_sequence,
        idempotency_key=idempotency_key,
    )
    session.add(run)
    await session.flush()
    request_payload: dict[str, Any] = {
        "generation_nonce": str(run.id),
        "work_version": work.version,
        "author_intent": author_intent.strip(),
        "prior_core_pitches": [item.strip() for item in prior_core_pitches if item.strip()][-5:],
        "prior_candidate_hashes": prior_candidate_hashes[-10:],
    }
    request_artifact = Artifact(
        work_id=work.id,
        kind="WORK_PLAN_REQUEST",
        schema_version=1,
        content_json=request_payload,
        content_hash=content_hash(data=cast(JSONValue, request_payload)),
        media_type="application/json",
        status="VALID",
    )
    session.add(request_artifact)
    await session.flush()
    for ordinal, definition in enumerate(WORK_PLANNING_ASSISTANT_V1, start=1):
        step = WorkflowStep(
            workflow_run_id=run.id,
            step_key=definition.key,
            ordinal=ordinal,
            status="PENDING",
        )
        if definition.key == "capture_author_brief":
            step.status = "SUCCEEDED"
            step.output_artifact_id = request_artifact.id
        session.add(step)
    await session.commit()
    return GenerationHandle(run.id, run.status, True)


async def execute_work_planning_run(run_id: UUID, settings: Settings | None = None) -> None:
    runtime_settings = settings or get_settings()
    async with session_factory() as session:
        run = await session.scalar(
            select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update()
        )
        if (
            run is None
            or run.kind != WORK_PLANNING_KIND
            or run.status
            not in {
                "PLANNED",
                "FAILED",
            }
        ):
            return
        run.status = "RUNNING"
        run.worker_id = str(uuid4())
        lease_seconds = (
            max(
                runtime_settings.codex_session_timeout_seconds,
                runtime_settings.model_request_timeout_seconds,
            )
            + 60
        )
        run.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        run.version += 1
        await session.commit()

        run = await session.get(WorkflowRun, run_id)
        work = await session.get(Work, run.work_id if run is not None else None)
        if run is None or work is None:
            return
        request_step = await _step(session, run.id, "capture_author_brief")
        request_artifact = (
            await session.get(Artifact, request_step.output_artifact_id)
            if request_step.output_artifact_id is not None
            else None
        )
        if request_artifact is None or request_artifact.content_json is None:
            await _fail_planning_run(session, run, "MISSING_AUTHOR_BRIEF", "大纲生成输入不存在")
            return
        request_data = request_artifact.content_json
        compile_step = await _step(session, run.id, "compile_work_plan_context")
        compile_step.status = "RUNNING"

        current_planning = {
            "description": work.description,
            "corePitch": work.settings_json.get("core_pitch"),
            "themes": work.settings_json.get("themes"),
            "mainPlot": work.settings_json.get("main_plot"),
            "outlineMarkdown": work.settings_json.get("outline_markdown"),
            "endingConstraints": work.settings_json.get("ending_constraints"),
            "storyBible": work.settings_json.get("story_bible"),
            "styleContract": work.settings_json.get("style_contract"),
            "forbiddenContent": work.settings_json.get("forbidden_content"),
        }
        rendered = get_prompt_catalog().render(
            "work_planner",
            {
                "work_profile": {
                    "title": work.title,
                    "currentPlanningForReference": current_planning,
                    "scope": "3卷、约100章、每章通常2000～3000字",
                },
                "author_intent": request_data.get("author_intent")
                or "根据作品标题提出鲜明且可持续的网络小说方向",
                "previous_directions": request_data.get("prior_core_pitches", []),
                "generation_nonce": request_data["generation_nonce"],
            },
        )
        snapshot = await _get_or_create_snapshot(
            session,
            run,
            rendered.system,
            rendered.user,
            rendered.key,
            rendered.version,
            rendered.fingerprint,
            {
                "work_id": str(work.id),
                "work_version": work.version,
                "request_artifact_id": str(request_artifact.id),
                "generation_nonce": request_data["generation_nonce"],
            },
        )
        compile_step.status = "SUCCEEDED"
        generate_step = await _step(session, run.id, "generate_work_plan")
        generate_step.status = "RUNNING"
        generate_step.attempt_count += 1
        provider, model = default_model_route(runtime_settings)
        generation = GenerationRun(
            workflow_step_id=generate_step.id,
            context_snapshot_id=snapshot.id,
            prompt_key=rendered.key,
            prompt_version=rendered.version,
            prompt_fingerprint=rendered.fingerprint,
            provider=provider.value,
            endpoint="pending",
            model_snapshot=model,
            parameters={"max_output_tokens": runtime_settings.generation_max_output_tokens},
            status="RUNNING",
            attempt=generate_step.attempt_count,
        )
        session.add(generation)
        await session.commit()

        gateway = build_model_gateway(runtime_settings)
        try:
            output = await gateway.generate_prompt(
                provider,
                model=model,
                prompt=rendered,
                max_output_tokens=runtime_settings.generation_max_output_tokens,
                reasoning_effort="low",
            )
        except ProviderError as exc:
            generation.status = "FAILED"
            generation.error_json = {
                "code": str(exc.code),
                "retryable": exc.retryable,
                "message": str(exc),
            }
            await _fail_planning_run(session, run, str(exc.code), str(exc))
            return
        except Exception as exc:
            generation.status = "FAILED"
            generation.error_json = {
                "code": "UNEXPECTED_PLANNING_ERROR",
                "retryable": False,
                "message": str(exc),
            }
            await _fail_planning_run(session, run, "UNEXPECTED_PLANNING_ERROR", str(exc))
            return
        finally:
            await gateway.aclose()

        raw_object = await asyncio.to_thread(
            LocalObjectStore(runtime_settings.object_store_path).put_json,
            "provider-responses",
            output.response.raw_payload,
        )
        audit = provider_audit_metadata(output.response)
        generation.endpoint = str(audit["endpoint"])
        generation.model_snapshot = str(audit["model_snapshot"])
        generation.finish_reason = output.response.finish_reason
        generation.response_status = output.response.status.value
        generation.provider_request_id = output.response.request_id
        generation.provider_response_id = output.response.response_id
        generation.response_item_types = list(output.response.output_item_types)
        generation.system_fingerprint = output.response.system_fingerprint
        generation.latency_ms = output.response.latency_ms
        generation.usage_json = output.response.usage
        generation.raw_response_uri = raw_object.uri
        if not isinstance(output.structured, dict):
            generation.status = "FAILED"
            await _fail_planning_run(session, run, "INVALID_PLAN_OUTPUT", "大纲输出不是结构化对象")
            return
        candidate = output.structured
        if candidate.get("candidateId") != request_data["generation_nonce"]:
            generation.status = "FAILED"
            await _fail_planning_run(
                session, run, "STALE_PLAN_OUTPUT", "大纲候选未返回本次生成标识"
            )
            return
        candidate_signature = _candidate_signature(candidate)
        if candidate_signature in request_data.get("prior_candidate_hashes", []):
            generation.status = "FAILED"
            await _fail_planning_run(
                session,
                run,
                "DUPLICATE_PLAN_OUTPUT",
                "本次结果与浏览器中的旧候选完全相同，请再次生成",
            )
            return
        generate_step.status = "SUCCEEDED"
        save_step = await _step(session, run.id, "save_work_plan_candidate")
        save_step.status = "RUNNING"
        artifact_digest = content_hash(data=cast(JSONValue, candidate))
        candidate_artifact = await session.scalar(
            select(Artifact).where(
                Artifact.work_id == work.id,
                Artifact.kind == "WORK_PLANNING_CANDIDATE",
                Artifact.content_hash == artifact_digest,
            )
        )
        if candidate_artifact is None:
            candidate_artifact = Artifact(
                work_id=work.id,
                kind="WORK_PLANNING_CANDIDATE",
                schema_version=1,
                content_json=candidate,
                content_hash=artifact_digest,
                media_type="application/json",
                status="REVIEW",
            )
            session.add(candidate_artifact)
            await session.flush()
        generation.status = "SUCCEEDED"
        generation.output_artifact_id = candidate_artifact.id
        save_step.status = "SUCCEEDED"
        save_step.output_artifact_id = candidate_artifact.id
        review_step = await _step(session, run.id, "review_work_plan_candidate")
        review_step.status = "PENDING"
        run.status = "AWAITING_REVIEW"
        run.worker_id = None
        run.lease_expires_at = None
        run.version += 1
        await session.commit()


async def get_work_planning_candidate(
    session: AsyncSession, run_id: UUID
) -> tuple[dict[str, Any], str]:
    run = await session.get(WorkflowRun, run_id)
    if run is None or run.kind != WORK_PLANNING_KIND:
        raise WritingNotFoundError("大纲生成任务不存在")
    if run.status != "AWAITING_REVIEW":
        raise GenerationConflictError("大纲候选尚未生成完成")
    step = await _step(session, run.id, "save_work_plan_candidate")
    artifact = (
        await session.get(Artifact, step.output_artifact_id)
        if step.output_artifact_id is not None
        else None
    )
    if artifact is None or artifact.content_json is None:
        raise WritingNotFoundError("大纲候选不存在")
    return artifact.content_json, _candidate_signature(artifact.content_json)


def _candidate_signature(candidate: dict[str, Any]) -> str:
    content = {
        key: value
        for key, value in candidate.items()
        if key not in {"schemaVersion", "artifactType", "candidateId"}
    }
    return hashlib.sha256(canonical_json(cast(JSONValue, content)).encode("utf-8")).hexdigest()


async def _step(session: AsyncSession, run_id: UUID, key: str) -> WorkflowStep:
    step = await session.scalar(
        select(WorkflowStep).where(
            WorkflowStep.workflow_run_id == run_id,
            WorkflowStep.step_key == key,
        )
    )
    if step is None:
        raise RuntimeError(f"workflow step missing: {key}")
    return step


async def _get_or_create_snapshot(
    session: AsyncSession,
    run: WorkflowRun,
    system: str,
    user: str,
    prompt_key: str,
    prompt_version: int,
    prompt_fingerprint: str,
    source_manifest: dict[str, Any],
) -> ContextSnapshot:
    digest = hashlib.sha256(
        canonical_json(
            cast(
                JSONValue,
                {"system": system, "user": user, "sources": source_manifest},
            )
        ).encode("utf-8")
    ).hexdigest()
    existing = await session.scalar(
        select(ContextSnapshot).where(
            ContextSnapshot.work_id == run.work_id,
            ContextSnapshot.content_hash == digest,
        )
    )
    if existing is not None:
        return existing
    snapshot = ContextSnapshot(
        work_id=run.work_id,
        baseline_commit_sequence=run.baseline_commit_sequence,
        prompt_key=prompt_key,
        prompt_version=prompt_version,
        prompt_fingerprint=prompt_fingerprint,
        exact_system_text=system,
        exact_user_text=user,
        source_manifest=source_manifest,
        budget_report={"system_chars": len(system), "user_chars": len(user)},
        content_hash=digest,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def _fail_planning_run(
    session: AsyncSession, run: WorkflowRun, code: str, message: str
) -> None:
    run.status = "FAILED"
    run.worker_id = None
    run.lease_expires_at = None
    run.version += 1
    running_steps = (
        await session.scalars(
            select(WorkflowStep).where(
                WorkflowStep.workflow_run_id == run.id,
                WorkflowStep.status == "RUNNING",
            )
        )
    ).all()
    for step in running_steps:
        step.status = "FAILED"
        step.error_json = {"code": code, "message": message}
    await session.commit()
