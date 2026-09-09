from __future__ import annotations

import argparse
import json
from pathlib import Path

from prometheus_observatory.database import SessionLocal
from prometheus_observatory.importers import ImportService
from prometheus_observatory.models import Corpus
from prometheus_observatory.object_store import ContentAddressedStore
from sqlalchemy import select


def import_export(directory: Path, corpus_name: str, object_root: Path) -> dict:
    if not directory.is_dir():
        raise SystemExit(f"Telegram export directory not found: {directory}")
    store = ContentAddressedStore(object_root)
    stored = store.put_directory(directory)
    with SessionLocal() as session:
        corpus = session.scalar(select(Corpus).where(Corpus.name == corpus_name))
        if corpus is None:
            corpus = Corpus(
                name=corpus_name,
                language="ru",
                source_type="telegram_html",
                privacy_policy="LOCAL_ONLY",
                is_validated_language=True,
            )
            session.add(corpus)
            # Assign the corpus ID without persisting an empty corpus if setup fails
            # before ImportService creates its resumable import run.
            session.flush()
        result = ImportService(session).import_object(
            corpus,
            stored,
            directory.name,
            "application/x-tar",
            "telegram_html",
        )
        return {
            "corpus_id": corpus.id,
            "corpus_name": corpus.name,
            "privacy_policy": corpus.privacy_policy,
            "import_run_id": result.import_run_id,
            "snapshot_id": result.snapshot_id,
            "source_hash": result.source_hash,
            "messages": result.imported_messages,
            "participants": result.imported_participants,
            "warnings": result.warnings,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import a Telegram HTML export locally"
    )
    parser.add_argument("directory", type=Path)
    parser.add_argument("--corpus-name", default="Psychedelic Renaissance 2.0")
    parser.add_argument("--object-root", type=Path, required=True)
    arguments = parser.parse_args()
    print(
        json.dumps(
            import_export(
                arguments.directory, arguments.corpus_name, arguments.object_root
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
