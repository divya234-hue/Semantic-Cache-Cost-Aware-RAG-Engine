import base64
import binascii
import hashlib
import hmac
import json
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from backend.app.core.config import Settings

_TENANT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_TOKEN_PARTS = 3


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str


def _decode_segment(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    return base64.b64decode(padded, altchars=b"-_", validate=True)


def _valid_timestamp(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def _valid_token(token: str, settings: Settings) -> TenantContext | None:
    secret = settings.AUTH_SECRET_KEY
    parts = token.split(".")
    if not secret or len(secret) < 32 or len(token) > 8192 or len(parts) != _TOKEN_PARTS:
        return None
    try:
        header = json.loads(_decode_segment(parts[0]))
        claims: dict[str, Any] = json.loads(_decode_segment(parts[1]))
        supplied_signature = _decode_segment(parts[2])
    except (ValueError, TypeError, binascii.Error):
        return None
    if not isinstance(header, dict) or header.get("alg") != "HS256":
        return None
    signed_content = f"{parts[0]}.{parts[1]}".encode("ascii")
    expected_signature = hmac.new(secret.encode("utf-8"), signed_content, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_signature, supplied_signature):
        return None

    tenant_id = claims.get("tenant_id")
    expiration = claims.get("exp")
    issued_at = claims.get("iat")
    audience = claims.get("aud")
    if (
        not isinstance(tenant_id, str)
        or not _TENANT_ID.fullmatch(tenant_id)
        or not isinstance(claims.get("sub"), str)
        or not claims["sub"]
        or len(claims["sub"]) > 256
        or claims.get("iss") != settings.AUTH_ISSUER
        or audience != settings.AUTH_AUDIENCE
        or not _valid_timestamp(expiration)
        or expiration <= time.time()
        or not _valid_timestamp(issued_at)
        or expiration <= issued_at
        or expiration - issued_at > settings.AUTH_MAX_TOKEN_TTL_SECONDS
    ):
        return None
    if issued_at > time.time() + 30:
        return None
    return TenantContext(tenant_id=tenant_id)


def require_tenant(request: Request) -> TenantContext:
    settings: Settings = request.app.state.settings
    if not settings.REQUIRE_TENANT_AUTH:
        if settings.APP_ENV == "production":
            raise HTTPException(status_code=503, detail="Tenant authentication is not configured.")
        return TenantContext(settings.DEFAULT_TENANT_ID)

    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    context = _valid_token(token, settings) if separator and scheme.lower() == "bearer" else None
    if context is None:
        raise HTTPException(
            status_code=401,
            detail="A valid tenant bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return context


class TenantRateLimiter:
    def __init__(self, requests_per_minute: int, max_tenants: int = 10000) -> None:
        self.requests_per_minute = requests_per_minute
        self.max_tenants = max_tenants
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[int, int]] = {}

    def check(self, tenant_id: str) -> None:
        now = int(time.time())
        window = now // 60
        with self._lock:
            current_window, count = self._windows.get(tenant_id, (window, 0))
            if current_window != window:
                current_window, count = window, 0
            if count >= self.requests_per_minute:
                raise HTTPException(status_code=429, detail="Request rate limit exceeded.")
            if tenant_id not in self._windows and len(self._windows) >= self.max_tenants:
                oldest = min(self._windows, key=lambda key: self._windows[key][0])
                del self._windows[oldest]
            self._windows[tenant_id] = (current_window, count + 1)
