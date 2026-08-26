"""Add private capture metadata.

Revision ID: 20260826_0005
Revises: 20260826_0004
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0005"
down_revision: str | None = "20260826_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "captures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_type", sa.String(length=50), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("quality_status", sa.String(length=32), nullable=False),
        sa.Column("file_path", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["mode_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_path"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index(
        "ix_captures_device_captured",
        "captures",
        ["device_id", "captured_at"],
    )
    op.create_index("ix_captures_expires_at", "captures", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_captures_expires_at", table_name="captures")
    op.drop_index("ix_captures_device_captured", table_name="captures")
    op.drop_table("captures")
