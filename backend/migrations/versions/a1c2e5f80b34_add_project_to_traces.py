"""add project (application/area) to traces

Adds a nullable ``project`` column plus a ``(project, timestamp)`` composite
index so the Requests feed can be segmented by application/area — the axis teams
actually organize around — without a full scan.

Revision ID: a1c2e5f80b34
Revises: f1b8e3c72d94
Create Date: 2026-07-17 23:40:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c2e5f80b34'
down_revision: Union[str, None] = 'f1b8e3c72d94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('traces', schema=None) as batch_op:
        batch_op.add_column(sa.Column('project', sa.String(length=120), nullable=True))
        batch_op.create_index('ix_traces_project_timestamp', ['project', 'timestamp'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('traces', schema=None) as batch_op:
        batch_op.drop_index('ix_traces_project_timestamp')
        batch_op.drop_column('project')
