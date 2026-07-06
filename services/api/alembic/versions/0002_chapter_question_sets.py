"""Add chapter-level adaptive question set plans.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "chapter_question_sets" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "chapter_question_sets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("chapter_id", sa.String(length=120), nullable=False),
        sa.Column("chapter_title", sa.String(length=200), nullable=False),
        sa.Column("target_question_count", sa.Integer(), nullable=False),
        sa.Column("learner_level", sa.String(length=30), nullable=False),
        sa.Column("average_mastery", sa.Float(), nullable=False),
        sa.Column("blueprint_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["learning_sessions.id"]),
        sa.UniqueConstraint("session_id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "chapter_question_sets" not in sa.inspect(bind).get_table_names():
        return
    op.drop_table("chapter_question_sets")
