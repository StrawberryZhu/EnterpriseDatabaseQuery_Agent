from __future__ import annotations

from cryptography.fernet import Fernet
import pytest

from app.config import Settings
from app.credentials import (
    CredentialCipher,
    CredentialDecryptionError,
    CredentialKeyNotConfiguredError,
    sanitize_secret_text,
)


def test_password_is_authenticated_encrypted_and_round_trips():
    key = Fernet.generate_key().decode()
    cipher = CredentialCipher({7: key}, active_key_version=7)

    first = cipher.encrypt("sensitive-password")
    second = cipher.encrypt("sensitive-password")

    assert first.key_version == 7
    assert first.ciphertext != "sensitive-password"
    assert first.ciphertext != second.ciphertext
    assert cipher.decrypt(first.ciphertext, first.key_version) == "sensitive-password"


def test_missing_key_blocks_external_credential_encryption():
    cipher = CredentialCipher({}, active_key_version=1)

    with pytest.raises(CredentialKeyNotConfiguredError, match="未配置数据源加密主密钥"):
        cipher.encrypt("secret")


def test_master_key_is_hidden_in_settings_representation():
    key = Fernet.generate_key().decode()
    settings = Settings(data_source_encryption_key=key)

    assert key not in repr(settings)


def test_tampered_ciphertext_raises_sanitized_error():
    key = Fernet.generate_key().decode()
    cipher = CredentialCipher({1: key}, active_key_version=1)
    encrypted = cipher.encrypt("must-not-leak")
    replacement = "A" if encrypted.ciphertext[20] != "A" else "B"
    tampered = encrypted.ciphertext[:20] + replacement + encrypted.ciphertext[21:]

    with pytest.raises(CredentialDecryptionError) as error:
        cipher.decrypt(tampered, encrypted.key_version)

    assert "must-not-leak" not in str(error.value)
    assert key not in str(error.value)


def test_unknown_key_version_is_not_silently_fallbacked():
    key = Fernet.generate_key().decode()
    cipher = CredentialCipher({1: key}, active_key_version=1)
    encrypted = cipher.encrypt("secret")

    with pytest.raises(CredentialDecryptionError, match="无法解密数据源凭据"):
        cipher.decrypt(encrypted.ciphertext, key_version=2)


@pytest.mark.parametrize(
    "raw",
    [
        "postgresql://alice:plain-secret@db.example.com:5432/app",
        "password=plain-secret host=db.example.com",
        "PASSWORD: plain-secret; user=alice",
    ],
)
def test_error_sanitizer_removes_passwords(raw: str):
    sanitized = sanitize_secret_text(raw)

    assert "plain-secret" not in sanitized
    assert "***" in sanitized
