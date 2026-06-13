"""Unit tests for security utilities (HMAC, idempotency)."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import time

import pytest
from cryptography.fernet import InvalidToken
from fastapi import HTTPException


class TestHMACVerification:
    """Tests for webhook HMAC-SHA256 signature verification."""

    def test_valid_signature(self) -> None:
        from app.core.security import verify_github_signature

        secret = "my_webhook_secret"
        payload = b'{"action":"opened"}'
        signature = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

        # Should not raise — returns None on success
        result = verify_github_signature(payload, signature, secret)
        assert result is None

    def test_invalid_signature(self) -> None:
        from app.core.security import verify_github_signature

        secret = "my_webhook_secret"
        payload = b'{"action":"opened"}'
        signature = "sha256=invalid_signature_hex"

        with pytest.raises(HTTPException) as exc_info:
            verify_github_signature(payload, signature, secret)
        assert exc_info.value.status_code == 403

    def test_missing_sha256_prefix(self) -> None:
        from app.core.security import verify_github_signature

        secret = "secret"
        payload = b"payload"
        signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

        with pytest.raises(HTTPException) as exc_info:
            verify_github_signature(payload, signature, secret)
        assert exc_info.value.status_code == 403

    def test_empty_signature(self) -> None:
        from app.core.security import verify_github_signature

        with pytest.raises(HTTPException) as exc_info:
            verify_github_signature(b"payload", "", "secret")
        assert exc_info.value.status_code == 403

    def test_constant_time_comparison(self) -> None:
        """Verify that timing doesn't leak signature info."""
        from app.core.security import verify_github_signature

        secret = "secret"
        payload = b'{"test":true}'
        valid_sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

        start = time.monotonic()
        verify_github_signature(payload, valid_sig, secret)
        valid_time = time.monotonic() - start

        start = time.monotonic()
        with contextlib.suppress(HTTPException):
            verify_github_signature(payload, "sha256=" + "a" * 64, secret)
        invalid_time = time.monotonic() - start

        # Times should be roughly similar (within a generous margin)
        # This is a heuristic test - constant-time comparison should
        # make timing attacks impractical
        assert abs(valid_time - invalid_time) < 0.01


class TestEncryptDecrypt:
    """Tests for Fernet-based secret encryption."""

    def test_roundtrip(self) -> None:
        from app.core.security import decrypt_secret, encrypt_secret

        passphrase = "my_app_secret_key"
        plaintext = "super_secret_webhook_value"

        ciphertext = encrypt_secret(plaintext, passphrase)
        assert isinstance(ciphertext, bytes)
        assert ciphertext != plaintext.encode()

        decrypted = decrypt_secret(ciphertext, passphrase)
        assert decrypted == plaintext

    def test_different_passphrase_fails(self) -> None:
        from app.core.security import decrypt_secret, encrypt_secret

        ciphertext = encrypt_secret("secret_data", "passphrase1")
        with pytest.raises(InvalidToken):
            decrypt_secret(ciphertext, "passphrase2")

    def test_empty_string(self) -> None:
        from app.core.security import decrypt_secret, encrypt_secret

        ciphertext = encrypt_secret("", "key")
        assert decrypt_secret(ciphertext, "key") == ""


class TestIdempotencyKey:
    """Tests for idempotency key generation."""

    def test_key_format(self) -> None:
        from app.core.idempotency import build_webhook_idempotency_key

        key = build_webhook_idempotency_key(
            repo_full_name="owner/repo",
            pr_number=42,
            commit_sha="abc123",
        )
        assert "owner/repo" in key
        assert "42" in key
        assert "abc123" in key
        assert key.startswith("webhook:")

    def test_different_inputs_different_keys(self) -> None:
        from app.core.idempotency import build_webhook_idempotency_key

        key1 = build_webhook_idempotency_key("a/b", 1, "sha1")
        key2 = build_webhook_idempotency_key("a/b", 2, "sha1")
        key3 = build_webhook_idempotency_key("a/b", 1, "sha2")

        assert key1 != key2
        assert key1 != key3
        assert key2 != key3
