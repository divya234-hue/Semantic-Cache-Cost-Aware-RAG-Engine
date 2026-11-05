"""Add tenant authentication, document permissions, and audit tables.

Revision ID: 0001_add_authentication
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_add_authentication"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_tenants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "auth_users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_auth_users_tenant_id", "auth_users", ["tenant_id"])
    op.create_index("ix_auth_users_email", "auth_users", ["email"])
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("access_jti", sa.String(length=36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("refresh_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table(
        "auth_documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("source_path", sa.String(length=512), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["auth_users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "source_path", name="uq_auth_document_tenant_path"),
    )
    op.create_index("ix_auth_documents_tenant_id", "auth_documents", ["tenant_id"])
    op.create_index("ix_auth_documents_owner_user_id", "auth_documents", ["owner_user_id"])
    op.create_table(
        "auth_document_permissions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("can_read", sa.Boolean(), nullable=False),
        sa.Column("can_edit", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["auth_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["auth_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["auth_users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("document_id", "user_id", name="uq_auth_document_permission_user"),
    )
    op.create_index(
        "ix_auth_document_permissions_document_id", "auth_document_permissions", ["document_id"]
    )
    op.create_index(
        "ix_auth_document_permissions_user_id", "auth_document_permissions", ["user_id"]
    )
    op.create_table(
        "auth_audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36)),
        sa.Column("tenant_id", sa.String(length=36)),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("resource_type", sa.String(length=80)),
        sa.Column("resource_id", sa.String(length=255)),
        sa.ForeignKeyConstraint(["actor_user_id"], ["auth_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["auth_tenants.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_auth_audit_events_actor_user_id", "auth_audit_events", ["actor_user_id"])
    op.create_index("ix_auth_audit_events_tenant_id", "auth_audit_events", ["tenant_id"])
    op.create_index("ix_auth_audit_events_action", "auth_audit_events", ["action"])


def downgrade() -> None:
    op.drop_table("auth_audit_events")
    op.drop_table("auth_document_permissions")
    op.drop_table("auth_documents")
    op.drop_table("auth_sessions")
    op.drop_table("auth_users")
    op.drop_table("auth_tenants")
