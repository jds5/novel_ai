"""Create the deterministic workflow and memory foundation.

Revision ID: 0001_core_foundation
Revises:
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_core_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "works",
        sa.Column("id", UUID, nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("commit_sequence", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "commit_sequence >= 0", name=op.f("ck_works_commit_sequence_nonnegative")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_works_version_positive")),
        sa.PrimaryKeyConstraint("id", name="pk_works"),
    )
    op.create_table(
        "chapters",
        sa.Column("id", UUID, nullable=False),
        sa.Column("work_id", UUID, nullable=False),
        sa.Column("chapter_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("chapter_number >= 1", name=op.f("ck_chapters_chapter_number_positive")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_chapters_version_positive")),
        sa.ForeignKeyConstraint(
            ["work_id"], ["works.id"], ondelete="CASCADE", name="fk_chapters_work_id_works"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chapters"),
        sa.UniqueConstraint("work_id", "chapter_number", name="uq_chapters_work_id"),
    )
    op.create_table(
        "artifacts",
        sa.Column("id", UUID, nullable=False),
        sa.Column("work_id", UUID, nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("content_json", JSONB, nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(content_text IS NULL) <> (content_json IS NULL)",
            name=op.f("ck_artifacts_exactly_one_content"),
        ),
        sa.CheckConstraint(
            "schema_version >= 1", name=op.f("ck_artifacts_schema_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["work_id"], ["works.id"], ondelete="CASCADE", name="fk_artifacts_work_id_works"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_artifacts"),
        sa.UniqueConstraint("work_id", "kind", "content_hash", name="uq_artifacts_work_id"),
    )
    op.create_table(
        "workflow_runs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("work_id", UUID, nullable=False),
        sa.Column("chapter_id", UUID, nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("baseline_commit_sequence", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "baseline_commit_sequence >= 0",
            name=op.f("ck_workflow_runs_baseline_sequence_nonnegative"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_workflow_runs_version_positive")),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            ondelete="CASCADE",
            name="fk_workflow_runs_chapter_id_chapters",
        ),
        sa.ForeignKeyConstraint(
            ["work_id"], ["works.id"], ondelete="CASCADE", name="fk_workflow_runs_work_id_works"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_runs"),
        sa.UniqueConstraint("work_id", "idempotency_key", name="uq_workflow_runs_work_id"),
    )
    op.create_table(
        "workflow_steps",
        sa.Column("id", UUID, nullable=False),
        sa.Column("workflow_run_id", UUID, nullable=False),
        sa.Column("step_key", sa.String(length=80), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("output_artifact_id", UUID, nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_json", JSONB, nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "attempt_count >= 0", name=op.f("ck_workflow_steps_attempt_count_nonnegative")
        ),
        sa.CheckConstraint("ordinal >= 1", name=op.f("ck_workflow_steps_ordinal_positive")),
        sa.ForeignKeyConstraint(
            ["output_artifact_id"],
            ["artifacts.id"],
            ondelete="SET NULL",
            name="fk_workflow_steps_output_artifact_id_artifacts",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            ondelete="CASCADE",
            name="fk_workflow_steps_workflow_run_id_workflow_runs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_steps"),
        sa.UniqueConstraint(
            "workflow_run_id", "step_key", name="uq_workflow_steps_workflow_run_id"
        ),
    )
    op.create_table(
        "artifact_dependencies",
        sa.Column("input_artifact_id", UUID, nullable=False),
        sa.Column("output_artifact_id", UUID, nullable=False),
        sa.Column("workflow_step_id", UUID, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["input_artifact_id"],
            ["artifacts.id"],
            ondelete="CASCADE",
            name="fk_artifact_dependencies_input_artifact_id_artifacts",
        ),
        sa.ForeignKeyConstraint(
            ["output_artifact_id"],
            ["artifacts.id"],
            ondelete="CASCADE",
            name="fk_artifact_dependencies_output_artifact_id_artifacts",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_step_id"],
            ["workflow_steps.id"],
            ondelete="CASCADE",
            name="fk_artifact_dependencies_workflow_step_id_workflow_steps",
        ),
        sa.PrimaryKeyConstraint(
            "input_artifact_id", "output_artifact_id", name="pk_artifact_dependencies"
        ),
    )
    op.create_table(
        "context_snapshots",
        sa.Column("id", UUID, nullable=False),
        sa.Column("work_id", UUID, nullable=False),
        sa.Column("baseline_commit_sequence", sa.BigInteger(), nullable=False),
        sa.Column("prompt_key", sa.String(length=80), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("prompt_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("exact_system_text", sa.Text(), nullable=False),
        sa.Column("exact_user_text", sa.Text(), nullable=False),
        sa.Column("source_manifest", JSONB, nullable=False),
        sa.Column("budget_report", JSONB, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["work_id"], ["works.id"], ondelete="CASCADE", name="fk_context_snapshots_work_id_works"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_context_snapshots"),
        sa.UniqueConstraint("work_id", "content_hash", name="uq_context_snapshots_work_id"),
    )
    op.create_table(
        "generation_runs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("workflow_step_id", UUID, nullable=False),
        sa.Column("context_snapshot_id", UUID, nullable=False),
        sa.Column("prompt_key", sa.String(length=80), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("prompt_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model_snapshot", sa.String(length=160), nullable=False),
        sa.Column("parameters", JSONB, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("finish_reason", sa.String(length=80), nullable=True),
        sa.Column("usage_json", JSONB, nullable=True),
        sa.Column("output_artifact_id", UUID, nullable=True),
        sa.Column("raw_response_uri", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("attempt >= 1", name=op.f("ck_generation_runs_attempt_positive")),
        sa.ForeignKeyConstraint(
            ["context_snapshot_id"],
            ["context_snapshots.id"],
            ondelete="RESTRICT",
            name="fk_generation_runs_context_snapshot_id_context_snapshots",
        ),
        sa.ForeignKeyConstraint(
            ["output_artifact_id"],
            ["artifacts.id"],
            ondelete="SET NULL",
            name="fk_generation_runs_output_artifact_id_artifacts",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_step_id"],
            ["workflow_steps.id"],
            ondelete="CASCADE",
            name="fk_generation_runs_workflow_step_id_workflow_steps",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_generation_runs"),
    )
    op.create_table(
        "chapter_revisions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("chapter_id", UUID, nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("prose_artifact_id", UUID, nullable=False),
        sa.Column("workflow_run_id", UUID, nullable=False),
        sa.Column("canonical_commit_sequence", sa.BigInteger(), nullable=True),
        sa.Column("is_canonical", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "revision_number >= 1",
            name=op.f("ck_chapter_revisions_revision_number_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["chapters.id"],
            ondelete="CASCADE",
            name="fk_chapter_revisions_chapter_id_chapters",
        ),
        sa.ForeignKeyConstraint(
            ["prose_artifact_id"],
            ["artifacts.id"],
            ondelete="RESTRICT",
            name="fk_chapter_revisions_prose_artifact_id_artifacts",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            ondelete="RESTRICT",
            name="fk_chapter_revisions_workflow_run_id_workflow_runs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chapter_revisions"),
        sa.UniqueConstraint(
            "chapter_id", "revision_number", name="uq_chapter_revisions_chapter_id"
        ),
    )
    op.create_index(
        "uq_chapter_revisions_one_canonical",
        "chapter_revisions",
        ["chapter_id"],
        unique=True,
        postgresql_where=sa.text("is_canonical"),
    )
    op.create_table(
        "change_sets",
        sa.Column("id", UUID, nullable=False),
        sa.Column("workflow_run_id", UUID, nullable=False),
        sa.Column("proposal_artifact_id", UUID, nullable=False),
        sa.Column("validation_artifact_id", UUID, nullable=True),
        sa.Column("baseline_commit_sequence", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("proposal_hash", sa.String(length=64), nullable=False),
        sa.Column("validated_proposal_hash", sa.String(length=64), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "baseline_commit_sequence >= 0", name=op.f("ck_change_sets_baseline_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["proposal_artifact_id"],
            ["artifacts.id"],
            ondelete="RESTRICT",
            name="fk_change_sets_proposal_artifact_id_artifacts",
        ),
        sa.ForeignKeyConstraint(
            ["validation_artifact_id"],
            ["artifacts.id"],
            ondelete="RESTRICT",
            name="fk_change_sets_validation_artifact_id_artifacts",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            ondelete="CASCADE",
            name="fk_change_sets_workflow_run_id_workflow_runs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_change_sets"),
    )
    op.create_table(
        "story_events",
        sa.Column("id", UUID, nullable=False),
        sa.Column("work_id", UUID, nullable=False),
        sa.Column("chapter_revision_id", UUID, nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("projector_version", sa.Integer(), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("evidence", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "projector_version >= 1", name=op.f("ck_story_events_projector_version_positive")
        ),
        sa.CheckConstraint("sequence >= 1", name=op.f("ck_story_events_sequence_positive")),
        sa.ForeignKeyConstraint(
            ["chapter_revision_id"],
            ["chapter_revisions.id"],
            ondelete="RESTRICT",
            name="fk_story_events_chapter_revision_id_chapter_revisions",
        ),
        sa.ForeignKeyConstraint(
            ["work_id"], ["works.id"], ondelete="CASCADE", name="fk_story_events_work_id_works"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_story_events"),
        sa.UniqueConstraint("work_id", "sequence", name="uq_story_events_work_id"),
    )
    op.create_table(
        "item_ownership_projection",
        sa.Column("work_id", UUID, nullable=False),
        sa.Column("item_id", UUID, nullable=False),
        sa.Column("owner_entity_id", UUID, nullable=False),
        sa.Column("source_event_id", UUID, nullable=False),
        sa.Column("source_sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "source_sequence >= 1",
            name=op.f("ck_item_ownership_projection_source_sequence_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["source_event_id"],
            ["story_events.id"],
            ondelete="RESTRICT",
            name="fk_item_ownership_projection_source_event_id_story_events",
        ),
        sa.ForeignKeyConstraint(
            ["work_id"],
            ["works.id"],
            ondelete="CASCADE",
            name="fk_item_ownership_projection_work_id_works",
        ),
        sa.PrimaryKeyConstraint("work_id", "item_id", name="pk_item_ownership_projection"),
    )
    op.create_table(
        "semantic_memories",
        sa.Column("id", UUID, nullable=False),
        sa.Column("work_id", UUID, nullable=False),
        sa.Column("source_artifact_id", UUID, nullable=False),
        sa.Column("namespace", sa.String(length=80), nullable=False),
        sa.Column("embedding_model", sa.String(length=160), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column("visible_from_sequence", sa.BigInteger(), nullable=False),
        sa.Column("visible_until_sequence", sa.BigInteger(), nullable=True),
        sa.Column("must_not_reveal_before_chapter", sa.Integer(), nullable=True),
        sa.Column("metadata_json", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "embedding_dimensions > 0",
            name=op.f("ck_semantic_memories_embedding_dimensions_positive"),
        ),
        sa.CheckConstraint(
            "visible_from_sequence >= 0",
            name=op.f("ck_semantic_memories_visible_sequence_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"],
            ["artifacts.id"],
            ondelete="CASCADE",
            name="fk_semantic_memories_source_artifact_id_artifacts",
        ),
        sa.ForeignKeyConstraint(
            ["work_id"], ["works.id"], ondelete="CASCADE", name="fk_semantic_memories_work_id_works"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_semantic_memories"),
        sa.UniqueConstraint(
            "source_artifact_id",
            "namespace",
            "embedding_model",
            "embedding_hash",
            name="uq_semantic_memories_source_artifact_id",
        ),
    )
    op.create_index("ix_semantic_memories_work_id", "semantic_memories", ["work_id"])
    op.create_table(
        "outbox_events",
        sa.Column("id", UUID, nullable=False),
        sa.Column("work_id", UUID, nullable=False),
        sa.Column("topic", sa.String(length=120), nullable=False),
        sa.Column("aggregate_id", UUID, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["work_id"], ["works.id"], ondelete="CASCADE", name="fk_outbox_events_work_id_works"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
    )
    op.create_index("ix_outbox_events_processed_at", "outbox_events", ["processed_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_events_processed_at", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_semantic_memories_work_id", table_name="semantic_memories")
    op.drop_table("semantic_memories")
    op.drop_table("item_ownership_projection")
    op.drop_table("story_events")
    op.drop_table("change_sets")
    op.drop_index("uq_chapter_revisions_one_canonical", table_name="chapter_revisions")
    op.drop_table("chapter_revisions")
    op.drop_table("generation_runs")
    op.drop_table("context_snapshots")
    op.drop_table("artifact_dependencies")
    op.drop_table("workflow_steps")
    op.drop_table("workflow_runs")
    op.drop_table("artifacts")
    op.drop_table("chapters")
    op.drop_table("works")
