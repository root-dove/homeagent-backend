import base64
import hashlib
import secrets
from uuid import UUID

API_KEY_PREFIX = "ha_dev"
PBKDF2_ITERATIONS = 310_000


class InvalidDeviceApiKey(ValueError):
    pass


def generate_device_api_key(device_id: UUID) -> tuple[str, str]:
    secret = secrets.token_urlsafe(32)
    raw_key = f"{API_KEY_PREFIX}_{device_id.hex}_{secret}"
    return raw_key, hash_device_api_key(raw_key)


def hash_device_api_key(raw_key: str, *, salt: bytes | None = None) -> str:
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        raw_key.encode("utf-8"),
        actual_salt,
        PBKDF2_ITERATIONS,
    )
    return "$".join(
        [
            "pbkdf2_sha256",
            str(PBKDF2_ITERATIONS),
            _encode(actual_salt),
            _encode(digest),
        ]
    )


def verify_device_api_key(raw_key: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, expected_text = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = _decode(salt_text)
        expected = _decode(expected_text)
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        raw_key.encode("utf-8"),
        salt,
        iterations,
    )
    return secrets.compare_digest(actual, expected)


def device_id_from_api_key(raw_key: str) -> UUID:
    parts = raw_key.split("_", 3)
    if len(parts) != 4 or parts[0] != "ha" or parts[1] != "dev" or not parts[3]:
        raise InvalidDeviceApiKey("Invalid device API key.")
    try:
        return UUID(hex=parts[2])
    except ValueError as error:
        raise InvalidDeviceApiKey("Invalid device API key.") from error


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
