import hashlib
import hmac
import secrets
from typing import Optional


def hash_api_key(api_key: str) -> str:
    """Hash an API key using SHA-256 for secure DB persistence."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def verify_api_key(plain_api_key: str, hashed_key: str) -> bool:
    """Verify if a provided API key matches the stored hash."""
    candidate_hash = hash_api_key(plain_api_key)
    return hmac.compare_digest(candidate_hash, hashed_key)


def generate_api_key(prefix: str = "dte_") -> tuple[str, str]:
    """
    Generate a new API key and its hash.
    Returns: (raw_key, hashed_key)
    """
    raw_key = f"{prefix}{secrets.token_urlsafe(32)}"
    return raw_key, hash_api_key(raw_key)


def generate_webhook_secret() -> str:
    """Generate a high-entropy secret for HMAC webhook verification."""
    return f"whsec_{secrets.token_hex(24)}"


def verify_webhook_signature(
    payload_bytes: bytes,
    secret: str,
    signature: str,
) -> bool:
    """
    Verify HMAC SHA-256 signature for webhook payload.
    Supports signatures formatted as 'sha256=<hex>' or raw hex.
    """
    if not secret or not signature:
        return False

    target_sig = signature.replace("sha256=", "").strip()
    expected_mac = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_mac, target_sig)
