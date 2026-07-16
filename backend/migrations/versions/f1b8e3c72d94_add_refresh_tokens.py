"""add refresh_tokens for rotating, revocable refresh tokens

Backs the v1.0 refresh-token hardening (M11): refresh tokens are no longer
purely stateless. Each issued token is recorded here with a unique ``jti`` and a
``family_id`` (one family per login) so it can be revoked on logout, password
change, or reuse detection, and rotated (single-use) on every refresh.

Revision ID: f1b8e3c72d94
Revises: e7a1c9d4b2f5
Create Date: 2026-07-17 01:20:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f1b8e3c72d94'
down_revision: Union[str, None] = 'e7a1c9d4b2f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'refresh_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('jti', sa.String(length=64), nullable=False),
        sa.Column('family_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('issued_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('refresh_tokens', schema=None) as batch_op:
        batch_op.create_index('ix_refresh_tokens_jti', ['jti'], unique=True)
        batch_op.create_index('ix_refresh_tokens_family_id', ['family_id'], unique=False)
        batch_op.create_index('ix_refresh_tokens_user_id', ['user_id'], unique=False)
        batch_op.create_index('ix_refresh_tokens_revoked', ['revoked'], unique=False)
        batch_op.create_index(
            'ix_refresh_tokens_user_revoked', ['user_id', 'revoked'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('refresh_tokens', schema=None) as batch_op:
        batch_op.drop_index('ix_refresh_tokens_user_revoked')
        batch_op.drop_index('ix_refresh_tokens_revoked')
        batch_op.drop_index('ix_refresh_tokens_user_id')
        batch_op.drop_index('ix_refresh_tokens_family_id')
        batch_op.drop_index('ix_refresh_tokens_jti')
    op.drop_table('refresh_tokens')
