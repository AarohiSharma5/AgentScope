"""add budgets (SLOs / metric thresholds)

Creates the ``budgets`` table backing the analytics guardrails: cost caps and
quality/latency/failure SLOs the dashboard evaluates over each budget's own
window to show OK / warn / breach status. Tenant-scoped (``organization_id``
SET NULL, mirroring the other resources) with a composite
``(organization_id, created_at)`` index for newest-first listing.

Revision ID: e2f7b4a6d1c9
Revises: d5e9f3a1c8b2
Create Date: 2026-07-21 17:50:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2f7b4a6d1c9'
down_revision: Union[str, None] = 'd5e9f3a1c8b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'budgets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('metric', sa.String(length=50), nullable=False),
        sa.Column('comparison', sa.String(length=8), nullable=False),
        sa.Column('threshold_value', sa.Float(), nullable=False),
        sa.Column('window_days', sa.Integer(), nullable=False),
        sa.Column('model', sa.String(length=255), nullable=True),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('budgets', schema=None) as batch_op:
        batch_op.create_index('ix_budgets_created_at', ['created_at'], unique=False)
        batch_op.create_index('ix_budgets_organization_id', ['organization_id'], unique=False)
        batch_op.create_index(
            'ix_budgets_org_created', ['organization_id', 'created_at'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('budgets', schema=None) as batch_op:
        batch_op.drop_index('ix_budgets_org_created')
        batch_op.drop_index('ix_budgets_organization_id')
        batch_op.drop_index('ix_budgets_created_at')
    op.drop_table('budgets')
