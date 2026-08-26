from uuid import uuid4

import pytest

from app.services.device_keys import (
    InvalidDeviceApiKey,
    device_id_from_api_key,
    generate_device_api_key,
    hash_device_api_key,
    verify_device_api_key,
)


def test_generated_key_can_be_verified_and_identifies_device() -> None:
    device_id = uuid4()

    raw_key, stored_hash = generate_device_api_key(device_id)

    assert raw_key not in stored_hash
    assert device_id_from_api_key(raw_key) == device_id
    assert verify_device_api_key(raw_key, stored_hash) is True
    assert verify_device_api_key(f"{raw_key}wrong", stored_hash) is False


def test_hash_uses_unique_salt() -> None:
    raw_key = f"ha_dev_{uuid4().hex}_secret"

    first = hash_device_api_key(raw_key)
    second = hash_device_api_key(raw_key)

    assert first != second
    assert verify_device_api_key(raw_key, first) is True
    assert verify_device_api_key(raw_key, second) is True


@pytest.mark.parametrize(
    "raw_key",
    ["", "wrong", "ha_dev_not-a-uuid_secret", f"ha_other_{uuid4().hex}_secret"],
)
def test_malformed_device_key_is_rejected(raw_key: str) -> None:
    with pytest.raises(InvalidDeviceApiKey):
        device_id_from_api_key(raw_key)


@pytest.mark.parametrize(
    "stored_hash",
    ["", "wrong", "unknown$1$c2FsdA$ZGlnZXN0", "pbkdf2_sha256$bad$c2FsdA$ZGlnZXN0"],
)
def test_malformed_stored_hash_does_not_authenticate(stored_hash: str) -> None:
    assert verify_device_api_key("some-key", stored_hash) is False
