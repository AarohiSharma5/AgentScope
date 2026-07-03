"""Authentication & multi-tenancy models (v1.0).

Purely additive: introduces users, organizations, projects, memberships, API
keys and audit logs. No existing table or model is modified, so the platform
stays fully backward compatible — these tables are simply unused until auth is
adopted by a route.

Tenancy model
-------------
* An :class:`Organization` is the top-level tenant boundary.
* A :class:`User` may belong to many organizations through a :class:`Membership`
  that carries their :class:`~app.auth.roles.Role` in that organization.
* A :class:`Project` belongs to exactly one organization (project isolation).
* An :class:`ApiKey` is scoped to an organization and, optionally, a project.
* :class:`AuditLog` rows record security-relevant actions.

All column types are chosen to work identically on SQLite and PostgreSQL.
"""
from sqlalchemy import JSON, Index, UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..utils.timeutils import utcnow


class Organization(db.Model):
    """A tenant: the isolation boundary that owns projects, keys and members."""

    __tablename__ = "organizations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    memberships = db.relationship(
        "Membership", back_populates="organization",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    projects = db.relationship(
        "Project", back_populates="organization",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    api_keys = db.relationship(
        "ApiKey", back_populates="organization",
        cascade="all, delete-orphan", passive_deletes=True,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class User(db.Model):
    """A person who can authenticate and belong to organizations."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(320), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(200), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # A platform superadmin bypasses org membership checks (ops/support).
    is_superadmin = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)

    memberships = db.relationship(
        "Membership", back_populates="user",
        cascade="all, delete-orphan", passive_deletes=True,
    )

    # -- password handling (werkzeug pbkdf2:sha256; no extra dependency) -----

    def set_password(self, password: str) -> None:
        """Hash and store a password (never stored in plaintext)."""
        self.password_hash = generate_password_hash(password, method="pbkdf2:sha256")

    def check_password(self, password: str) -> bool:
        """Constant-time verification of a candidate password."""
        return check_password_hash(self.password_hash, password)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "is_active": self.is_active,
            "is_superadmin": self.is_superadmin,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }


class Membership(db.Model):
    """A user's role within an organization (RBAC binding)."""

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_membership_user_org"),
        Index("ix_memberships_org_role", "organization_id", "role"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role = db.Column(db.String(20), nullable=False, default="viewer")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    user = db.relationship("User", back_populates="memberships")
    organization = db.relationship("Organization", back_populates="memberships")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "organization_id": self.organization_id,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Project(db.Model):
    """A project inside an organization — the finest isolation boundary."""

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_project_org_slug"),
    )

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    organization = db.relationship("Organization", back_populates="projects")
    api_keys = db.relationship(
        "ApiKey", back_populates="project",
        cascade="all, delete-orphan", passive_deletes=True,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "name": self.name,
            "slug": self.slug,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ApiKey(db.Model):
    """A hashed API key scoped to an organization (and optionally a project).

    The raw secret is shown exactly once at creation; only its SHA-256 hash is
    stored. ``prefix`` is a short, non-secret label for display/lookup.
    """

    __tablename__ = "api_keys"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id = db.Column(
        db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name = db.Column(db.String(200), nullable=False)
    prefix = db.Column(db.String(16), nullable=False, index=True)
    key_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    role = db.Column(db.String(20), nullable=False, default="developer")
    created_by_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_used_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    revoked = db.Column(db.Boolean, nullable=False, default=False, index=True)

    organization = db.relationship("Organization", back_populates="api_keys")
    project = db.relationship("Project", back_populates="api_keys")

    def is_valid(self, now=None) -> bool:
        """True when the key is neither revoked nor expired."""
        if self.revoked:
            return False
        if self.expires_at is not None:
            now = now or utcnow()
            expires = self.expires_at
            if expires.tzinfo is None:  # normalize naive timestamps from SQLite
                from datetime import timezone

                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= now:
                return False
        return True

    def to_dict(self, include_secret: str = None) -> dict:
        data = {
            "id": self.id,
            "organization_id": self.organization_id,
            "project_id": self.project_id,
            "name": self.name,
            "prefix": self.prefix,
            "role": self.role,
            "created_by_user_id": self.created_by_user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked": self.revoked,
        }
        if include_secret is not None:
            data["key"] = include_secret  # returned once, on creation
        return data


class AuditLog(db.Model):
    """An append-only record of a security-relevant action."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_org_created", "organization_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_id = db.Column(
        db.Integer, db.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    api_key_id = db.Column(db.Integer, db.ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True)

    action = db.Column(db.String(80), nullable=False, index=True)
    target_type = db.Column(db.String(80), nullable=True)
    target_id = db.Column(db.String(80), nullable=True)
    ip = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(400), nullable=True)
    # 'metadata' is reserved by SQLAlchemy's declarative base; map it explicitly.
    log_metadata = db.Column("metadata", JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "project_id": self.project_id,
            "user_id": self.user_id,
            "api_key_id": self.api_key_id,
            "action": self.action,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "ip": self.ip,
            "user_agent": self.user_agent,
            "metadata": self.log_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
