"""add gold task judgments

Revision ID: 7b2c4d9e1a10
Revises: 0afb97092513
Create Date: 2026-09-07 10:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7b2c4d9e1a10"
down_revision: str | None = "0afb97092513"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gold_task_judgments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("annotation_set_id", sa.String(length=36), nullable=False),
        sa.Column("unit_id", sa.String(length=36), nullable=False),
        sa.Column("task", sa.String(length=80), nullable=False),
        sa.Column("slot", sa.String(length=16), nullable=False),
        sa.Column("stage", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("annotator", sa.String(length=240), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["annotation_set_id"], ["annotation_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unit_id"], ["annotation_units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("unit_id", "task", "slot", name="uq_gold_judgment_unit_task_slot"),
    )
    for column in ("annotation_set_id", "unit_id", "task", "slot", "stage", "status", "annotator"):
        op.create_index(
            op.f(f"ix_gold_task_judgments_{column}"),
            "gold_task_judgments",
            [column],
            unique=False,
        )
    op.create_table(
        "gold_judgment_annotations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("judgment_id", sa.String(length=36), nullable=False),
        sa.Column("annotation_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["annotation_id"], ["annotations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["judgment_id"], ["gold_task_judgments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("judgment_id", "annotation_id", name="uq_gold_judgment_annotation"),
    )
    op.create_index(
        op.f("ix_gold_judgment_annotations_annotation_id"),
        "gold_judgment_annotations",
        ["annotation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_gold_judgment_annotations_judgment_id"),
        "gold_judgment_annotations",
        ["judgment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_gold_judgment_annotations_judgment_id"),
        table_name="gold_judgment_annotations",
    )
    op.drop_index(
        op.f("ix_gold_judgment_annotations_annotation_id"),
        table_name="gold_judgment_annotations",
    )
    op.drop_table("gold_judgment_annotations")
    for column in reversed(
        ("annotation_set_id", "unit_id", "task", "slot", "stage", "status", "annotator")
    ):
        op.drop_index(
            op.f(f"ix_gold_task_judgments_{column}"),
            table_name="gold_task_judgments",
        )
    op.drop_table("gold_task_judgments")
