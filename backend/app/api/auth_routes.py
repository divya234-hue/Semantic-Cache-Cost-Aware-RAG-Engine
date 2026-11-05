import hashlib
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from backend.app.api.dependencies import AdminUser, CurrentUser, DatabaseSession
from backend.app.core.config import Settings
from backend.app.models.auth import AuthSession, User, UserRole
from backend.app.schemas.auth import (
    ChangePasswordRequest,
    CreateUserRequest,
    LoginResponse,
    RegisterRequest,
    UpdateRoleRequest,
    UserListResponse,
)
from backend.app.services.auth_service import (
    create_tenant_user,
    decode_access_token,
    find_valid_refresh_session,
    hash_password,
    issue_session,
    record_audit,
    register_tenant_admin,
    revoke_session,
    revoke_user_sessions,
    rotate_refresh_session,
    utcnow,
    verify_csrf_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _rate_limit(request: Request) -> None:
    client_host = request.client.host if request.client else "unknown"
    request.app.state.auth_rate_limiter.check(client_host)


def _require_auth_secret(settings: Settings) -> None:
    if not settings.AUTH_SECRET_KEY or len(settings.AUTH_SECRET_KEY) < 32:
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured. Set AUTH_SECRET_KEY to at least 32 characters.",
        )


def _check_browser_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    fetch_site = request.headers.get("sec-fetch-site")
    if origin and origin not in settings.CORS_ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="The request origin is not allowed.")
    if fetch_site == "cross-site":
        raise HTTPException(
            status_code=403, detail="Cross-site authentication requests are blocked."
        )


def _secure_cookie(settings: Settings) -> bool:
    return settings.APP_ENV == "production"


def _cookie_name(name: str, settings: Settings) -> str:
    return f"__Host-{name}" if _secure_cookie(settings) else name


def _set_auth_cookies(response: Response, tokens, settings: Settings) -> None:
    refresh_max_age = settings.AUTH_REFRESH_TOKEN_TTL_DAYS * 24 * 60 * 60
    cookie_settings = {
        "secure": _secure_cookie(settings),
        "samesite": "strict",
        "path": "/",
    }
    response.set_cookie(
        _cookie_name("access_token", settings),
        tokens.access_token,
        httponly=True,
        max_age=settings.AUTH_ACCESS_TOKEN_TTL_MINUTES * 60,
        **cookie_settings,
    )
    response.set_cookie(
        _cookie_name("refresh_token", settings),
        tokens.refresh_token,
        httponly=True,
        max_age=refresh_max_age,
        **cookie_settings,
    )
    response.set_cookie(
        _cookie_name("csrf_token", settings),
        tokens.csrf_token,
        httponly=False,
        max_age=refresh_max_age,
        **cookie_settings,
    )


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    for name in ("access_token", "refresh_token", "csrf_token"):
        response.delete_cookie(
            _cookie_name(name, settings),
            path="/",
            secure=_secure_cookie(settings),
            httponly=name != "csrf_token",
            samesite="strict",
        )


def _user_response(user: User) -> LoginResponse:
    return LoginResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        tenant_id=user.tenant_id,
        role=user.role,
        is_active=user.is_active,
    )


def _record_failed_login(db: Session, email: str) -> None:
    email_fingerprint = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
    record_audit(
        db,
        "user.login_failed",
        resource_type="account_fingerprint",
        resource_id=email_fingerprint,
    )
    db.commit()


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: DatabaseSession,
) -> LoginResponse:
    settings = _settings(request)
    _rate_limit(request)
    _check_browser_origin(request, settings)
    _require_auth_secret(settings)
    user = register_tenant_admin(
        db,
        str(payload.email),
        payload.display_name,
        payload.tenant_name,
        payload.password,
    )
    if user is None:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    tokens = issue_session(db, user, settings)
    _set_auth_cookies(response, tokens, settings)
    return _user_response(user)


