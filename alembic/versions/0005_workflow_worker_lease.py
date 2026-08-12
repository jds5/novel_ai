"""Add recoverable workflow worker leases.

Revision ID: 0005_workflow_worker_lease
Revises: 0004_writing_workspace
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_workflow_worker_lease"
down_revision: str | None = "0004_writing_workspace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("worker_id", sa.String(length=80), nullable=True))
    op.add_column(
        "workflow_runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_workflow_runs_recovery",
        "workflow_runs",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_recovery", table_name="workflow_runs")
    op.drop_column("workflow_runs", "lease_expires_at")
    op.drop_column("workflow_runs", "worker_id")
