"""add conversation graph analysis

Revision ID: c81f74d9a2e3
Revises: 7b2c4d9e1a10
Create Date: 2026-09-08 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c81f74d9a2e3"
down_revision: str | None = "7b2c4d9e1a10"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("response_relations") as batch:
        batch.add_column(sa.Column("snapshot_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("run_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("source_revision_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("target_revision_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column(
                "scoring_method", sa.String(length=80), nullable=False, server_default="legacy"
            )
        )
        batch.add_column(sa.Column("rank", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("status", sa.String(length=24), nullable=False, server_default="provisional")
        )
        batch.create_foreign_key(
            "fk_response_relations_snapshot_id",
            "corpus_snapshots",
            ["snapshot_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_response_relations_run_id", "analysis_runs", ["run_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_foreign_key(
            "fk_response_relations_source_revision_id",
            "message_revisions",
            ["source_revision_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_response_relations_target_revision_id",
            "message_revisions",
            ["target_revision_id"],
            ["id"],
        )
        batch.create_unique_constraint(
            "uq_response_candidate_run_source_target_method",
            ["run_id", "source_message_id", "target_message_id", "scoring_method"],
        )
    for column in ("snapshot_id", "run_id", "source_revision_id", "target_revision_id"):
        op.create_index(op.f(f"ix_response_relations_{column}"), "response_relations", [column])

    op.create_table(
        "discourse_relations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("source_message_id", sa.String(length=36), nullable=False),
        sa.Column("target_message_id", sa.String(length=36), nullable=False),
        sa.Column("source_revision_id", sa.String(length=36), nullable=False),
        sa.Column("target_revision_id", sa.String(length=36), nullable=False),
        sa.Column("relation_type", sa.String(length=40), nullable=False),
        sa.Column("annotation_id", sa.String(length=36), nullable=False),
        sa.Column("scoring_method", sa.String(length=80), nullable=False),
        sa.Column("raw_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["annotation_id"], ["annotations.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["corpus_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["source_revision_id"], ["message_revisions.id"]),
        sa.ForeignKeyConstraint(["target_message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["target_revision_id"], ["message_revisions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "source_message_id",
            "target_message_id",
            "relation_type",
            "scoring_method",
            name="uq_discourse_relation_run_endpoints_type_method",
        ),
    )
    for column in (
        "snapshot_id",
        "run_id",
        "source_message_id",
        "target_message_id",
        "source_revision_id",
        "target_revision_id",
        "relation_type",
        "annotation_id",
    ):
        op.create_index(op.f(f"ix_discourse_relations_{column}"), "discourse_relations", [column])

    op.create_table(
        "message_features",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("message_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("feature_type", sa.String(length=80), nullable=False),
        sa.Column("producer_hash", sa.String(length=64), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["revision_id"], ["message_revisions.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["corpus_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id",
            "revision_id",
            "feature_type",
            "producer_hash",
            name="uq_message_feature_snapshot_revision_producer",
        ),
    )
    for column in (
        "snapshot_id",
        "run_id",
        "message_id",
        "revision_id",
        "feature_type",
        "producer_hash",
    ):
        op.create_index(op.f(f"ix_message_features_{column}"), "message_features", [column])


def downgrade() -> None:
    op.drop_table("message_features")
    op.drop_table("discourse_relations")
    for column in ("target_revision_id", "source_revision_id", "run_id", "snapshot_id"):
        op.drop_index(op.f(f"ix_response_relations_{column}"), table_name="response_relations")
    with op.batch_alter_table("response_relations") as batch:
        batch.drop_constraint("uq_response_candidate_run_source_target_method", type_="unique")
        for constraint in (
            "fk_response_relations_target_revision_id",
            "fk_response_relations_source_revision_id",
            "fk_response_relations_run_id",
            "fk_response_relations_snapshot_id",
        ):
            batch.drop_constraint(constraint, type_="foreignkey")
        for column in (
            "status",
            "rank",
            "scoring_method",
            "target_revision_id",
            "source_revision_id",
            "run_id",
            "snapshot_id",
        ):
            batch.drop_column(column)
