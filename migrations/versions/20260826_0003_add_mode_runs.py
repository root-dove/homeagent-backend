"""Add persistent mode execution queue.

Revision ID: 20260826_0003
Revises: 20260826_0002
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0003"
down_revision: str | None = "20260826_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mode_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mode_id", sa.Uuid(), nullable=False),
        sa.Column("mode_state_version", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["mode_id"], ["modes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mode_id",
            "mode_state_version",
            name="uq_mode_runs_mode_state_version",
        ),
    )
    op.create_index(
        "ix_mode_runs_mode_created",
        "mode_runs",
        ["mode_id", "created_at"],
    )
    op.create_index(
        "ix_mode_runs_status_created",
        "mode_runs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_mode_runs_status_created", table_name="mode_runs")
    op.drop_index("ix_mode_runs_mode_created", table_name="mode_runs")
    op.drop_table("mode_runs")
