from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from novel_ai.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Work(TimestampMixin, Base):
    __tablename__ = "works"
    __table_args__ = (
        CheckConstraint("commit_sequence >= 0", name="commit_sequence_nonnegative"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    commit_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Chapter(TimestampMixin, Base):
    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("work_id", "chapter_number"),
        CheckConstraint("chapter_number >= 1", name="chapter_number_positive"),
        CheckConstraint("target_char_count >= 100", name="target_char_count_minimum"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    work_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("works.id", ondelete="CASCADE"), nullable=False
    )
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text)
    generation_brief: Mapped[str | None] = mapped_column(Text)
    target_char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=2500)
    latest_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "chapter_revisions.id",
            name="fk_chapters_latest_revision_id_chapter_revisions",
            ondelete="SET NULL",
            use_alter=True,
        ),
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PLANNED")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint(
            "(content_text IS NULL) <> (content_json IS NULL)", name="exactly_one_content"
        ),
        CheckConstraint("schema_version >= 1", name="schema_version_positive"),
        UniqueConstraint("work_id", "kind", "content_hash"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    work_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("works.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_text: Mapped[str | None] = mapped_column(Text)
    content_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False, default="application/json")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="VALID")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkflowRun(TimestampMixin, Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint("baseline_commit_sequence >= 0", name="baseline_sequence_nonnegative"),
        CheckConstraint("version >= 1", name="version_positive"),
        UniqueConstraint("work_id", "idempotency_key"),
        Index("ix_workflow_runs_recovery", "status", "lease_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    work_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("works.id", ondelete="CASCADE"), nullable=False
    )
    chapter_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PLANNED")
    baseline_commit_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(80))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class WorkflowStep(TimestampMixin, Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (
        UniqueConstraint("workflow_run_id", "step_key"),
        CheckConstraint("ordinal >= 1", name="ordinal_positive"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    step_key: Mapped[str] = mapped_column(String(80), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    input_fingerprint: Mapped[str | None] = mapped_column(String(64))
    output_artifact_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="SET NULL")
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ArtifactDependency(Base):
    __tablename__ = "artifact_dependencies"

    input_artifact_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="CASCADE"), primary_key=True
    )
    output_artifact_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="CASCADE"), primary_key=True
    )
    workflow_step_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workflow_steps.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ContextSnapshot(Base):
    __tablename__ = "context_snapshots"
    __table_args__ = (UniqueConstraint("work_id", "content_hash"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    work_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("works.id", ondelete="CASCADE"), nullable=False
    )
    baseline_commit_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    prompt_key: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    exact_system_text: Mapped[str] = mapped_column(Text, nullable=False)
    exact_user_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    budget_report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GenerationRun(Base):
    __tablename__ = "generation_runs"
    __table_args__ = (
        CheckConstraint("attempt >= 1", name="attempt_positive"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="latency_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_step_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workflow_steps.id", ondelete="CASCADE"), nullable=False
    )
    context_snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("context_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    prompt_key: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(300), nullable=False)
    model_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    finish_reason: Mapped[str | None] = mapped_column(String(80))
    response_status: Mapped[str | None] = mapped_column(String(32))
    provider_request_id: Mapped[str | None] = mapped_column(String(200))
    provider_response_id: Mapped[str | None] = mapped_column(String(200))
    response_item_types: Mapped[list[str] | None] = mapped_column(JSONB)
    system_fingerprint: Mapped[str | None] = mapped_column(String(200))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output_artifact_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="SET NULL")
    )
    raw_response_uri: Mapped[str | None] = mapped_column(Text)
    retry_of_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("generation_runs.id", ondelete="SET NULL")
    )
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChapterRevision(Base):
    __tablename__ = "chapter_revisions"
    __table_args__ = (
        UniqueConstraint("chapter_id", "revision_number"),
        CheckConstraint("revision_number >= 1", name="revision_number_positive"),
        CheckConstraint("char_count >= 0", name="char_count_nonnegative"),
        Index(
            "uq_chapter_revisions_one_canonical",
            "chapter_id",
            unique=True,
            postgresql_where=text("is_canonical"),
        ),
        Index("ix_chapter_revisions_chapter_created", "chapter_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    chapter_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    prose_artifact_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False
    )
    workflow_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="RESTRICT")
    )
    parent_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("chapter_revisions.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="HUMAN")
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    canonical_commit_sequence: Mapped[int | None] = mapped_column(BigInteger)
    is_canonical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChangeSet(Base):
    __tablename__ = "change_sets"
    __table_args__ = (
        CheckConstraint("baseline_commit_sequence >= 0", name="baseline_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    proposal_artifact_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False
    )
    validation_artifact_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="RESTRICT")
    )
    baseline_commit_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PROPOSED")
    proposal_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    validated_proposal_hash: Mapped[str | None] = mapped_column(String(64))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EventTypeDefinition(Base):
    __tablename__ = "event_type_definitions"
    __table_args__ = (CheckConstraint("version >= 1", name="version_positive"),)

    event_type: Mapped[str] = mapped_column(String(80), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    projector_name: Mapped[str] = mapped_column(String(160), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StoryEvent(Base):
    __tablename__ = "story_events"
    __table_args__ = (
        UniqueConstraint("work_id", "sequence"),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint("projector_version >= 1", name="projector_version_positive"),
        ForeignKeyConstraint(
            ["event_type", "projector_version"],
            ["event_type_definitions.event_type", "event_type_definitions.version"],
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    work_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("works.id", ondelete="CASCADE"), nullable=False
    )
    chapter_revision_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chapter_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    projector_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ItemOwnershipProjection(Base):
    __tablename__ = "item_ownership_projection"
    __table_args__ = (CheckConstraint("source_sequence >= 1", name="source_sequence_positive"),)

    work_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("works.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    owner_entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("story_events.id", ondelete="RESTRICT"), nullable=False
    )
    source_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SemanticMemory(Base):
    __tablename__ = "semantic_memories"
    __table_args__ = (
        UniqueConstraint("source_artifact_id", "namespace", "embedding_model", "embedding_hash"),
        CheckConstraint("visible_from_sequence >= 0", name="visible_sequence_nonnegative"),
        CheckConstraint("embedding_dimensions > 0", name="embedding_dimensions_positive"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    work_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("works.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_artifact_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    namespace: Mapped[str] = mapped_column(String(80), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(160), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False)
    visible_from_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    visible_until_sequence: Mapped[int | None] = mapped_column(BigInteger)
    must_not_reveal_before_chapter: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    work_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("works.id", ondelete="CASCADE"), nullable=False
    )
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
