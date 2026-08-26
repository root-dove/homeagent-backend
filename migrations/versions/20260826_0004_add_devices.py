"""Add camera devices and mode-run leases.

Revision ID: 20260826_0004
Revises: 20260826_0003
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0004"
down_revision: str | None = "20260826_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("room_name", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("api_key_hash", sa.String(length=255), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_agent_version", sa.String(length=50), nullable=True),
        sa.Column("last_camera_status", sa.String(length=32), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_key"),
    )
    op.add_column("mode_runs", sa.Column("assigned_device_id", sa.Uuid(), nullable=True))
    op.add_column(
        "mode_runs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "mode_runs",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_foreign_key(
        "fk_mode_runs_assigned_device_id",
        "mode_runs",
        "devices",
        ["assigned_device_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_mode_runs_claim",
        "mode_runs",
        ["status", "lease_expires_at", "created_at"],
    )
    op.alter_column("mode_runs", "attempt_count", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_mode_runs_claim", table_name="mode_runs")
    op.drop_constraint(
        "fk_mode_runs_assigned_device_id",
        "mode_runs",
        type_="foreignkey",
    )
    op.drop_column("mode_runs", "attempt_count")
    op.drop_column("mode_runs", "lease_expires_at")
    op.drop_column("mode_runs", "assigned_device_id")
    op.drop_table("devices")
