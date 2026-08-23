# ruff: noqa: E501 - generated-style migration; formatting is not hand-managed
"""add ix_searches_created_at for retention cleanup

Revision ID: c7d2e94a1b58
Revises: 2fa1ed115369
Create Date: 2026-08-23 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c7d2e94a1b58'
down_revision: str | Sequence[str] | None = '2fa1ed115369'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # M15.1: retention cleanup scans searches.created_at; without this index
    # every purge would be a sequential scan. Additive and safe on the live
    # production table (~108 rows today).
    op.create_index(
        op.f('ix_searches_created_at'),
        'searches',
        ['created_at'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_searches_created_at'), table_name='searches')
