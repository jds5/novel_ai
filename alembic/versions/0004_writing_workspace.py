"""Add writing workspace metadata and immutable revision pointers.

Revision ID: 0004_writing_workspace
Revises: 0003_provider_audit_fields
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_writing_workspace"
down_revision: str | None = "0003_provider_audit_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("works", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "works",
        sa.Column(
            "settings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("works", "settings_json", server_default=None)

    op.add_column("chapters", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("chapters", sa.Column("generation_brief", sa.Text(), nullable=True))
    op.add_column(
        "chapters",
        sa.Column("target_char_count", sa.Integer(), nullable=False, server_default="2500"),
    )
    op.alter_column("chapters", "target_char_count", server_default=None)
    op.create_check_constraint(
        op.f("ck_chapters_target_char_count_minimum"),
        "chapters",
        "target_char_count >= 100",
    )

    op.add_column(
        "artifacts",
        sa.Column(
            "media_type", sa.String(length=100), nullable=False, server_default="application/json"
        ),
    )
    op.add_column(
        "artifacts",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="VALID"),
    )
    op.alter_column("artifacts", "media_type", server_default=None)
    op.alter_column("artifacts", "status", server_default=None)

    op.alter_column("chapter_revisions", "workflow_run_id", nullable=True)
    op.add_column(
        "chapter_revisions",
        sa.Column("parent_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "chapter_revisions",
        sa.Column("source", sa.String(length=32), nullable=False, server_default="MODEL"),
    )
    op.add_column(
        "chapter_revisions",
        sa.Column("char_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("chapter_revisions", "source", server_default=None)
    op.alter_column("chapter_revisions", "char_count", server_default=None)
    op.create_check_constraint(
        op.f("ck_chapter_revisions_char_count_nonnegative"),
        "chapter_revisions",
        "char_count >= 0",
    )
    op.create_foreign_key(
        "fk_chapter_revisions_parent_revision_id_chapter_revisions",
        "chapter_revisions",
        "chapter_revisions",
        ["parent_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "chapters",
        sa.Column("latest_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_chapters_latest_revision_id_chapter_revisions",
        "chapters",
        "chapter_revisions",
        ["latest_revision_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )
    op.create_index(
        "ix_chapter_revisions_chapter_created",
        "chapter_revisions",
        ["chapter_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_chapter_revisions_chapter_created", table_name="chapter_revisions")
    op.drop_constraint(
        "fk_chapters_latest_revision_id_chapter_revisions", "chapters", type_="foreignkey"
    )
    op.drop_column("chapters", "latest_revision_id")
    op.drop_constraint(
        "fk_chapter_revisions_parent_revision_id_chapter_revisions",
        "chapter_revisions",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("ck_chapter_revisions_char_count_nonnegative"),
        "chapter_revisions",
        type_="check",
    )
    op.drop_column("chapter_revisions", "char_count")
    op.drop_column("chapter_revisions", "source")
    op.drop_column("chapter_revisions", "parent_revision_id")
    op.alter_column("chapter_revisions", "workflow_run_id", nullable=False)
    op.drop_column("artifacts", "status")
    op.drop_column("artifacts", "media_type")
    op.drop_constraint(op.f("ck_chapters_target_char_count_minimum"), "chapters", type_="check")
    op.drop_column("chapters", "target_char_count")
    op.drop_column("chapters", "generation_brief")
    op.drop_column("chapters", "summary")
    op.drop_column("works", "settings_json")
    op.drop_column("works", "description")
