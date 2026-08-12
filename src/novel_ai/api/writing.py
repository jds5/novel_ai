from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from novel_ai.api.schemas import (
    ChapterContentUpdate,
    ChapterCreate,
    ChapterDetail,
    ChapterPage,
    ChapterRevisionDetail,
    ChapterRevisionPage,
    ChapterRevisionSummary,
    ChapterSummary,
    ChapterUpdate,
    GenerationHandleResponse,
    GenerationStatusResponse,
    WorkCreate,
    WorkDetail,
    WorkflowStepResponse,
    WorkPlanningCandidate,
    WorkPlanningGenerationRequest,
    WorkSummary,
    WorkUpdate,
)
from novel_ai.application.generation import (
    GenerationStatusRecord,
    create_generation_run,
    get_generation_status,
    get_latest_generation_status_for_chapter,
    prepare_generation_resume,
    schedule_generation_run,
)
from novel_ai.application.planning import (
    create_work_planning_run,
    get_work_planning_candidate,
)
from novel_ai.application.writing import (
    ChapterRecord,
    RevisionRecord,
    WorkRecord,
    create_chapter,
    create_work,
    get_chapter,
    get_chapter_revision,
    get_work,
    list_chapter_revisions,
    list_chapters,
    list_works,
    publish_revision,
    save_chapter_content,
    update_chapter_metadata,
    update_work_settings,
)
from novel_ai.config import get_settings
from novel_ai.db.session import get_session

