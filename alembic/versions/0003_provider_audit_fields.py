"""Record normalized provider request and response metadata.

Revision ID: 0003_provider_audit_fields
Revises: 0002_event_type_registry
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_provider_audit_fields"
down_revision: str | None = "0002_event_type_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generation_runs",
        sa.Column(
            "endpoint",
            sa.String(length=300),
            nullable=False,
            server_default="legacy-unknown",
        ),
    )
    op.alter_column("generation_runs", "endpoint", server_default=None)
    op.add_column(
        "generation_runs", sa.Column("response_status", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "generation_runs", sa.Column("provider_request_id", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "generation_runs", sa.Column("provider_response_id", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "generation_runs",
        sa.Column("response_item_types", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "generation_runs", sa.Column("system_fingerprint", sa.String(length=200), nullable=True)
    )
    op.add_column("generation_runs", sa.Column("latency_ms", sa.Integer(), nullable=True))
    op.add_column(
        "generation_runs",
        sa.Column("retry_of_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "generation_runs",
        sa.Column("error_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_generation_runs_latency_nonnegative"),
        "generation_runs",
        "latency_ms IS NULL OR latency_ms >= 0",
    )
    op.create_foreign_key(
        "fk_generation_runs_retry_of_id_generation_runs",
        "generation_runs",
        "generation_runs",
        ["retry_of_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_generation_runs_retry_of_id_generation_runs",
        "generation_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("ck_generation_runs_latency_nonnegative"),
        "generation_runs",
        type_="check",
    )
    op.drop_column("generation_runs", "error_json")
    op.drop_column("generation_runs", "retry_of_id")
    op.drop_column("generation_runs", "latency_ms")
    op.drop_column("generation_runs", "system_fingerprint")
    op.drop_column("generation_runs", "response_item_types")
    op.drop_column("generation_runs", "provider_response_id")
    op.drop_column("generation_runs", "provider_request_id")
    op.drop_column("generation_runs", "response_status")
    op.drop_column("generation_runs", "endpoint")
