"""add reasoning graph provenance

Revision ID: e16d203ab7c4
Revises: c81f74d9a2e3
Create Date: 2026-09-08 11:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e16d203ab7c4"
down_revision: str | None = "c81f74d9a2e3"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("proposition_relations") as batch:
        batch.add_column(sa.Column("snapshot_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("run_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column(
                "scoring_method", sa.String(length=80), nullable=False, server_default="legacy"
            )
        )
        batch.add_column(
            sa.Column("status", sa.String(length=24), nullable=False, server_default="provisional")
        )
        batch.create_foreign_key(
            "fk_proposition_relations_snapshot_id", "corpus_snapshots", ["snapshot_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_proposition_relations_run_id", "analysis_runs", ["run_id"], ["id"]
        )
    op.create_index(
        op.f("ix_proposition_relations_snapshot_id"), "proposition_relations", ["snapshot_id"]
    )
    op.create_index(op.f("ix_proposition_relations_run_id"), "proposition_relations", ["run_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_proposition_relations_run_id"), table_name="proposition_relations")
    op.drop_index(op.f("ix_proposition_relations_snapshot_id"), table_name="proposition_relations")
    with op.batch_alter_table("proposition_relations") as batch:
        batch.drop_constraint("fk_proposition_relations_run_id", type_="foreignkey")
        batch.drop_constraint("fk_proposition_relations_snapshot_id", type_="foreignkey")
        batch.drop_column("status")
        batch.drop_column("scoring_method")
        batch.drop_column("run_id")
        batch.drop_column("snapshot_id")
