"""add_style_score_column

Revision ID: fa90999f935f
Revises: 0001
Create Date: 2026-06-13 22:59:19.928136
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = 'fa90999f935f'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add style_score column to reviews table
    op.add_column(
        'reviews',
        sa.Column('style_score', sa.Integer(), nullable=True),
    )

    # Add check constraint for style_score range (0-100)
    op.create_check_constraint(
        'ck_reviews_style_score',
        'reviews',
        'style_score >= 0 AND style_score <= 100',
    )


def downgrade() -> None:
    # Remove check constraint
    op.drop_constraint('ck_reviews_style_score', 'reviews', type_='check')

    # Remove style_score column
    op.drop_column('reviews', 'style_score')