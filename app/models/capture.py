from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Capture(Base):
    __tablename__ = "captures"
    __table_args__ = (
        Index("ix_captures_device_captured", "device_id", "captured_at"),
        Index("ix_captures_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mode_runs.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    device_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("devices.id", ondelete="RESTRICT"),
        nullable=False,
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    quality_status: Mapped[str] = mapped_column(String(32), nullable=False)
    file_path: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