router = APIRouter(tags=["writing"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/works", response_model=list[WorkSummary])
async def works(session: SessionDep) -> list[WorkSummary]:
    return [_work_summary(record) for record in await list_works(session)]


@router.post("/works", response_model=WorkDetail, status_code=status.HTTP_201_CREATED)
async def add_work(request: WorkCreate, session: SessionDep) -> WorkDetail:
    record = await create_work(session, title=request.title, description=request.description)
    return _work_detail(record)


@router.get("/works/{work_id}", response_model=WorkDetail)
async def work_detail(work_id: UUID, session: SessionDep) -> WorkDetail:
    work = await get_work(session, work_id)
    records = await list_works(session)
    record = next(item for item in records if item.work.id == work.id)
    return _work_detail(record)


@router.patch("/works/{work_id}", response_model=WorkDetail)
async def edit_work(
    work_id: UUID,
    request: WorkUpdate,
    session: SessionDep,
) -> WorkDetail:
    await update_work_settings(
        session,
        work_id=work_id,
        expected_version=request.expected_version,
        description=request.description,
        core_pitch=request.core_pitch,
        themes=request.themes,
        main_plot=request.main_plot,
        outline_markdown=request.outline_markdown,
        ending_constraints=request.ending_constraints,
        story_bible=request.story_bible,
        style_contract=request.style_contract,
        forbidden_content=request.forbidden_content,
    )
    records = await list_works(session)
    record = next(item for item in records if item.work.id == work_id)
    return _work_detail(record)


@router.post(
    "/works/{work_id}/planning-generation-runs",
    response_model=GenerationHandleResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_work_planning(
    work_id: UUID,
    request: WorkPlanningGenerationRequest,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
) -> GenerationHandleResponse:
    handle = await create_work_planning_run(
        session,
        work_id=work_id,
        idempotency_key=idempotency_key,
        author_intent=request.author_intent,
        prior_core_pitches=request.prior_core_pitches,
        prior_candidate_hashes=request.prior_candidate_hashes,
    )
    if handle.should_start:
        schedule_generation_run(handle.run_id)
    return GenerationHandleResponse(run_id=handle.run_id, status=handle.status)


@router.get(
    "/workflow-runs/{run_id}/planning-candidate",
    response_model=WorkPlanningCandidate,
)
async def work_planning_candidate(run_id: UUID, session: SessionDep) -> WorkPlanningCandidate:
    candidate, candidate_hash = await get_work_planning_candidate(session, run_id)
    return WorkPlanningCandidate.model_validate({**candidate, "contentHash": candidate_hash})


@router.get("/works/{work_id}/chapters", response_model=ChapterPage)
async def chapters(
    work_id: UUID,
    session: SessionDep,
    after: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=100),
) -> ChapterPage:
    records, next_after = await list_chapters(
        session,
        work_id=work_id,
        after_chapter_number=after,
        limit=limit,
    )
    return ChapterPage(
        items=[_chapter_summary(record) for record in records], next_after=next_after
    )


@router.post(
    "/works/{work_id}/chapters",
    response_model=ChapterDetail,
    status_code=status.HTTP_201_CREATED,
)
async def add_chapter(
    work_id: UUID,
    request: ChapterCreate,
    session: SessionDep,
) -> ChapterDetail:
    record = await create_chapter(
        session,
        work_id=work_id,
        title=request.title,
        generation_brief=request.generation_brief,
        target_char_count=request.target_char_count,
        chapter_number=request.chapter_number,
    )
    return _chapter_detail(record)


@router.get("/chapters/{chapter_id}", response_model=ChapterDetail)
async def chapter_detail(chapter_id: UUID, session: SessionDep) -> ChapterDetail:
    return _chapter_detail(await get_chapter(session, chapter_id))


@router.patch("/chapters/{chapter_id}", response_model=ChapterDetail)
async def edit_chapter(
    chapter_id: UUID,
    request: ChapterUpdate,
    session: SessionDep,
) -> ChapterDetail:
    record = await update_chapter_metadata(
        session,
        chapter_id=chapter_id,
        expected_version=request.expected_version,
        title=request.title,
        generation_brief=request.generation_brief,
        target_char_count=request.target_char_count,
    )
    return _chapter_detail(record)


@router.put("/chapters/{chapter_id}/content", response_model=ChapterDetail)
async def save_content(
    chapter_id: UUID,
    request: ChapterContentUpdate,
    session: SessionDep,
) -> ChapterDetail:
    record = await save_chapter_content(
        session,
        chapter_id=chapter_id,
        content=request.content,
        expected_revision_number=request.expected_revision_number,
        max_chars=get_settings().max_chapter_chars,
    )
    return _chapter_detail(record)


@router.get("/chapters/{chapter_id}/revisions", response_model=ChapterRevisionPage)
async def chapter_revisions(
    chapter_id: UUID,
    session: SessionDep,
    before: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> ChapterRevisionPage:
    records, next_before = await list_chapter_revisions(
        session,
        chapter_id=chapter_id,
        before_revision_number=before,
        limit=limit,
    )
    return ChapterRevisionPage(
        items=[_revision_summary(record) for record in records],
        next_before=next_before,
    )


@router.get(
    "/chapters/{chapter_id}/revisions/{revision_id}",
    response_model=ChapterRevisionDetail,
)
async def chapter_revision_detail(
    chapter_id: UUID,
    revision_id: UUID,
    session: SessionDep,
) -> ChapterRevisionDetail:
    record = await get_chapter_revision(session, chapter_id=chapter_id, revision_id=revision_id)
    summary = _revision_summary(record)
    if record.content_hash is None:
        raise RuntimeError("revision artifact has no content hash")
    return ChapterRevisionDetail(
        **summary.model_dump(),
        content=record.content,
        content_hash=record.content_hash,
    )


@router.post(
    "/chapters/{chapter_id}/revisions/{revision_id}/publish",
    response_model=ChapterDetail,
)
async def publish(
    chapter_id: UUID,
    revision_id: UUID,
    session: SessionDep,
) -> ChapterDetail:
    return _chapter_detail(
        await publish_revision(session, chapter_id=chapter_id, revision_id=revision_id)
    )


@router.post(
    "/chapters/{chapter_id}/generation-runs",
    response_model=GenerationHandleResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate(
    chapter_id: UUID,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
) -> GenerationHandleResponse:
    handle = await create_generation_run(
        session, chapter_id=chapter_id, idempotency_key=idempotency_key
    )
    if handle.should_start:
        schedule_generation_run(handle.run_id)
    return GenerationHandleResponse(run_id=handle.run_id, status=handle.status)


@router.get("/workflow-runs/{run_id}", response_model=GenerationStatusResponse)
async def generation_status(run_id: UUID, session: SessionDep) -> GenerationStatusResponse:
    record = await get_generation_status(session, run_id)
    return _generation_status_response(record)


@router.get(
    "/chapters/{chapter_id}/generation-runs/latest",
    response_model=GenerationStatusResponse | None,
)
async def latest_chapter_generation(
    chapter_id: UUID, session: SessionDep
) -> GenerationStatusResponse | None:
    record = await get_latest_generation_status_for_chapter(session, chapter_id)
    return _generation_status_response(record) if record is not None else None


def _generation_status_response(record: GenerationStatusRecord) -> GenerationStatusResponse:
    generation = record.generation
    return GenerationStatusResponse(
        run_id=record.run.id,
        chapter_id=record.run.chapter_id,
        status=record.run.status,
        version=record.run.version,
        steps=[
            WorkflowStepResponse(
                key=step.step_key,
                ordinal=step.ordinal,
                status=step.status,
                attempt_count=step.attempt_count,
                error=step.error_json,
            )
            for step in record.steps
        ],
        provider=generation.provider if generation is not None else None,
        model=generation.model_snapshot if generation is not None else None,
        usage=generation.usage_json if generation is not None else None,
        error=generation.error_json if generation is not None else None,
        candidate_revision_id=record.candidate_revision_id,
        lease_expires_at=record.run.lease_expires_at,
        updated_at=record.run.updated_at,
    )


@router.post("/workflow-runs/{run_id}/resume", response_model=GenerationHandleResponse)
async def resume_generation(run_id: UUID, session: SessionDep) -> GenerationHandleResponse:
    handle = await prepare_generation_resume(session, run_id)
    schedule_generation_run(handle.run_id)
    return GenerationHandleResponse(run_id=handle.run_id, status=handle.status)


def _work_summary(record: WorkRecord) -> WorkSummary:
    return WorkSummary(
        id=record.work.id,
        title=record.work.title,
        description=record.work.description,
        status=record.work.status,
        chapter_count=record.chapter_count,
        total_char_count=record.total_char_count,
        version=record.work.version,
        updated_at=record.work.updated_at,
    )


def _work_detail(record: WorkRecord) -> WorkDetail:
    summary = _work_summary(record)
    return WorkDetail(
        **summary.model_dump(),
        settings=record.work.settings_json,
        commit_sequence=record.work.commit_sequence,
    )


def _chapter_summary(record: ChapterRecord) -> ChapterSummary:
    revision = record.revision
    return ChapterSummary(
        id=record.chapter.id,
        work_id=record.chapter.work_id,
        chapter_number=record.chapter.chapter_number,
        title=record.chapter.title,
        status=record.chapter.status,
        version=record.chapter.version,
        latest_revision_id=revision.id if revision is not None else None,
        latest_revision_number=revision.revision_number if revision is not None else 0,
        latest_revision_source=revision.source if revision is not None else None,
        is_canonical=revision.is_canonical if revision is not None else False,
        char_count=revision.char_count if revision is not None else 0,
        updated_at=record.chapter.updated_at,
    )


def _chapter_detail(record: ChapterRecord) -> ChapterDetail:
    summary = _chapter_summary(record)
    return ChapterDetail(
        **summary.model_dump(),
        summary=record.chapter.summary,
        generation_brief=record.chapter.generation_brief,
        target_char_count=record.chapter.target_char_count,
        content=record.content,
        content_hash=record.content_hash,
    )


def _revision_summary(record: RevisionRecord) -> ChapterRevisionSummary:
    revision = record.revision
    return ChapterRevisionSummary(
        id=revision.id,
        revision_number=revision.revision_number,
        parent_revision_id=revision.parent_revision_id,
        source=revision.source,
        char_count=revision.char_count,
        is_canonical=revision.is_canonical,
        canonical_commit_sequence=revision.canonical_commit_sequence,
        workflow_run_id=revision.workflow_run_id,
        created_at=revision.created_at,
    )
