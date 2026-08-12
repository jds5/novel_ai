from __future__ import annotations

import asyncio
import hashlib
import math
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_ai.application.chapter_workflow import INTERACTIVE_DRAFT_WORKFLOW_V1
from novel_ai.application.writing import (
    WritingConflictError,
    WritingNotFoundError,
    save_chapter_content,
)
from novel_ai.config import Settings, get_settings
from novel_ai.db.models import (
    Artifact,
    Chapter,
    ChapterRevision,
    ContextSnapshot,
    GenerationRun,
    Work,
    WorkflowRun,
    WorkflowStep,
)
from novel_ai.db.session import session_factory
from novel_ai.domain.artifacts import canonical_json
from novel_ai.domain.prose_length import ProseLengthPolicy
from novel_ai.domain.prose_purity import (
    SceneProseEnvelope,
    TransportStatus,
    parse_and_scan_scene_prose,
)
from novel_ai.prompts.catalog import get_prompt_catalog
from novel_ai.prompts.models import RenderedPrompt
from novel_ai.providers.audit import provider_audit_metadata
from novel_ai.providers.errors import ProviderError
from novel_ai.providers.factory import build_model_gateway, default_model_route
from novel_ai.storage import LocalObjectStore


class GenerationConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GenerationHandle:
    run_id: UUID
    status: str
    should_start: bool = False


@dataclass(frozen=True, slots=True)
class GenerationStatusRecord:
    run: WorkflowRun
    steps: tuple[WorkflowStep, ...]
    generation: GenerationRun | None
    candidate_revision_id: UUID | None


