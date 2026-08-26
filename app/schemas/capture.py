from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CaptureResponse(BaseModel):
    id: UUID
    run_id: UUID
    device_id: UUID
    captured_at: datetime
    content_type: str
    size_bytes: int
    sha256: str
    width: int
    height: int
    quality_status: str
    expires_at: datetime
    replayed: bool = False