@router.post("/login", response_model=LoginResponse)
def login(
    request: Request,
    response: Response,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DatabaseSession,
) -> LoginResponse:
    settings = _settings(request)
    _rate_limit(request)
    _check_browser_origin(request, settings)
    _require_auth_secret(settings)
    email = form.username.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not user.is_active or not verify_password(user.password_hash, form.password):
        _record_failed_login(db, email)
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    tokens = issue_session(db, user, settings)
    record_audit(
        db,
        "user.login_succeeded",
        actor_user_id=user.id,
        tenant_id=user.tenant_id,
        resource_type="session",
        resource_id=tokens.session_id,
    )
    db.commit()
    _set_auth_cookies(response, tokens, settings)
    return _user_response(user)


@router.post("/refresh", response_model=LoginResponse)
def refresh(
    request: Request,
    response: Response,
    db: DatabaseSession,
) -> LoginResponse:
    settings = _settings(request)
    _rate_limit(request)
    _check_browser_origin(request, settings)
    _require_auth_secret(settings)
    refresh_token = request.cookies.get(_cookie_name("refresh_token", settings), "")
    auth_session = find_valid_refresh_session(db, refresh_token) if refresh_token else None
    csrf_token = request.cookies.get(_cookie_name("csrf_token", settings), "")
    header_token = request.headers.get("x-csrf-token", "")
    if (
        auth_session is None
        or not csrf_token
        or not header_token
        or not hmac.compare_digest(csrf_token, header_token)
        or not verify_csrf_token(csrf_token, auth_session.id, settings)
    ):
        error_response = JSONResponse(
            status_code=401,
            content={"detail": "The refresh session is invalid or expired."},
        )
        _clear_auth_cookies(error_response, settings)
        return error_response
    user = db.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        revoke_session(db, auth_session)
        db.commit()
        error_response = JSONResponse(
            status_code=401,
            content={"detail": "The refresh session is invalid or expired."},
        )
        _clear_auth_cookies(error_response, settings)
        return error_response
    tokens = rotate_refresh_session(db, auth_session, user, refresh_token, settings)
    if tokens is None:
        error_response = JSONResponse(
            status_code=401,
            content={"detail": "The refresh session was already used."},
        )
        _clear_auth_cookies(error_response, settings)
        return error_response
    _set_auth_cookies(response, tokens, settings)
    return _user_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: DatabaseSession) -> Response:
    settings = _settings(request)
    _rate_limit(request)
    _check_browser_origin(request, settings)
    refresh_token = request.cookies.get(_cookie_name("refresh_token", settings), "")
    auth_session = find_valid_refresh_session(db, refresh_token) if refresh_token else None
    if auth_session is None:
        access_cookie = _cookie_name("access_token", settings)
        claims = decode_access_token(request.cookies.get(access_cookie, ""), settings)
        session_id = claims.get("sid") if claims is not None else None
        if isinstance(session_id, str):
            candidate = db.get(AuthSession, session_id)
            if candidate is not None and candidate.revoked_at is None:
                auth_session = candidate
    if auth_session is not None:
        csrf_token = request.cookies.get(_cookie_name("csrf_token", settings), "")
        header_token = request.headers.get("x-csrf-token", "")
        if (
            not csrf_token
            or not header_token
            or not hmac.compare_digest(csrf_token, header_token)
            or not verify_csrf_token(csrf_token, auth_session.id, settings)
        ):
            raise HTTPException(status_code=403, detail="A valid CSRF token is required.")
        user = db.get(User, auth_session.user_id)
        revoke_session(db, auth_session)
        record_audit(
            db,
            "user.logout",
            actor_user_id=auth_session.user_id,
            tenant_id=user.tenant_id if user is not None else None,
            resource_type="session",
            resource_id=auth_session.id,
        )
        db.commit()
    _clear_auth_cookies(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=LoginResponse)
