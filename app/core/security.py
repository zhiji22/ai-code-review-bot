"""
HMAC-SHA256 webhook signature verification + secret encryption.

Per DESIGN.md §3 Webhook Handler + §15 Security.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from cryptography.fernet import Fernet
from fastapi import HTTPException, Request, status


def verify_github_signature(payload_body: bytes, signature_header: str, secret: str) -> None:
    """Verify the X-Hub-Signature-256 header against the payload.

    Uses constant-time comparison to prevent timing attacks.

    Args:
        payload_body: Raw request body bytes.
        signature_header: Value of X-Hub-Signature-256 header.
        secret: The webhook secret configured in the GitHub App.

    Raises:
        HTTPException 403 if signature is invalid or missing.
    """
    if not signature_header:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing X-Hub-Signature-256 header",
        )

    if not signature_header.startswith("sha256="):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature format",
        )

    expected = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    provided = signature_header.removeprefix("sha256=")

    if not hmac.compare_digest(expected, provided):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )


async def verify_webhook(request: Request, secret: str) -> bytes:
    """Verify and return the raw webhook body.

    Args:
        request: FastAPI Request object.
        secret: Webhook secret.

    Returns:
        Raw body bytes.

    Raises:
        HTTPException on invalid signature.
    """
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    verify_github_signature(body, signature, secret)
    return body


def prevent_replay(timestamp_header: str, max_age_seconds: int = 300) -> None:
    """Prevent replay attacks by checking X-GitHub-Delivery timestamp.

    Args:
        timestamp_header: Value of X-GitHub-Hook-Installation-Target-ID or similar.
        max_age_seconds: Maximum allowed age in seconds.

    Raises:
        HTTPException if timestamp is too old.
    """
    try:
        ts = int(timestamp_header)
    except (ValueError, TypeError):
        return  # Skip if no valid timestamp

    now = int(time.time())
    if now - ts > max_age_seconds:
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail="Webhook timestamp too old — possible replay attack",
        )


# ------------------------------------------------------------------ Secret Encryption
# Per §15: webhook_secret stored as BYTEA, encrypted at rest.


def _derive_key(secret: str) -> bytes:
    """Derive a Fernet-compatible key from a passphrase."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(plaintext: str, passphrase: str) -> bytes:
    """Encrypt a secret using Fernet symmetric encryption."""
    key = _derive_key(passphrase)
    f = Fernet(key)
    return f.encrypt(plaintext.encode("utf-8"))


def decrypt_secret(ciphertext: bytes, passphrase: str) -> str:
    """Decrypt a Fernet-encrypted secret."""
    key = _derive_key(passphrase)
    f = Fernet(key)
    return f.decrypt(ciphertext).decode("utf-8")
