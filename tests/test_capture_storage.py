from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.services.capture_storage import (
    CaptureStorageError,
    CaptureTooLarge,
    InvalidCapture,
    LocalCaptureStorage,
)


def jpeg_bytes(width: int = 128, height: int = 72) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height), color=(40, 80, 120)).save(
        output,
        format="JPEG",
        quality=90,
    )
    return output.getvalue()


def storage(tmp_path: Path, **overrides: int) -> LocalCaptureStorage:
    values = {
        "max_upload_bytes": 1024 * 1024,
        "min_width": 64,
        "min_height": 64,
        "max_pixels": 1_000_000,
    }
    values.update(overrides)
    return LocalCaptureStorage(tmp_path, **values)


def test_valid_jpeg_is_staged_finalized_and_removed(tmp_path: Path) -> None:
    capture_storage = storage(tmp_path)
    content = jpeg_bytes()

    staged = capture_storage.stage_jpeg(BytesIO(content), content_type="image/jpeg")
    relative_path = capture_storage.finalize(staged, capture_id="capture-id")

    final_path = tmp_path / relative_path
    assert staged.size_bytes == len(content)
    assert len(staged.sha256) == 64
    assert (staged.width, staged.height) == (128, 72)
    assert relative_path == "capture-id.jpg"
    assert final_path.read_bytes() == content
    capture_storage.remove(relative_path)
    assert not final_path.exists()


@pytest.mark.parametrize("content_type", [None, "image/png", "application/octet-stream"])
def test_non_jpeg_content_type_is_rejected(tmp_path: Path, content_type: str | None) -> None:
    with pytest.raises(InvalidCapture, match="image/jpeg"):
        storage(tmp_path).stage_jpeg(BytesIO(jpeg_bytes()), content_type=content_type)


@pytest.mark.parametrize("content", [b"", b"not-an-image"])
def test_empty_or_invalid_image_is_rejected_without_temp_file(
    tmp_path: Path,
    content: bytes,
) -> None:
    with pytest.raises(InvalidCapture):
        storage(tmp_path).stage_jpeg(BytesIO(content), content_type="image/jpeg")

    assert list(tmp_path.glob("*.upload")) == []


def test_upload_size_limit_is_enforced(tmp_path: Path) -> None:
    capture_storage = storage(tmp_path, max_upload_bytes=10)

    with pytest.raises(CaptureTooLarge, match="10 byte"):
        capture_storage.stage_jpeg(BytesIO(b"x" * 11), content_type="image/jpeg")

    assert list(tmp_path.glob("*.upload")) == []


def test_minimum_dimensions_are_enforced(tmp_path: Path) -> None:
    with pytest.raises(InvalidCapture, match="at least 64x64"):
        storage(tmp_path).stage_jpeg(BytesIO(jpeg_bytes(32, 32)), content_type="image/jpeg")


def test_maximum_pixel_count_is_enforced(tmp_path: Path) -> None:
    capture_storage = storage(
        tmp_path,
        min_width=1,
        min_height=1,
        max_pixels=1_000,
    )

    with pytest.raises(InvalidCapture, match="pixel count"):
        capture_storage.stage_jpeg(
            BytesIO(jpeg_bytes(40, 40)),
            content_type="image/jpeg",
        )


def test_discard_staged_removes_temporary_file(tmp_path: Path) -> None:
    capture_storage = storage(tmp_path)
    staged = capture_storage.stage_jpeg(BytesIO(jpeg_bytes()), content_type="image/jpeg")

    capture_storage.discard_staged(staged)
    capture_storage.discard_staged(None)

    assert not staged.path.exists()


def test_remove_refuses_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(CaptureStorageError, match="outside"):
        storage(tmp_path).remove("../outside.jpg")
