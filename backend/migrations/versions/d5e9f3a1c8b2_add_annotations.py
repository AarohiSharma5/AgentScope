"""add annotations (timeline deploy/change markers)

Creates the ``annotations`` table backing the analytics timeline markers, so
quality/cost/latency movements can be tied to the change that caused them. The
table is tenant-scoped (``organization_id`` SET NULL, mirroring the other
resources) with a composite ``(organization_id, annotated_at)`` index for
windowed listing.

Revision ID: d5e9f3a1c8b2
Revises: a1c2e5f80b34
Create Date: 2026-07-21 15:40:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5e9f3a1c8b2'
down_revision: Union[str, None] = 'a1c2e5f80b34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'annotations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('annotated_at', sa.DateTime(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('annotations', schema=None) as batch_op:
        batch_op.create_index('ix_annotations_annotated_at', ['annotated_at'], unique=False)
        batch_op.create_index('ix_annotations_created_at', ['created_at'], unique=False)
        batch_op.create_index('ix_annotations_organization_id', ['organization_id'], unique=False)
        batch_op.create_index(
            'ix_annotations_org_date', ['organization_id', 'annotated_at'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('annotations', schema=None) as batch_op:
        batch_op.drop_index('ix_annotations_org_date')
        batch_op.drop_index('ix_annotations_organization_id')
        batch_op.drop_index('ix_annotations_created_at')
        batch_op.drop_index('ix_annotations_annotated_at')
    op.drop_table('annotations')
