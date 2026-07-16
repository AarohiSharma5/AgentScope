"""unique prompt version per agent run

Enforces ``UNIQUE(agent_run_id, version)`` on ``prompt_versions`` so the
auto-increment ``v{count+1}`` path in ``prompt_service.record_prompt_version``
can no longer persist two rows with the same version label under concurrency.

The pre-existing non-unique composite index ``ix_prompt_versions_run_version``
is replaced by the unique constraint (a unique constraint is itself backed by an
index, so the "fetch a run's versions in order" access path is preserved).

Any duplicate ``(agent_run_id, version)`` rows already present (the exact bug
this migration closes) are made unique first by suffixing the row id, so the
constraint can be created without a hard failure or data loss.

Revision ID: e7a1c9d4b2f5
Revises: c4d2f1a9b7e3
Create Date: 2026-07-16 21:45:00.000000
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e7a1c9d4b2f5'
down_revision: Union[str, None] = 'c4d2f1a9b7e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Re-label existing duplicates (keeping the earliest row of each group intact) so
# the unique constraint can be added. Appending the unique row id guarantees a
# collision-free label. Portable across SQLite and PostgreSQL.
_DEDUP_SQL = """
UPDATE prompt_versions
SET version = version || '-dup-' || id
WHERE id NOT IN (
    SELECT MIN(id) FROM prompt_versions GROUP BY agent_run_id, version
)
"""


def upgrade() -> None:
    op.execute(_DEDUP_SQL)
    with op.batch_alter_table('prompt_versions', schema=None) as batch_op:
        batch_op.drop_index('ix_prompt_versions_run_version')
        batch_op.create_unique_constraint(
            'uq_prompt_versions_run_version', ['agent_run_id', 'version']
        )


def downgrade() -> None:
    with op.batch_alter_table('prompt_versions', schema=None) as batch_op:
        batch_op.drop_constraint('uq_prompt_versions_run_version', type_='unique')
        batch_op.create_index(
            'ix_prompt_versions_run_version', ['agent_run_id', 'version'], unique=False
        )
