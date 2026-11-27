"""Security primitives: bcrypt password hashing, JWT tokens, Fernet vault, and secret log redaction."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

# Regexes matching API keys and auth tokens so they can NEVER leak into logs
_SECRET_PATTERNS = [
    re.compile(r"(sk-ant-[A-Za-z0-9_\-]{8,})"),
    re.compile(r"(sk-[A-Za-z0-9_\-]{12,})"),
    re.compile(r"(AIza[0-9A-Za-z_\-]{16,})"),
    re.compile(r"(AQ\.[0-9A-Za-z_\-]{12,})"),
    re.compile(r"(Bearer\s+[A-Za-z0-9\-._~+/]+=*)", re.IGNORECASE),
    re.compile(r"((?:x-api-key|x-goog-api-key|authorization)['\"]?\s*[:=]\s*['\"]?[^\s,'\"}]+)", re.IGNORECASE),
]


def redact_secrets(text: str) -> str:
    if not text:
        return text
    cleaned = text
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("[REDACTED_SECRET]", cleaned)
    return cleaned


class SecretRedactionFilter(logging.Filter):
    """Logging filter that scrubs API secrets and authorization headers from every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    redact_secrets(a) if isinstance(a, str) else a for a in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: redact_secrets(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
        return True


def configure_secure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    redactor = SecretRedactionFilter()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        )
        root.addHandler(handler)
    for handler in root.handlers:
        handler.addFilter(redactor)


# ---------------------------------------------------------------------------
# Password Hashing (bcrypt)
# ---------------------------------------------------------------------------
def hash_password(plain_password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT Access Tokens
# ---------------------------------------------------------------------------
def create_access_token(
    user_id: str,
    email: str,
    expires_minutes: Optional[int] = None,
    username: Optional[str] = None,
    full_name: Optional[str] = None,
    role: str = "admin",
) -> tuple[str, str, int]:
    """Returns (encoded_jwt, jti, ttl_seconds)."""
    settings = get_settings()
    ttl_minutes = expires_minutes or settings.jwt_access_token_expire_minutes
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=ttl_minutes)
    jti = uuid.uuid4().hex
    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "username": username or email.split("@")[0],
        "full_name": full_name,
        "role": role,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    token = jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    return token, jti, int(ttl_minutes * 60)


def decode_access_token(token: str) -> Dict[str, Any]:
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )


# ---------------------------------------------------------------------------
# Fernet Authenticated Encryption for Provider API Keys
# ---------------------------------------------------------------------------
def _get_fernet() -> Fernet:
    settings = get_settings()
    digest = hashlib.sha256(settings.encryption_secret_key.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    return Fernet(fernet_key)


def encrypt_api_key(plain_key: str) -> str:
    cleaned = plain_key.strip()
    return _get_fernet().encrypt(cleaned.encode("utf-8")).decode("utf-8")


def decrypt_api_key(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Stored provider API credential could not be decrypted") from exc


def mask_api_key(plain_key: str) -> str:
    """Return a fully masked indicator so zero secret characters ever reach the browser."""
    if not plain_key or not plain_key.strip():
        return ""
    return "••••••••••••••••"


def seal_account_cookie(account_data: Dict[str, Any]) -> str:
    """Fernet-encrypt minimal user record (with bcrypt hash) for stateless serverless recovery."""
    raw = json.dumps(account_data, separators=(",", ":")).encode("utf-8")
    return _get_fernet().encrypt(raw).decode("utf-8")


def unseal_account_cookie(sealed: str) -> Optional[Dict[str, Any]]:
    """Decrypt and validate a Fernet-sealed serverless account recovery cookie."""
    if not sealed:
        return None
    try:
        raw = _get_fernet().decrypt(sealed.encode("utf-8")).decode("utf-8")
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None
