"""Create the initial migration baseline.

Revision ID: 20260820_0001
Revises:
Create Date: 2026-08-20
"""

from collections.abc import Sequence

revision: str = "20260820_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the baseline before domain tables are added."""


def downgrade() -> None:
    """Remove the baseline."""
