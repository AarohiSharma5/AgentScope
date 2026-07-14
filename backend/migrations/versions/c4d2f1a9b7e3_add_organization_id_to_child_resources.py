"""add organization_id to child resources (phase 2 tenant isolation)

Denormalizes tenant ownership onto the remaining top-level resource tables so
agent runs, retrievals, evaluations, replays, comparisons and workflow
definitions can be scoped per organization without joining through their parent.

Revision ID: c4d2f1a9b7e3
Revises: 079078dbceb7
Create Date: 2026-07-14 14:40:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d2f1a9b7e3'
down_revision: Union[str, None] = '079078dbceb7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tables gaining a nullable organization_id FK (SET NULL) + index. Batch mode
# (SQLite) requires named constraints, so the foreign keys are named explicitly.
_TABLES = (
    "agent_runs",
    "retriever_traces",
    "evaluation_runs",
    "replay_runs",
    "model_comparisons",
    "workflow_definitions",
)


def upgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('organization_id', sa.Integer(), nullable=True))
            batch_op.create_index(
                batch_op.f(f'ix_{table}_organization_id'), ['organization_id'], unique=False
            )
            batch_op.create_foreign_key(
                f'fk_{table}_organization_id', 'organizations',
                ['organization_id'], ['id'], ondelete='SET NULL',
            )


def downgrade() -> None:
    for table in reversed(_TABLES):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(f'fk_{table}_organization_id', type_='foreignkey')
            batch_op.drop_index(batch_op.f(f'ix_{table}_organization_id'))
            batch_op.drop_column('organization_id')
