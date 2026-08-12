from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from novel_ai.db.models import (
    Artifact,
    Chapter,
    ChapterRevision,
    OutboxEvent,
    Work,
    WorkflowRun,
    WorkflowStep,
)
from novel_ai.domain.artifacts import content_hash, normalize_text
from novel_ai.domain.prose_purity import TransportStatus, scan_prose


class WritingError(RuntimeError):
    pass


class WritingNotFoundError(WritingError):
    pass


class WritingConflictError(WritingError):
    pass


class WritingValidationError(WritingError):
    pass


@dataclass(frozen=True, slots=True)
class WorkRecord:
    work: Work
    chapter_count: int
    total_char_count: int


@dataclass(frozen=True, slots=True)
class ChapterRecord:
    chapter: Chapter
    revision: ChapterRevision | None
    content: str
    content_hash: str | None


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    revision: ChapterRevision
    content: str = ""
    content_hash: str | None = None


async def list_works(session: AsyncSession) -> list[WorkRecord]:
    statement = (
        select(
            Work,
            func.count(Chapter.id),
            func.coalesce(func.sum(ChapterRevision.char_count), 0),
        )
        .outerjoin(Chapter, Chapter.work_id == Work.id)
        .outerjoin(ChapterRevision, ChapterRevision.id == Chapter.latest_revision_id)
        .group_by(Work.id)
        .order_by(Work.updated_at.desc(), Work.created_at.desc())
    )
    rows = (await session.execute(statement)).all()
    return [
        WorkRecord(work=work, chapter_count=int(count), total_char_count=int(char_count))
        for work, count, char_count in rows
    ]


async def create_work(
    session: AsyncSession,
    *,
    title: str,
    description: str | None,
    settings: dict[str, Any] | None = None,
) -> WorkRecord:
    clean_title = title.strip()
    if not clean_title:
        raise WritingValidationError("作品标题不能为空")
    work = Work(
        title=clean_title,
        description=_optional_text(description),
        settings_json=settings or {},
    )
    session.add(work)
    await session.commit()
    await session.refresh(work)
    return WorkRecord(work=work, chapter_count=0, total_char_count=0)


async def get_work(session: AsyncSession, work_id: UUID) -> Work:
    work = await session.get(Work, work_id)
    if work is None:
        raise WritingNotFoundError("作品不存在")
    return work


async def update_work_settings(
    session: AsyncSession,
    *,
    work_id: UUID,
    expected_version: int,
    description: str | None,
    core_pitch: str | None,
    themes: str | None,
    main_plot: str | None,
    outline_markdown: str | None,
    ending_constraints: str | None,
    story_bible: str | None,
    style_contract: str | None,
    forbidden_content: str | None,
) -> Work:
    work = await session.scalar(select(Work).where(Work.id == work_id).with_for_update())
    if work is None:
        raise WritingNotFoundError("作品不存在")
    if work.version != expected_version:
        raise WritingConflictError("作品设定已被其他操作更新，请刷新后重试")
    settings = dict(work.settings_json)
    for key, value in {
        "core_pitch": core_pitch,
        "themes": themes,
        "main_plot": main_plot,
        "outline_markdown": outline_markdown,
        "ending_constraints": ending_constraints,
        "story_bible": story_bible,
        "style_contract": style_contract,
        "forbidden_content": forbidden_content,
    }.items():
        clean = _optional_text(value)
        if clean is None:
            settings.pop(key, None)
        else:
            settings[key] = clean
    work.description = _optional_text(description)
    work.settings_json = settings
    work.version += 1
    await session.commit()
    await session.refresh(work)
    return work


