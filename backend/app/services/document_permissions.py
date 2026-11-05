import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.api.dependencies import AuthContext
from backend.app.models.auth import (
    DocumentPermission,
    DocumentRecord,
    User,
    UserRole,
)
from backend.app.services.auth_service import record_audit


def document_id_for_path(source_path: str) -> str:
    return hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:16]


def permitted_document_paths(db: Session, context: AuthContext) -> set[str] | None:
    if context.role is UserRole.ADMIN:
        return None
    records = db.scalars(
        select(DocumentRecord)
        .outerjoin(DocumentPermission, DocumentPermission.document_id == DocumentRecord.id)
        .where(
            DocumentRecord.tenant_id == context.tenant_id,
            or_(
                DocumentRecord.owner_user_id == context.user_id,
                (
                    (DocumentPermission.user_id == context.user_id)
                    & DocumentPermission.can_read.is_(True)
                ),
            ),
        )
    ).all()
    return {record.source_path for record in records}


def permitted_document_ids(db: Session, context: AuthContext) -> list[str] | None:
    paths = permitted_document_paths(db, context)
    if paths is None:
        return None
    return [document_id_for_path(path) for path in sorted(paths)]


def permission_scope(db: Session, context: AuthContext) -> str:
    document_ids = permitted_document_ids(db, context)
    scope_parts = [
        context.tenant_id,
        context.user_id,
        context.role.value,
        "*" if document_ids is None else ",".join(document_ids),
    ]
    return hashlib.sha256("\0".join(scope_parts).encode("utf-8")).hexdigest()


def get_document_record(
    db: Session,
    tenant_id: str,
    source_path: str,
) -> DocumentRecord | None:
    return db.scalar(
        select(DocumentRecord).where(
            DocumentRecord.tenant_id == tenant_id,
            DocumentRecord.source_path == source_path,
        )
    )


def record_document_owner(
    db: Session,
    tenant_id: str,
    source_path: str,
    owner_user_id: str,
) -> DocumentRecord:
    now = datetime.now(UTC)
    record = get_document_record(db, tenant_id, source_path)
    if record is None:
        record = DocumentRecord(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            source_path=source_path,
            owner_user_id=owner_user_id,
            created_at=now,
            updated_at=now,
        )
        db.add(record)
    else:
        db.query(DocumentPermission).filter(DocumentPermission.document_id == record.id).delete(
            synchronize_session=False
        )
        record.owner_user_id = owner_user_id
        record.updated_at = now
    return record


def can_read_document(
    db: Session,
    context: AuthContext,
    source_path: str,
) -> bool:
    if context.role is UserRole.ADMIN or context.legacy:
        return True
    record = get_document_record(db, context.tenant_id, source_path)
    if record is None:
        return False
    if record.owner_user_id == context.user_id:
        return True
    permission = db.scalar(
        select(DocumentPermission).where(
            DocumentPermission.document_id == record.id,
            DocumentPermission.user_id == context.user_id,
            DocumentPermission.can_read.is_(True),
        )
    )
    return permission is not None


def can_edit_document(
    db: Session,
    context: AuthContext,
    source_path: str,
) -> bool:
    if context.role is UserRole.ADMIN or context.legacy:
        return True
    if context.role is UserRole.VIEWER:
        return False
    record = get_document_record(db, context.tenant_id, source_path)
    if record is None:
        return False
    if record.owner_user_id == context.user_id:
        return True
    permission = db.scalar(
        select(DocumentPermission).where(
            DocumentPermission.document_id == record.id,
            DocumentPermission.user_id == context.user_id,
            DocumentPermission.can_edit.is_(True),
        )
    )
    return permission is not None


def replace_document_permissions(
    db: Session,
    context: AuthContext,
    record: DocumentRecord,
    permissions: list[tuple[str, bool, bool]],
) -> None:
    target_user_ids = [user_id for user_id, _can_read, _can_edit in permissions]
    if target_user_ids:
        users = db.scalars(
            select(User).where(
                User.tenant_id == context.tenant_id,
                User.id.in_(target_user_ids),
                User.is_active.is_(True),
            )
        ).all()
        if {user.id for user in users} != set(target_user_ids):
            raise HTTPException(
                status_code=400,
                detail="Permissions can only be assigned to active users in this tenant.",
            )
    db.query(DocumentPermission).filter(DocumentPermission.document_id == record.id).delete(
        synchronize_session=False
    )
    now = datetime.now(UTC)
    for user_id, can_read, can_edit in permissions:
        db.add(
            DocumentPermission(
                id=str(uuid.uuid4()),
                document_id=record.id,
                user_id=user_id,
                can_read=can_read,
                can_edit=can_edit,
                created_by_user_id=context.user_id,
                created_at=now,
            )
        )
    record_audit(
        db,
        "document.permissions_changed",
        actor_user_id=context.user_id,
        tenant_id=context.tenant_id,
        resource_type="document",
        resource_id=record.source_path,
    )
    db.commit()
