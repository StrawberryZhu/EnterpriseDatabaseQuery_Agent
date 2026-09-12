from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings, get_settings


class CredentialError(RuntimeError):
    """Base class for safe, user-facing credential failures."""


class CredentialKeyNotConfiguredError(CredentialError):
    pass


class CredentialDecryptionError(CredentialError):
    pass


@dataclass(frozen=True)
class EncryptedCredential:
    ciphertext: str
    key_version: int


class CredentialCipher:
    """Authenticated encryption for external data-source passwords."""

    def __init__(self, keys: dict[int, str], *, active_key_version: int) -> None:
        self._active_key_version = active_key_version
        self._ciphers: dict[int, Fernet] = {}
        for version, key in keys.items():
            try:
                self._ciphers[version] = Fernet(key.encode())
            except (TypeError, ValueError) as exc:
                raise CredentialKeyNotConfiguredError("数据源加密主密钥格式无效") from exc

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "CredentialCipher":
        settings = settings or get_settings()
        keys = {}
        encryption_key = settings.data_source_encryption_key.get_secret_value().strip()
        if encryption_key:
            keys[settings.data_source_encryption_key_version] = encryption_key
        return cls(keys, active_key_version=settings.data_source_encryption_key_version)

    def encrypt(self, password: str) -> EncryptedCredential:
        if not password:
            raise ValueError("数据源密码不能为空")
        cipher = self._ciphers.get(self._active_key_version)
        if cipher is None:
            raise CredentialKeyNotConfiguredError("未配置数据源加密主密钥")
        return EncryptedCredential(
            ciphertext=cipher.encrypt(password.encode()).decode(),
            key_version=self._active_key_version,
        )

    def decrypt(self, ciphertext: str, key_version: int) -> str:
        cipher = self._ciphers.get(key_version)
        if cipher is None:
            raise CredentialDecryptionError("无法解密数据源凭据")
        try:
            return cipher.decrypt(ciphertext.encode()).decode()
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise CredentialDecryptionError("无法解密数据源凭据") from exc


_PASSWORD_PATTERN = re.compile(
    r"(?i)(\b(?:password|passwd|pwd)\b\s*[:=]\s*)([^\s;,]+)"
)


def sanitize_secret_text(value: object) -> str:
    """Remove passwords from connection URLs and common error-message forms."""
    text = str(value)
    try:
        parsed = urlsplit(text)
        if parsed.scheme and parsed.hostname and parsed.password is not None:
            username = parsed.username or ""
            host = parsed.hostname
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            credentials = f"{username}:***@" if username else "***@"
            port = f":{parsed.port}" if parsed.port is not None else ""
            text = urlunsplit((parsed.scheme, f"{credentials}{host}{port}", parsed.path, parsed.query, parsed.fragment))
    except ValueError:
        pass
    return _PASSWORD_PATTERN.sub(r"\1***", text)
