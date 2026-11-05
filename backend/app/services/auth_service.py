import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.models.auth import (
    AuditEvent,
    AuthSession,
    Tenant,
    User,
    UserRole,
)

_password_hasher = PasswordHasher()


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    csrf_token: str
    session_id: str
    refresh_expires_at: datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerifyMismatchError):
        return False


def record_audit(
    db: Session,
    action: str,
    *,
    actor_user_id: str | None = None,
    tenant_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> None:
    db.add(
        AuditEvent(
            id=str(uuid.uuid4()),
            occurred_at=utcnow(),
            actor_user_id=actor_user_id,
            tenant_id=tenant_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
        )
    )


def register_tenant_admin(
    db: Session,
    email: str,
    display_name: str,
    tenant_name: str,
    password: str,
) -> User | None:
    now = utcnow()
    tenant = Tenant(id=str(uuid.uuid4()), name=tenant_name.strip(), created_at=now)
    user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        email=email.strip().lower(),
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        role=UserRole.ADMIN.value,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add_all([tenant, user])
    record_audit(
        db,
        "user.registered",
        actor_user_id=user.id,
        tenant_id=tenant.id,
        resource_type="user",
        resource_id=user.id,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    db.refresh(user)
    return user


def create_tenant_user(
    db: Session,
    *,
    tenant_id: str,
    actor_user_id: str,
    email: str,
    display_name: str,
    password: str,
    role: str,
) -> User | None:
    now = utcnow()
    user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        email=email.strip().lower(),
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        role=role,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    record_audit(
        db,
        "user.created",
        actor_user_id=actor_user_id,
        tenant_id=tenant_id,
        resource_type="user",
        resource_id=user.id,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    db.refresh(user)
    return user


def issue_session(db: Session, user: User, settings: Settings) -> IssuedTokens:
    now = utcnow()
    session_id = str(uuid.uuid4())
    access_jti = str(uuid.uuid4())
    refresh_token = secrets.token_urlsafe(48)
    expires_at = now + timedelta(days=settings.AUTH_REFRESH_TOKEN_TTL_DAYS)
    db.add(
        AuthSession(
            id=session_id,
            user_id=user.id,
            refresh_token_hash=hash_token(refresh_token),
            access_jti=access_jti,
            expires_at=expires_at,
            created_at=now,
        )
    )
    db.commit()
    access_token = encode_access_token(
        user,
        session_id,
        access_jti,
        settings,
        now=now,
    )
    return IssuedTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        csrf_token=make_csrf_token(session_id, settings),
        session_id=session_id,
        refresh_expires_at=expires_at,
    )


def encode_access_token(
    user: User,
    session_id: str,
    access_jti: str,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> str:
    issued_at = now or utcnow()
    return jwt.encode(
        {
            "sub": user.id,
            "tid": user.tenant_id,
            "sid": session_id,
            "jti": access_jti,
            "token_type": "access",
            "iss": settings.AUTH_ISSUER,
            "aud": settings.AUTH_AUDIENCE,
            "iat": issued_at,
            "exp": issued_at + timedelta(minutes=settings.AUTH_ACCESS_TOKEN_TTL_MINUTES),
        },
        settings.AUTH_SECRET_KEY,
        algorithm="HS256",
    )


def decode_access_token(token: str, settings: Settings) -> dict[str, object] | None:
    if not settings.AUTH_SECRET_KEY or len(token) > 8192:
        return None
    try:
        claims = jwt.decode(
            token,
            settings.AUTH_SECRET_KEY,
            algorithms=["HS256"],
            issuer=settings.AUTH_ISSUER,
            audience=settings.AUTH_AUDIENCE,
            options={"require": ["sub", "tid", "sid", "jti", "token_type", "iat", "exp"]},
        )
    except jwt.InvalidTokenError:
        return None
    return claims if claims.get("token_type") == "access" else None


def make_csrf_token(session_id: str, settings: Settings) -> str:
    nonce = secrets.token_urlsafe(32)
    signature = hmac.new(
        settings.AUTH_SECRET_KEY.encode("utf-8"),
        f"{session_id}:{nonce}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{nonce}.{signature}"


def verify_csrf_token(token: str, session_id: str, settings: Settings) -> bool:
    nonce, separator, supplied_signature = token.partition(".")
    if not separator or not nonce or not supplied_signature:
        return False
    expected_signature = hmac.new(
        settings.AUTH_SECRET_KEY.encode("utf-8"),
        f"{session_id}:{nonce}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_signature, supplied_signature)


def find_valid_refresh_session(db: Session, refresh_token: str) -> AuthSession | None:
    token_hash = hash_token(refresh_token)
    return db.scalar(
        select(AuthSession).where(
            AuthSession.refresh_token_hash == token_hash,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        )
    )


def rotate_refresh_session(
    db: Session,
    auth_session: AuthSession,
    user: User,
    refresh_token: str,
    settings: Settings,
) -> IssuedTokens | None:
    now = utcnow()
    new_refresh_token = secrets.token_urlsafe(48)
    new_access_jti = str(uuid.uuid4())
    new_expires_at = now + timedelta(days=settings.AUTH_REFRESH_TOKEN_TTL_DAYS)
    result = db.execute(
        update(AuthSession)
        .where(
            AuthSession.id == auth_session.id,
            AuthSession.refresh_token_hash == hash_token(refresh_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
        .values(
            refresh_token_hash=hash_token(new_refresh_token),
            access_jti=new_access_jti,
            expires_at=new_expires_at,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        return None
    db.commit()
    return IssuedTokens(
        access_token=encode_access_token(user, auth_session.id, new_access_jti, settings, now=now),
        refresh_token=new_refresh_token,
        csrf_token=make_csrf_token(auth_session.id, settings),
        session_id=auth_session.id,
        refresh_expires_at=new_expires_at,
    )


def revoke_session(db: Session, auth_session: AuthSession) -> None:
    auth_session.revoked_at = utcnow()


def revoke_user_sessions(db: Session, user_id: str) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
