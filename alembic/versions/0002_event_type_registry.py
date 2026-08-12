"""Register event schemas and projector versions.

Revision ID: 0002_event_type_registry
Revises: 0001_core_foundation
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_event_type_registry"
down_revision: str | None = "0001_core_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "event_type_definitions",
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload_schema", JSONB, nullable=False),
        sa.Column("projector_name", sa.String(length=160), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_event_type_definitions_version_positive")),
        sa.PrimaryKeyConstraint("event_type", "version", name="pk_event_type_definitions"),
    )
    op.create_foreign_key(
        "fk_story_events_event_type_event_type_definitions",
        "story_events",
        "event_type_definitions",
        ["event_type", "projector_version"],
        ["event_type", "version"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_story_events_event_type_event_type_definitions",
        "story_events",
        type_="foreignkey",
    )
    op.drop_table("event_type_definitions")