def me(context: CurrentUser, db: DatabaseSession) -> LoginResponse:
    if context.legacy:
        raise HTTPException(status_code=401, detail="A user account is required.")
    user = db.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="The account is no longer available.")
    return _user_response(user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
    context: CurrentUser,
    request: Request,
    response: Response,
    db: DatabaseSession,
) -> Response:
    _rate_limit(request)
    if context.legacy:
        raise HTTPException(status_code=401, detail="A user account is required.")
    user = db.get(User, context.user_id)
    if user is None or not verify_password(user.password_hash, payload.current_password):
        raise HTTPException(status_code=400, detail="The current password is incorrect.")
    if verify_password(user.password_hash, payload.new_password):
        raise HTTPException(
            status_code=400, detail="Choose a new password different from the current one."
        )
    user.password_hash = hash_password(payload.new_password)
    user.updated_at = utcnow()
    record_audit(
        db,
        "user.password_changed",
        actor_user_id=user.id,
        tenant_id=user.tenant_id,
        resource_type="user",
        resource_id=user.id,
    )
    revoke_user_sessions(db, user.id)
    db.commit()
    _clear_auth_cookies(response, _settings(request))
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/users", response_model=UserListResponse)
def list_users(context: AdminUser, db: DatabaseSession) -> UserListResponse:
    users = db.scalars(
        select(User).where(User.tenant_id == context.tenant_id).order_by(User.created_at)
    ).all()
    return UserListResponse(users=[_user_response(user) for user in users])


@router.post("/users", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest,
    context: AdminUser,
    db: DatabaseSession,
) -> LoginResponse:
    user = create_tenant_user(
        db,
        tenant_id=context.tenant_id,
        actor_user_id=context.user_id,
        email=str(payload.email),
        display_name=payload.display_name,
        password=payload.password,
        role=payload.role,
    )
    if user is None:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    return _user_response(user)


@router.patch("/users/{user_id}/role", response_model=LoginResponse)
def update_user_role(
    user_id: str,
    payload: UpdateRoleRequest,
    context: AdminUser,
    db: DatabaseSession,
) -> LoginResponse:
    user = db.scalar(select(User).where(User.id == user_id, User.tenant_id == context.tenant_id))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.id == context.user_id and payload.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=409, detail="Administrators cannot demote their own account."
        )
    if user.role == UserRole.ADMIN.value and payload.role != UserRole.ADMIN.value:
        admin_count = db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.tenant_id == context.tenant_id,
                User.role == UserRole.ADMIN.value,
                User.is_active.is_(True),
            )
        )
        if admin_count == 1:
            raise HTTPException(
                status_code=409, detail="A tenant must retain at least one administrator."
            )
    user.role = payload.role
    user.updated_at = utcnow()
    record_audit(
        db,
        "user.role_changed",
        actor_user_id=context.user_id,
        tenant_id=context.tenant_id,
        resource_type="user",
        resource_id=user.id,
    )
    revoke_user_sessions(db, user.id)
    db.commit()
    return _user_response(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user(user_id: str, context: AdminUser, db: DatabaseSession) -> Response:
    user = db.scalar(select(User).where(User.id == user_id, User.tenant_id == context.tenant_id))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.id == context.user_id:
        raise HTTPException(
            status_code=409, detail="Administrators cannot deactivate their own account."
        )
    if user.role == UserRole.ADMIN.value and user.is_active:
        admin_count = db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.tenant_id == context.tenant_id,
                User.role == UserRole.ADMIN.value,
                User.is_active.is_(True),
            )
        )
        if admin_count == 1:
            raise HTTPException(
                status_code=409, detail="A tenant must retain at least one administrator."
            )
    user.is_active = False
    user.updated_at = utcnow()
    record_audit(
        db,
        "user.deactivated",
        actor_user_id=context.user_id,
        tenant_id=context.tenant_id,
        resource_type="user",
        resource_id=user.id,
    )
    revoke_user_sessions(db, user.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
