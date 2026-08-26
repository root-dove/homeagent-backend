"""Add mode instances and state history.

Revision ID: 20260826_0002
Revises: 20260820_0001
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0002"
down_revision: str | None = "20260820_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "modes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("instance_key", sa.String(length=100), nullable=False),
        sa.Column("mode_type", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("runtime_state", sa.String(length=32), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=False),
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
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_modes_state_version_non_negative",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instance_key"),
    )
    op.create_index("ix_modes_next_run_at", "modes", ["next_run_at"])
    op.create_index("ix_modes_type_enabled", "modes", ["mode_type", "enabled"])

    op.create_table(
        "mode_state_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mode_id", sa.Uuid(), nullable=False),
        sa.Column("previous_state", sa.String(length=32), nullable=True),
        sa.Column("current_state", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=50), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["mode_id"], ["modes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mode_state_history_mode_created",
        "mode_state_history",
        ["mode_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mode_state_history_mode_created",
        table_name="mode_state_history",
    )
    op.drop_table("mode_state_history")
    op.drop_index("ix_modes_type_enabled", table_name="modes")
    op.drop_index("ix_modes_next_run_at", table_name="modes")
    op.drop_table("modes")