async def list_chapters(
    session: AsyncSession,
    *,
    work_id: UUID,
    after_chapter_number: int | None,
    limit: int,
) -> tuple[list[ChapterRecord], int | None]:
    await get_work(session, work_id)
    statement = (
        select(Chapter, ChapterRevision)
        .outerjoin(ChapterRevision, ChapterRevision.id == Chapter.latest_revision_id)
        .where(Chapter.work_id == work_id)
        .order_by(Chapter.chapter_number)
        .limit(limit + 1)
    )
    if after_chapter_number is not None:
        statement = statement.where(Chapter.chapter_number > after_chapter_number)
    rows = (await session.execute(statement)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    records = [
        ChapterRecord(chapter=chapter, revision=revision, content="", content_hash=None)
        for chapter, revision in rows
    ]
    next_after = records[-1].chapter.chapter_number if has_more and records else None
    return records, next_after


async def create_chapter(
    session: AsyncSession,
    *,
    work_id: UUID,
    title: str | None,
    generation_brief: str | None,
    target_char_count: int,
    chapter_number: int | None = None,
) -> ChapterRecord:
    work = await get_work(session, work_id)
    if target_char_count < 100:
        raise WritingValidationError("目标字数不能少于 100")
    if chapter_number is None:
        maximum = await session.scalar(
            select(func.max(Chapter.chapter_number)).where(Chapter.work_id == work_id)
        )
        chapter_number = int(maximum or 0) + 1
    chapter = Chapter(
        work_id=work_id,
        chapter_number=chapter_number,
        title=_optional_text(title),
        generation_brief=_optional_text(generation_brief),
        target_char_count=target_char_count,
    )
    work.version += 1
    session.add(chapter)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await session.refresh(chapter)
    return ChapterRecord(chapter=chapter, revision=None, content="", content_hash=None)


async def get_chapter(session: AsyncSession, chapter_id: UUID) -> ChapterRecord:
    statement = (
        select(Chapter, ChapterRevision, Artifact)
        .outerjoin(ChapterRevision, ChapterRevision.id == Chapter.latest_revision_id)
        .outerjoin(Artifact, Artifact.id == ChapterRevision.prose_artifact_id)
        .where(Chapter.id == chapter_id)
    )
    row = (await session.execute(statement)).one_or_none()
    if row is None:
        raise WritingNotFoundError("章节不存在")
    chapter, revision, artifact = row
    content = artifact.content_text if artifact is not None else ""
    artifact_hash = artifact.content_hash if artifact is not None else None
    return ChapterRecord(
        chapter=chapter,
        revision=revision,
        content=content or "",
        content_hash=artifact_hash,
    )


async def list_chapter_revisions(
    session: AsyncSession,
    *,
    chapter_id: UUID,
    before_revision_number: int | None,
    limit: int,
) -> tuple[list[RevisionRecord], int | None]:
    await _get_chapter_entity(session, chapter_id)
    statement = (
        select(ChapterRevision)
        .where(ChapterRevision.chapter_id == chapter_id)
        .order_by(ChapterRevision.revision_number.desc())
        .limit(limit + 1)
    )
    if before_revision_number is not None:
        statement = statement.where(ChapterRevision.revision_number < before_revision_number)
    revisions = list((await session.scalars(statement)).all())
    has_more = len(revisions) > limit
    revisions = revisions[:limit]
    records = [RevisionRecord(revision=revision) for revision in revisions]
    next_before = records[-1].revision.revision_number if has_more and records else None
    return records, next_before


async def get_chapter_revision(
    session: AsyncSession, *, chapter_id: UUID, revision_id: UUID
) -> RevisionRecord:
    row = (
        await session.execute(
            select(ChapterRevision, Artifact)
            .join(Artifact, Artifact.id == ChapterRevision.prose_artifact_id)
            .where(
                ChapterRevision.id == revision_id,
                ChapterRevision.chapter_id == chapter_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise WritingNotFoundError("正文版本不存在")
    revision, artifact = row
    return RevisionRecord(
        revision=revision,
        content=artifact.content_text or "",
        content_hash=artifact.content_hash,
    )


async def update_chapter_metadata(
    session: AsyncSession,
    *,
    chapter_id: UUID,
    expected_version: int,
    title: str | None,
    generation_brief: str | None,
    target_char_count: int,
) -> ChapterRecord:
    chapter = await session.scalar(
        select(Chapter).where(Chapter.id == chapter_id).with_for_update()
    )
    if chapter is None:
        raise WritingNotFoundError("章节不存在")
    if chapter.version != expected_version:
        raise WritingConflictError("章节元数据已被其他操作更新，请刷新后重试")
    if target_char_count < 100:
        raise WritingValidationError("目标字数不能少于 100")
    chapter.title = _optional_text(title)
    chapter.generation_brief = _optional_text(generation_brief)
    chapter.target_char_count = target_char_count
    chapter.version += 1
    await session.commit()
    return await get_chapter(session, chapter_id)


async def save_chapter_content(
    session: AsyncSession,
    *,
    chapter_id: UUID,
    content: str,
    expected_revision_number: int,
    max_chars: int,
    source: str = "HUMAN",
    workflow_run_id: UUID | None = None,
    gate_passed: bool = False,
    commit: bool = True,
) -> ChapterRecord:
    normalized = normalize_text(content)
    if len(normalized) > max_chars:
        raise WritingValidationError(f"单章正文不能超过 {max_chars} 个字符")
    chapter = await session.scalar(
        select(Chapter).where(Chapter.id == chapter_id).with_for_update()
    )
    if chapter is None:
        raise WritingNotFoundError("章节不存在")
    current_revision = (
        await session.get(ChapterRevision, chapter.latest_revision_id)
        if chapter.latest_revision_id is not None
        else None
    )
    current_number = current_revision.revision_number if current_revision is not None else 0
    if current_number != expected_revision_number:
        raise WritingConflictError("正文已经产生新版本，请刷新后再保存")

    digest = content_hash(text=normalized)
    if current_revision is not None:
        current_artifact = await session.get(Artifact, current_revision.prose_artifact_id)
        if (
            source == "HUMAN"
            and current_artifact is not None
            and current_artifact.content_hash == digest
        ):
            if commit:
                await session.commit()
            return await get_chapter(session, chapter_id)

    artifact = await session.scalar(
        select(Artifact).where(
            Artifact.work_id == chapter.work_id,
            Artifact.kind == "CHAPTER_PROSE",
            Artifact.content_hash == digest,
        )
    )
    if artifact is None:
        artifact = Artifact(
            work_id=chapter.work_id,
            kind="CHAPTER_PROSE",
            schema_version=1,
            content_text=normalized,
            content_hash=digest,
            media_type="text/markdown; charset=utf-8",
            status="GATE_PASSED" if gate_passed else "VALID",
        )
        session.add(artifact)
        await session.flush()
    elif gate_passed:
        artifact.status = "GATE_PASSED"
    revision = ChapterRevision(
        chapter_id=chapter.id,
        revision_number=current_number + 1,
        prose_artifact_id=artifact.id,
        workflow_run_id=workflow_run_id,
        parent_revision_id=current_revision.id if current_revision is not None else None,
        source=source,
        char_count=_visible_char_count(normalized),
        is_canonical=False,
    )
    session.add(revision)
    await session.flush()
    chapter.latest_revision_id = revision.id
    chapter.status = "REVIEW" if source == "MODEL" else "DRAFT"
    chapter.version += 1
    if commit:
        await session.commit()
    else:
        await session.flush()
    return await get_chapter(session, chapter_id)


async def publish_revision(
    session: AsyncSession,
    *,
    chapter_id: UUID,
    revision_id: UUID,
) -> ChapterRecord:
    chapter = await session.scalar(
        select(Chapter).where(Chapter.id == chapter_id).with_for_update()
    )
    if chapter is None:
        raise WritingNotFoundError("章节不存在")
    work = await session.scalar(select(Work).where(Work.id == chapter.work_id).with_for_update())
    revision = await session.get(ChapterRevision, revision_id)
    if work is None or revision is None or revision.chapter_id != chapter.id:
        raise WritingNotFoundError("正文版本不存在")
    if revision.is_canonical:
        await session.rollback()
        return await get_chapter(session, chapter_id)
    artifact = await session.get(Artifact, revision.prose_artifact_id)
    if artifact is None or artifact.content_text is None:
        raise WritingValidationError("正文产物不可用")
    if _visible_char_count(artifact.content_text) == 0:
        raise WritingValidationError("空正文不能发布")
    gate = scan_prose(
        artifact.content_text,
        TransportStatus(completed=True, finish_reason="completed"),
        allow_markdown_headings=True,
    )
    if not gate.accepted:
        raise WritingValidationError("正文纯净度检查未通过，不能发布")

    canonical = await session.scalar(
        select(ChapterRevision).where(
            ChapterRevision.chapter_id == chapter.id,
            ChapterRevision.is_canonical.is_(True),
        )
    )
    if canonical is not None and canonical.id != revision.id:
        canonical.is_canonical = False
        await session.flush()
    next_sequence = work.commit_sequence + 1
    revision.is_canonical = True
    revision.canonical_commit_sequence = next_sequence
    artifact.status = "GATE_PASSED"
    chapter.latest_revision_id = revision.id
    chapter.status = "COMMITTED"
    chapter.version += 1
    work.commit_sequence = next_sequence
    work.version += 1
    if revision.workflow_run_id is not None:
        workflow_run = await session.get(WorkflowRun, revision.workflow_run_id)
        if workflow_run is not None:
            workflow_run.status = "COMPLETED"
            workflow_run.version += 1
            review_step = await session.scalar(
                select(WorkflowStep).where(
                    WorkflowStep.workflow_run_id == workflow_run.id,
                    WorkflowStep.step_key == "review_candidate",
                )
            )
            if review_step is not None:
                review_step.status = "SUCCEEDED"
    session.add(
        OutboxEvent(
            work_id=work.id,
            topic="chapter.published",
            aggregate_id=chapter.id,
            payload={
                "chapter_id": str(chapter.id),
                "revision_id": str(revision.id),
                "commit_sequence": next_sequence,
            },
        )
    )
    await session.commit()
    return await get_chapter(session, chapter_id)


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _visible_char_count(content: str) -> int:
    return sum(not character.isspace() for character in content)


async def _get_chapter_entity(session: AsyncSession, chapter_id: UUID) -> Chapter:
    chapter = await session.get(Chapter, chapter_id)
    if chapter is None:
        raise WritingNotFoundError("章节不存在")
    return chapter
