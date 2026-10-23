"""Add knowledge provenance and explicit runtime curriculum scope.

Revision ID: 0004
Revises: 0003

Existing nodes remain enabled. Catalogue-only supplemental knowledge can be
recorded without entering active learning contexts. Learner progress is untouched.
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "curriculum_chapters",
        sa.Column("reference_url", sa.String(length=500), nullable=True),
    )
    with op.batch_alter_table("knowledge_nodes") as batch_op:
        batch_op.add_column(sa.Column("reference_url", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("reference_section", sa.String(length=40), nullable=True))
        batch_op.add_column(
            sa.Column("is_supplementary", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(
            sa.Column("runtime_enabled", sa.Boolean(), server_default=sa.true(), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_nodes") as batch_op:
        batch_op.drop_column("runtime_enabled")
        batch_op.drop_column("is_supplementary")
        batch_op.drop_column("reference_section")
        batch_op.drop_column("reference_url")
    with op.batch_alter_table("curriculum_chapters") as batch_op:
        batch_op.drop_column("reference_url")