def schedule_generation_run(run_id: UUID, settings: Settings | None = None) -> None:
    """Start an isolated worker so a long Codex call cannot block the web process."""

    del settings
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(  # noqa: S603
        (sys.executable, "-m", "novel_ai.worker", str(run_id)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )


async def create_generation_run(
    session: AsyncSession,
    *,
    chapter_id: UUID,
    idempotency_key: str,
) -> GenerationHandle:
    chapter = await session.get(Chapter, chapter_id)
    if chapter is None:
        raise WritingNotFoundError("章节不存在")
    existing = await session.scalar(
        select(WorkflowRun).where(
            WorkflowRun.work_id == chapter.work_id,
            WorkflowRun.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return GenerationHandle(run_id=existing.id, status=existing.status, should_start=False)
    active = await session.scalar(
        select(WorkflowRun).where(
            WorkflowRun.chapter_id == chapter_id,
            WorkflowRun.kind == "INTERACTIVE_CHAPTER_DRAFT_V1",
            WorkflowRun.status.in_(("PLANNED", "RUNNING")),
        )
    )
    if active is not None:
        raise GenerationConflictError("该章节已有正在执行的生成任务")
    work = await session.get(Work, chapter.work_id)
    if work is None:
        raise WritingNotFoundError("作品不存在")
    run = WorkflowRun(
        work_id=work.id,
        chapter_id=chapter.id,
        kind="INTERACTIVE_CHAPTER_DRAFT_V1",
        status="PLANNED",
        baseline_commit_sequence=work.commit_sequence,
        idempotency_key=idempotency_key,
    )
    session.add(run)
    await session.flush()
    for ordinal, definition in enumerate(INTERACTIVE_DRAFT_WORKFLOW_V1, start=1):
        session.add(
            WorkflowStep(
                workflow_run_id=run.id,
                step_key=definition.key,
                ordinal=ordinal,
                status="PENDING",
            )
        )
    chapter.status = "GENERATING"
    chapter.version += 1
    await session.commit()
    return GenerationHandle(run_id=run.id, status=run.status, should_start=True)


async def execute_generation_run(run_id: UUID, settings: Settings | None = None) -> None:
    runtime_settings = settings or get_settings()
    async with session_factory() as session:
        run = await session.scalar(
            select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update()
        )
        if run is None or run.status not in {"PLANNED", "FAILED"}:
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
        if run is None:
            return
        await _mark_step(session, run.id, "load_chapter_task", "RUNNING")
        chapter = await session.get(Chapter, run.chapter_id)
        work = await session.get(Work, run.work_id)
        if chapter is None or work is None:
            await _fail_run(session, run, "MISSING_AGGREGATE", "作品或章节不存在")
            return
        expected_revision_number = await _latest_revision_number(session, chapter)
        await _mark_step(session, run.id, "load_chapter_task", "SUCCEEDED")
        await _mark_step(session, run.id, "compile_context", "RUNNING")

        rendered, source_manifest, budget_report = await _compile_prompt(
            session, work, chapter, runtime_settings
        )
        snapshot = await _get_or_create_context_snapshot(
            session=session,
            run=run,
            rendered=rendered,
            source_manifest=source_manifest,
            budget_report=budget_report,
        )
        await _mark_step(session, run.id, "compile_context", "SUCCEEDED")
        writer_step = await _mark_step(session, run.id, "write_chapter", "RUNNING")
        provider, model = default_model_route(runtime_settings)
        generation = GenerationRun(
            workflow_step_id=writer_step.id,
            context_snapshot_id=snapshot.id,
            prompt_key=rendered.key,
            prompt_version=rendered.version,
            prompt_fingerprint=rendered.fingerprint,
            provider=provider.value,
            endpoint="pending",
            model_snapshot=model,
            parameters={"max_output_tokens": runtime_settings.generation_max_output_tokens},
            status="RUNNING",
            attempt=writer_step.attempt_count + 1,
        )
        writer_step.attempt_count += 1
        session.add(generation)
        await session.commit()
        generation_id = generation.id

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
            await gateway.aclose()
            failed_generation = await session.get(GenerationRun, generation_id)
            if failed_generation is not None:
                failed_generation.status = "FAILED"
                failed_generation.error_json = {
                    "code": str(exc.code),
                    "retryable": exc.retryable,
                    "message": str(exc),
                }
            run = await session.get(WorkflowRun, run_id)
            if run is not None:
                await _fail_run(session, run, str(exc.code), str(exc))
            return
        except Exception as exc:
            await gateway.aclose()
            failed_generation = await session.get(GenerationRun, generation_id)
            if failed_generation is not None:
                failed_generation.status = "FAILED"
                failed_generation.error_json = {
                    "code": "UNEXPECTED_GENERATION_ERROR",
                    "retryable": False,
                    "message": str(exc),
                }
            run = await session.get(WorkflowRun, run_id)
            if run is not None:
                await _fail_run(session, run, "UNEXPECTED_GENERATION_ERROR", str(exc))
            return
        await gateway.aclose()

        raw_object = await asyncio.to_thread(
            LocalObjectStore(runtime_settings.object_store_path).put_json,
            "provider-responses",
            output.response.raw_payload,
        )
        loaded_generation = await session.get(GenerationRun, generation_id)
        run = await session.get(WorkflowRun, run_id)
        chapter = await session.get(Chapter, run.chapter_id if run is not None else None)
        if loaded_generation is None or run is None or chapter is None:
            return
        generation = loaded_generation
        audit = provider_audit_metadata(output.response)
        generation.endpoint = str(audit["endpoint"])
        generation.model_snapshot = str(audit["model_snapshot"])
        generation.status = "SUCCEEDED"
        generation.finish_reason = output.response.finish_reason
        generation.response_status = output.response.status.value
        generation.provider_request_id = output.response.request_id
        generation.provider_response_id = output.response.response_id
        generation.response_item_types = list(output.response.output_item_types)
        generation.system_fingerprint = output.response.system_fingerprint
        generation.latency_ms = output.response.latency_ms
        generation.usage_json = output.response.usage
        generation.raw_response_uri = raw_object.uri
        await _mark_step(session, run.id, "write_chapter", "SUCCEEDED")
        await _mark_step(session, run.id, "scan_prose_purity", "RUNNING")

        try:
            if not isinstance(output.structured, dict):
                raise ValueError("正文输出不是结构化对象")
            envelope, gate = parse_and_scan_scene_prose(
                output.structured,
                expected_scene_id=str(chapter.id),
                transport=TransportStatus(
                    completed=True,
                    refused=False,
                    finish_reason=output.response.finish_reason,
                ),
            )
            if not gate.accepted:
                finding_summary = [
                    {"category": finding.category, "rule": finding.rule}
                    for finding in gate.findings
                ]
                raise ValueError(f"正文纯净度检查失败: {finding_summary}")
            length_policy = ProseLengthPolicy(chapter.target_char_count)
            visible_chars = sum(not character.isspace() for character in envelope.prose)
            if length_policy.should_expand(visible_chars) or not length_policy.is_sane(
                visible_chars
            ):
                generation.status = "REJECTED"
                generation.error_json = {
                    "code": "OUTPUT_LENGTH_REPAIR_REQUESTED",
                    "retryable": True,
                    "message": (
                        f"正文实际 {visible_chars} 字，与 {chapter.target_char_count} 字目标"
                        "偏差较大，已请求一次质量优先的自然拓写或删减"
                    ),
                }
                envelope, generation = await _repair_chapter_length(
                    session=session,
                    run=run,
                    chapter=chapter,
                    writer_step=writer_step,
                    original_generation=generation,
                    original_prose=envelope.prose,
                    settings=runtime_settings,
                )
            final_visible_chars = sum(not character.isspace() for character in envelope.prose)
            if not length_policy.is_sane(final_visible_chars):
                raise ValueError(
                    "正文字数超出宽松安全范围："
                    f"实际 {final_visible_chars} 字，目标 {chapter.target_char_count} 字，"
                    f"允许 {length_policy.hard_minimum}～{length_policy.hard_maximum} 字"
                )
            await _mark_step(session, run.id, "scan_prose_purity", "SUCCEEDED")
            await _mark_step(session, run.id, "save_candidate", "RUNNING")
            saved = await save_chapter_content(
                session,
                chapter_id=chapter.id,
                content=envelope.prose,
                expected_revision_number=expected_revision_number,
                max_chars=runtime_settings.max_chapter_chars,
                source="MODEL",
                workflow_run_id=run.id,
                gate_passed=True,
                commit=False,
            )
        except (ValueError, WritingConflictError) as exc:
            generation.status = "FAILED"
            generation.error_json = {
                "code": "OUTPUT_GATE_FAILED",
                "retryable": True,
                "message": str(exc),
            }
            await _fail_run(session, run, "OUTPUT_GATE_FAILED", str(exc))
            return

        if saved.revision is None:
            await _fail_run(session, run, "MISSING_REVISION", "候选正文未形成修订")
            return
        generation.output_artifact_id = saved.revision.prose_artifact_id
        save_step = await _mark_step(session, run.id, "save_candidate", "SUCCEEDED")
        save_step.output_artifact_id = saved.revision.prose_artifact_id
        await _mark_step(session, run.id, "review_candidate", "PENDING")
        run.status = "AWAITING_REVIEW"
        run.worker_id = None
        run.lease_expires_at = None
        run.version += 1
        await session.commit()


async def get_generation_run(session: AsyncSession, run_id: UUID) -> WorkflowRun:
    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise WritingNotFoundError("生成任务不存在")
    return run


async def get_generation_status(session: AsyncSession, run_id: UUID) -> GenerationStatusRecord:
    run = await get_generation_run(session, run_id)
    steps = tuple(
        (
            await session.scalars(
                select(WorkflowStep)
                .where(WorkflowStep.workflow_run_id == run_id)
                .order_by(WorkflowStep.ordinal)
            )
        ).all()
    )
    generation = await session.scalar(
        select(GenerationRun)
        .join(WorkflowStep, WorkflowStep.id == GenerationRun.workflow_step_id)
        .where(WorkflowStep.workflow_run_id == run_id)
        .order_by(GenerationRun.created_at.desc())
        .limit(1)
    )
    candidate_revision_id = await session.scalar(
        select(ChapterRevision.id)
        .where(ChapterRevision.workflow_run_id == run_id)
        .order_by(ChapterRevision.revision_number.desc())
        .limit(1)
    )
    return GenerationStatusRecord(
        run=run,
        steps=steps,
        generation=generation,
        candidate_revision_id=candidate_revision_id,
    )


async def get_latest_generation_status_for_chapter(
    session: AsyncSession, chapter_id: UUID
) -> GenerationStatusRecord | None:
    chapter = await session.get(Chapter, chapter_id)
    if chapter is None:
        raise WritingNotFoundError("章节不存在")
    run_id = await session.scalar(
        select(WorkflowRun.id)
        .where(
            WorkflowRun.chapter_id == chapter_id,
            WorkflowRun.kind == "INTERACTIVE_CHAPTER_DRAFT_V1",
        )
        .order_by(WorkflowRun.created_at.desc())
        .limit(1)
    )
    if run_id is None:
        return None
    return await get_generation_status(session, run_id)


async def prepare_generation_resume(session: AsyncSession, run_id: UUID) -> GenerationHandle:
    run = await session.scalar(
        select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update()
    )
    if run is None:
        raise WritingNotFoundError("生成任务不存在")
    now = datetime.now(UTC)
    recoverable = run.status in {"PLANNED", "FAILED"} or (
        run.status == "RUNNING" and run.lease_expires_at is not None and run.lease_expires_at <= now
    )
    if not recoverable:
        raise GenerationConflictError("任务仍在执行或已经结束，不能重复恢复")
    run.status = "PLANNED"
    run.worker_id = None
    run.lease_expires_at = None
    run.version += 1
    await session.commit()
    return GenerationHandle(run_id=run.id, status=run.status, should_start=True)


async def _repair_chapter_length(
    *,
    session: AsyncSession,
    run: WorkflowRun,
    chapter: Chapter,
    writer_step: WorkflowStep,
    original_generation: GenerationRun,
    original_prose: str,
    settings: Settings,
) -> tuple[SceneProseEnvelope, GenerationRun]:
    length_policy = ProseLengthPolicy(chapter.target_char_count)
    original_visible_chars = sum(not character.isspace() for character in original_prose)
    direction = "EXPAND" if original_visible_chars < chapter.target_char_count else "TRIM"
    work = await session.get(Work, chapter.work_id)
    work_settings = work.settings_json if work is not None else {}
    rendered = get_prompt_catalog().render(
        "chapter_length_reviser",
        {
            "scene_id": str(chapter.id),
            "chapter_task": chapter.generation_brief or "保持本章既有事件与因果关系",
            "prose_length": {
                "actual": original_visible_chars,
                "direction": direction,
                "desiredNetChange": chapter.target_char_count - original_visible_chars,
                **length_policy.prompt_contract(),
            },
            "original_prose": original_prose,
            "style_contract": work_settings.get("style_contract", ""),
            "forbidden_content": work_settings.get("forbidden_content", ""),
        },
    )
    source_manifest = {
        "work_id": str(chapter.work_id),
        "chapter_id": str(chapter.id),
        "repair_of_generation_id": str(original_generation.id),
        "original_visible_chars": original_visible_chars,
    }
    budget_report = {
        "system_chars": len(rendered.system),
        "user_chars": len(rendered.user),
        "original_prose_chars": len(original_prose),
    }
    snapshot = await _get_or_create_context_snapshot(
        session=session,
        run=run,
        rendered=rendered,
        source_manifest=source_manifest,
        budget_report=budget_report,
    )
    provider, model = default_model_route(settings)
    repair_generation = GenerationRun(
        workflow_step_id=writer_step.id,
        context_snapshot_id=snapshot.id,
        prompt_key=rendered.key,
        prompt_version=rendered.version,
        prompt_fingerprint=rendered.fingerprint,
        provider=provider.value,
        endpoint="pending",
        model_snapshot=model,
        parameters={
            "max_output_tokens": settings.generation_max_output_tokens,
            "reason": "OUTPUT_LENGTH_OUT_OF_RANGE",
        },
        status="RUNNING",
        attempt=writer_step.attempt_count + 1,
        retry_of_id=original_generation.id,
    )
    writer_step.attempt_count += 1
    session.add(repair_generation)
    await session.commit()

    gateway = build_model_gateway(settings)
    try:
        output = await gateway.generate_prompt(
            provider,
            model=model,
            prompt=rendered,
            max_output_tokens=settings.generation_max_output_tokens,
            reasoning_effort="low",
        )
    except Exception as exc:
        repair_generation.status = "FAILED"
        repair_generation.error_json = {
            "code": "LENGTH_REPAIR_GENERATION_FAILED",
            "retryable": True,
            "message": str(exc),
        }
        raise ValueError(f"章节长度自动修订失败：{exc}") from exc
    finally:
        await gateway.aclose()

    raw_object = await asyncio.to_thread(
        LocalObjectStore(settings.object_store_path).put_json,
        "provider-responses",
        output.response.raw_payload,
    )
    audit = provider_audit_metadata(output.response)
    repair_generation.endpoint = str(audit["endpoint"])
    repair_generation.model_snapshot = str(audit["model_snapshot"])
    repair_generation.finish_reason = output.response.finish_reason
    repair_generation.response_status = output.response.status.value
    repair_generation.provider_request_id = output.response.request_id
    repair_generation.provider_response_id = output.response.response_id
    repair_generation.response_item_types = list(output.response.output_item_types)
    repair_generation.system_fingerprint = output.response.system_fingerprint
    repair_generation.latency_ms = output.response.latency_ms
    repair_generation.usage_json = output.response.usage
    repair_generation.raw_response_uri = raw_object.uri
    if not isinstance(output.structured, dict):
        repair_generation.status = "FAILED"
        raise ValueError("长度修订输出不是结构化对象")
    envelope, gate = parse_and_scan_scene_prose(
        output.structured,
        expected_scene_id=str(chapter.id),
        transport=TransportStatus(
            completed=True,
            refused=False,
            finish_reason=output.response.finish_reason,
        ),
    )
    if not gate.accepted:
        repair_generation.status = "FAILED"
        repair_generation.error_json = {
            "code": "LENGTH_REPAIR_PURITY_FAILED",
            "retryable": True,
            "message": "长度修订稿未通过正文纯净度检查",
        }
        raise ValueError("长度修订稿未通过正文纯净度检查")
    visible_chars = sum(not character.isspace() for character in envelope.prose)
    if not length_policy.is_sane(visible_chars):
        repair_generation.status = "REJECTED"
        repair_generation.error_json = {
            "code": "OUTPUT_LENGTH_OUT_OF_RANGE",
            "retryable": True,
            "message": (
                "自动修订后仍超出宽松安全范围："
                f"实际 {visible_chars} 字，允许 "
                f"{length_policy.hard_minimum}～{length_policy.hard_maximum} 字"
            ),
        }
        return envelope, repair_generation
    repair_generation.status = "SUCCEEDED"
    return envelope, repair_generation


async def _compile_prompt(
    session: AsyncSession,
    work: Work,
    chapter: Chapter,
    settings: Settings,
) -> tuple[RenderedPrompt, dict[str, Any], dict[str, Any]]:
    recent_statement = (
        select(Chapter, ChapterRevision, Artifact)
        .join(ChapterRevision, ChapterRevision.id == Chapter.latest_revision_id)
        .join(Artifact, Artifact.id == ChapterRevision.prose_artifact_id)
        .where(
            Chapter.work_id == work.id,
            Chapter.chapter_number < chapter.chapter_number,
        )
        .order_by(Chapter.chapter_number.desc())
        .limit(2)
    )
    recent_rows = (await session.execute(recent_statement)).all()
    recent_parts_descending: list[str] = []
    revision_ids: list[str] = []
    remaining = settings.recent_chapter_context_chars
    immediate_budget = math.ceil(remaining * 0.7) if len(recent_rows) > 1 else remaining
    previous_ending = ""
    previous_title = ""
    for index, (previous, revision, artifact) in enumerate(recent_rows):
        text = artifact.content_text or ""
        budget = min(remaining, immediate_budget) if index == 0 else remaining
        excerpt = text[-budget:] if budget else ""
        authority = "已发布规范稿" if revision.is_canonical else "当前未发布工作稿"
        recent_parts_descending.append(
            f"第{previous.chapter_number}章 {previous.title or ''}（{authority}）\n{excerpt}"
        )
        revision_ids.append(str(revision.id))
        remaining = max(0, remaining - len(excerpt))
        if index == 0:
            previous_ending = text[-1200:]
            previous_title = previous.title or f"第{previous.chapter_number}章"

    brief = chapter.generation_brief or "依据当前故事自然推进一章，保持因果连续。"
    beats = [line.strip(" -") for line in brief.splitlines() if line.strip()]
    if not beats:
        beats = [brief]
    scene_plan = {
        "sceneId": str(chapter.id),
        "chapterNumber": chapter.chapter_number,
        "chapterTitle": chapter.title,
        "objective": brief,
        "beats": beats,
        "requiredProgression": [
            "开篇直接承接前章未决动作或建立本章即时处境",
            "让主角采取有明确目标的行动并遭遇第一重阻力",
            "通过至少两轮有效互动升级冲突或信息差",
            "产生会改变人物判断或局势的阶段结果",
            "以新压力、新信息或未完成行动形成章末钩子",
        ],
        "targetCharCount": chapter.target_char_count,
        "proseLength": ProseLengthPolicy(chapter.target_char_count).prompt_contract(),
        "continuity": {
            "previousChapterTitle": previous_title or None,
            "previousEnding": previous_ending,
            "rule": (
                "开篇先承接前章结尾仍在进行的动作、对话和在场人物，再推进本章任务；"
                "允许暂不解谜，但不允许无解释地跳时空或让人物消失。"
            ),
        },
    }
    global_context = {
        "corePitch": work.settings_json.get("core_pitch"),
        "themes": work.settings_json.get("themes"),
        "mainPlot": work.settings_json.get("main_plot"),
        "outline": work.settings_json.get("outline_markdown"),
        "endingConstraints": work.settings_json.get("ending_constraints"),
        "storyBible": work.settings_json.get(
            "story_bible", work.settings_json.get("canonical_facts", [])
        ),
    }
    rendered = get_prompt_catalog().render(
        "scene_writer",
        {
            "scene_plan": scene_plan,
            "canonical_facts": global_context,
            "draft_overlay": {},
            "recent_prose": "\n\n".join(reversed(recent_parts_descending)),
            "style_contract": work.settings_json.get(
                "style_contract", "中文网络小说；叙事清晰；场景化表达；避免总结腔。"
            ),
            "forbidden_content": work.settings_json.get("forbidden_content", []),
        },
    )
    source_manifest = {
        "work_id": str(work.id),
        "chapter_id": str(chapter.id),
        "work_version": work.version,
        "chapter_version": chapter.version,
        "recent_revision_ids": revision_ids,
        "recent_revision_authority": "latest_revision_including_unpublished_draft",
    }
    budget_report = {
        "system_chars": len(rendered.system),
        "user_chars": len(rendered.user),
        "recent_context_chars": sum(len(part) for part in recent_parts_descending),
    }
    return rendered, source_manifest, budget_report


async def _get_or_create_context_snapshot(
    *,
    session: AsyncSession,
    run: WorkflowRun,
    rendered: RenderedPrompt,
    source_manifest: dict[str, Any],
    budget_report: dict[str, Any],
) -> ContextSnapshot:
    digest = hashlib.sha256(
        canonical_json(
            {
                "system": rendered.system,
                "user": rendered.user,
                "sources": source_manifest,
            }
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
        prompt_key=rendered.key,
        prompt_version=rendered.version,
        prompt_fingerprint=rendered.fingerprint,
        exact_system_text=rendered.system,
        exact_user_text=rendered.user,
        source_manifest=source_manifest,
        budget_report=budget_report,
        content_hash=digest,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def _mark_step(
    session: AsyncSession, run_id: UUID, step_key: str, status: str
) -> WorkflowStep:
    step = await session.scalar(
        select(WorkflowStep).where(
            WorkflowStep.workflow_run_id == run_id,
            WorkflowStep.step_key == step_key,
        )
    )
    if step is None:
        raise RuntimeError(f"workflow step missing: {step_key}")
    step.status = status
    return step


async def _latest_revision_number(session: AsyncSession, chapter: Chapter) -> int:
    if chapter.latest_revision_id is None:
        return 0
    revision = await session.get(ChapterRevision, chapter.latest_revision_id)
    return revision.revision_number if revision is not None else 0


async def _fail_run(session: AsyncSession, run: WorkflowRun, code: str, message: str) -> None:
    run.status = "FAILED"
    run.worker_id = None
    run.lease_expires_at = None
    run.version += 1
    chapter = await session.get(Chapter, run.chapter_id)
    if chapter is not None:
        latest_revision = (
            await session.get(ChapterRevision, chapter.latest_revision_id)
            if chapter.latest_revision_id is not None
            else None
        )
        if latest_revision is None:
            chapter.status = "PLANNED"
        elif latest_revision.is_canonical:
            chapter.status = "COMMITTED"
        elif latest_revision.source == "MODEL":
            chapter.status = "REVIEW"
        else:
            chapter.status = "DRAFT"
        chapter.version += 1
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
