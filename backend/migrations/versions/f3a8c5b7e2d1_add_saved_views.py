"""add saved_views (custom analytics dashboards)

Creates the ``saved_views`` table backing named analytics dashboard
configurations (range + model filter, extensible via the JSON ``config`` blob).
Tenant-scoped (``organization_id`` SET NULL, mirroring the other resources) with
a composite ``(organization_id, created_at)`` index for newest-first listing.

Revision ID: f3a8c5b7e2d1
Revises: e2f7b4a6d1c9
Create Date: 2026-07-21 19:05:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a8c5b7e2d1'
down_revision: Union[str, None] = 'e2f7b4a6d1c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'saved_views',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('saved_views', schema=None) as batch_op:
        batch_op.create_index('ix_saved_views_created_at', ['created_at'], unique=False)
        batch_op.create_index('ix_saved_views_organization_id', ['organization_id'], unique=False)
        batch_op.create_index(
            'ix_saved_views_org_created', ['organization_id', 'created_at'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('saved_views', schema=None) as batch_op:
        batch_op.drop_index('ix_saved_views_org_created')
        batch_op.drop_index('ix_saved_views_organization_id')
        batch_op.drop_index('ix_saved_views_created_at')
    op.drop_table('saved_views')
