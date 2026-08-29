"""add resumable import checkpoints

Revision ID: d92ccbc76a6b
Revises: a0227985f3fc
Create Date: 2026-08-29 09:35:54.161880
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d92ccbc76a6b"
down_revision: str | None = "a0227985f3fc"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("import_runs") as batch:
        batch.add_column(sa.Column("original_name", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("media_type", sa.String(length=160), nullable=True))
        batch.add_column(sa.Column("object_path", sa.Text(), nullable=True))
        batch.add_column(sa.Column("size_bytes", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("conversation_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("parent_snapshot_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("snapshot_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("processed_messages", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("imported_participants", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("checkpoint", sa.JSON(), nullable=True))
    op.execute(
        "UPDATE import_runs SET "
        "snapshot_id = (SELECT id FROM corpus_snapshots "
        "WHERE corpus_snapshots.corpus_id = import_runs.corpus_id "
        "AND corpus_snapshots.source_hash = import_runs.source_hash "
        "ORDER BY corpus_snapshots.created_at DESC LIMIT 1)"
    )
    op.execute(
        "UPDATE import_runs SET "
        "original_name = COALESCE((SELECT original_name FROM source_artifacts "
        "WHERE source_artifacts.snapshot_id = import_runs.snapshot_id LIMIT 1), 'legacy-import'), "
        "media_type = COALESCE((SELECT media_type FROM source_artifacts "
        "WHERE source_artifacts.snapshot_id = import_runs.snapshot_id LIMIT 1), "
        "'application/octet-stream'), "
        "object_path = COALESCE((SELECT object_path FROM source_artifacts "
        "WHERE source_artifacts.snapshot_id = import_runs.snapshot_id LIMIT 1), ''), "
        "size_bytes = COALESCE((SELECT size_bytes FROM source_artifacts "
        "WHERE source_artifacts.snapshot_id = import_runs.snapshot_id LIMIT 1), 0), "
        "parent_snapshot_id = (SELECT parent_snapshot_id FROM corpus_snapshots "
        "WHERE corpus_snapshots.id = import_runs.snapshot_id), "
        "conversation_id = (SELECT id FROM conversations "
        "WHERE conversations.corpus_id = import_runs.corpus_id "
        "AND conversations.platform = import_runs.platform LIMIT 1), "
        "processed_messages = imported_messages + reused_messages, "
        "imported_participants = 0, checkpoint = '{}'"
    )
    with op.batch_alter_table("import_runs") as batch:
        batch.alter_column("original_name", nullable=False)
        batch.alter_column("media_type", nullable=False)
        batch.alter_column("object_path", nullable=False)
        batch.alter_column("size_bytes", nullable=False)
        batch.alter_column("processed_messages", nullable=False)
        batch.alter_column("imported_participants", nullable=False)
        batch.alter_column("checkpoint", nullable=False)
        batch.create_index("ix_import_runs_conversation_id", ["conversation_id"])
        batch.create_index("ix_import_runs_parent_snapshot_id", ["parent_snapshot_id"])
        batch.create_index("ix_import_runs_snapshot_id", ["snapshot_id"])
        batch.create_foreign_key(
            "fk_import_runs_conversation", "conversations", ["conversation_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_import_runs_parent_snapshot",
            "corpus_snapshots",
            ["parent_snapshot_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_import_runs_snapshot", "corpus_snapshots", ["snapshot_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("import_runs") as batch:
        batch.drop_constraint("fk_import_runs_snapshot", type_="foreignkey")
        batch.drop_constraint("fk_import_runs_parent_snapshot", type_="foreignkey")
        batch.drop_constraint("fk_import_runs_conversation", type_="foreignkey")
        batch.drop_index("ix_import_runs_snapshot_id")
        batch.drop_index("ix_import_runs_parent_snapshot_id")
        batch.drop_index("ix_import_runs_conversation_id")
        batch.drop_column("checkpoint")
        batch.drop_column("imported_participants")
        batch.drop_column("processed_messages")
        batch.drop_column("snapshot_id")
        batch.drop_column("parent_snapshot_id")
        batch.drop_column("conversation_id")
        batch.drop_column("size_bytes")
        batch.drop_column("object_path")
        batch.drop_column("media_type")
        batch.drop_column("original_name")
