import hashlib
import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

CHUNK_SIZE = 1024 * 1024


class CaptureStorageError(RuntimeError):
    pass


class CaptureTooLarge(ValueError):
    pass


class InvalidCapture(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StagedCapture:
    path: Path
    size_bytes: int
    sha256: str
    width: int
    height: int


class LocalCaptureStorage:
    def __init__(
        self,
        root: Path,
        *,
        max_upload_bytes: int,
        min_width: int,
        min_height: int,
        max_pixels: int,
    ) -> None:
        self.root = root
        self.max_upload_bytes = max_upload_bytes
        self.min_width = min_width
        self.min_height = min_height
        self.max_pixels = max_pixels

    def stage_jpeg(self, source: BinaryIO, *, content_type: str | None) -> StagedCapture:
        if content_type != "image/jpeg":
            raise InvalidCapture("Only image/jpeg uploads are accepted.")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            temporary_path = self.root / f".{uuid4().hex}.upload"
            digest = hashlib.sha256()
            size_bytes = 0
            with temporary_path.open("xb") as destination:
                while chunk := source.read(CHUNK_SIZE):
                    size_bytes += len(chunk)
                    if size_bytes > self.max_upload_bytes:
                        raise CaptureTooLarge(
                            f"Capture exceeds the {self.max_upload_bytes} byte limit."
                        )
                    digest.update(chunk)
                    destination.write(chunk)
            if size_bytes == 0:
                raise InvalidCapture("Capture file is empty.")
            width, height = self._verify_jpeg(temporary_path)
            return StagedCapture(
                path=temporary_path,
                size_bytes=size_bytes,
                sha256=digest.hexdigest(),
                width=width,
                height=height,
            )
        except (CaptureTooLarge, InvalidCapture):
            if "temporary_path" in locals():
                temporary_path.unlink(missing_ok=True)
            raise
        except OSError as error:
            if "temporary_path" in locals():
                temporary_path.unlink(missing_ok=True)
            raise CaptureStorageError("Could not stage capture in private storage.") from error

    def finalize(self, staged: StagedCapture, *, capture_id: str) -> str:
        relative_path = f"{capture_id}.jpg"
        destination = self.root / relative_path
        try:
            os.replace(staged.path, destination)
        except OSError as error:
            raise CaptureStorageError("Could not finalize capture in private storage.") from error
        return relative_path

    def discard_staged(self, staged: StagedCapture | None) -> None:
        if staged is not None:
            staged.path.unlink(missing_ok=True)

    def remove(self, relative_path: str | None) -> None:
        if relative_path is None:
            return
        candidate = (self.root / relative_path).resolve()
        root = self.root.resolve()
        if candidate.parent != root:
            raise CaptureStorageError("Refusing to remove a path outside private storage.")
        try:
            candidate.unlink(missing_ok=True)
        except OSError as error:
            raise CaptureStorageError("Could not remove capture from private storage.") from error

    def _verify_jpeg(self, path: Path) -> tuple[int, int]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    if image.format != "JPEG":
                        raise InvalidCapture("Uploaded content is not a valid JPEG image.")
                    width, height = image.size
                    if width * height > self.max_pixels:
                        raise InvalidCapture("Capture pixel count exceeds the configured limit.")
                    if width < self.min_width or height < self.min_height:
                        raise InvalidCapture(
                            f"Capture must be at least {self.min_width}x{self.min_height}."
                        )
                    image.verify()
        except InvalidCapture:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise InvalidCapture("Capture dimensions are unsafe.") from error
        except (OSError, UnidentifiedImageError) as error:
            raise InvalidCapture("Uploaded content is not a valid JPEG image.") from error
        return width, height
