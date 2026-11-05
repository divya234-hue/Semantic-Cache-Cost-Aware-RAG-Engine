import hmac
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.database import get_db_session
from backend.app.core.security import require_tenant
from backend.app.models.auth import AuthSession, User, UserRole
from backend.app.services.auth_service import decode_access_token, utcnow, verify_csrf_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    tenant_id: str
    role: UserRole
    email: str
    session_id: str | None
    legacy: bool = False


def get_db(request: Request) -> Iterator[Session]:
    yield from get_db_session(request.app.state.db_session_factory)


def _validate_csrf(request: Request, session_id: str, settings: Settings) -> None:
    csrf_cookie = "__Host-csrf_token" if settings.APP_ENV == "production" else "csrf_token"
    cookie_token = request.cookies.get(csrf_cookie, "")
    header_token = request.headers.get("x-csrf-token", "")
    if (
        not cookie_token
        or not header_token
        or not hmac.compare_digest(cookie_token, header_token)
        or not verify_csrf_token(cookie_token, session_id, settings)
    ):
        raise HTTPException(status_code=403, detail="A valid CSRF token is required.")


def current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    bearer_token: Annotated[str | None, Depends(oauth2_scheme)],
) -> AuthContext:
    settings: Settings = request.app.state.settings
    is_bearer = bearer_token is not None
    cookie_name = "__Host-access_token" if settings.APP_ENV == "production" else "access_token"
    token = bearer_token if is_bearer else request.cookies.get(cookie_name, "")
    if not token:
        if not settings.AUTHENTICATION_REQUIRED and settings.APP_ENV != "production":
            legacy_tenant = require_tenant(request)
            return AuthContext(
                user_id="legacy-development-user",
                tenant_id=legacy_tenant.tenant_id,
                role=UserRole.ADMIN,
                email="legacy@localhost",
                session_id=None,
                legacy=True,
            )
        raise HTTPException(
            status_code=401,
            detail="Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = decode_access_token(token, settings)
    if claims is None:
        if not settings.AUTHENTICATION_REQUIRED and settings.APP_ENV != "production":
            legacy_tenant = require_tenant(request)
            return AuthContext(
                user_id="legacy-development-user",
                tenant_id=legacy_tenant.tenant_id,
                role=UserRole.ADMIN,
                email="legacy@localhost",
                session_id=None,
                legacy=True,
            )
        raise HTTPException(
            status_code=401,
            detail="The access token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id, tenant_id, session_id, access_jti = (
        claims.get("sub"),
        claims.get("tid"),
        claims.get("sid"),
        claims.get("jti"),
    )
    if not all(isinstance(value, str) and value for value in (user_id, tenant_id, session_id)):
        raise HTTPException(status_code=401, detail="The access token is invalid.")

    auth_session = db.get(AuthSession, session_id)
    session_expiration = auth_session.expires_at if auth_session is not None else None
    if session_expiration is not None and session_expiration.tzinfo is None:
        session_expiration = session_expiration.replace(tzinfo=UTC)
    user = db.scalar(
        select(User).where(
            User.id == user_id, User.tenant_id == tenant_id, User.is_active.is_(True)
        )
    )
    if (
        auth_session is None
        or auth_session.user_id != user_id
        or auth_session.revoked_at is not None
        or session_expiration <= utcnow()
        or auth_session.access_jti != access_jti
        or user is None
    ):
        raise HTTPException(
            status_code=401,
            detail="The session is invalid or has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not is_bearer and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        _validate_csrf(request, session_id, settings)
    try:
        role = UserRole(user.role)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="The account has an invalid role.") from exc
    return AuthContext(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=role,
        email=user.email,
        session_id=session_id,
    )


def require_admin(context: Annotated[AuthContext, Depends(current_user)]) -> AuthContext:
    if context.role is not UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Administrator privileges are required.")
    return context


def require_editor_or_admin(
    context: Annotated[AuthContext, Depends(current_user)],
) -> AuthContext:
    if context.role is UserRole.VIEWER:
        raise HTTPException(status_code=403, detail="This account cannot modify documents.")
    return context


CurrentUser = Annotated[AuthContext, Depends(current_user)]
AdminUser = Annotated[AuthContext, Depends(require_admin)]
EditorOrAdminUser = Annotated[AuthContext, Depends(require_editor_or_admin)]
DatabaseSession = Annotated[Session, Depends(get_db)]
