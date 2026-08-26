from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Mode(Base):
    __tablename__ = "modes"
    __table_args__ = (
        CheckConstraint("state_version >= 0", name="ck_modes_state_version_non_negative"),
        Index("ix_modes_type_enabled", "mode_type", "enabled"),
        Index("ix_modes_next_run_at", "next_run_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    instance_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    mode_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    runtime_state: Mapped[str] = mapped_column(String(32), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    state_history: Mapped[list[ModeStateHistory]] = relationship(
        back_populates="mode",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ModeStateHistory(Base):
    __tablename__ = "mode_state_history"
    __table_args__ = (Index("ix_mode_state_history_mode_created", "mode_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    mode_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("modes.id", ondelete="CASCADE"),
        nullable=False,
    )
    previous_state: Mapped[str | None] = mapped_column(String(32))
    current_state: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger: Mapped[str] = mapped_column(String(50), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    mode: Mapped[Mode] = relationship(back_populates="state_history")
