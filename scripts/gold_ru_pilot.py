from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from prometheus_observatory.annotation_workbench import AnnotationWorkbenchService
from prometheus_observatory.codebooks import register_codebooks
from prometheus_observatory.database import SessionLocal
from prometheus_observatory.models import AnnotationSet, Corpus, CorpusSnapshot
from sqlalchemy import select


def resolve_corpus(session, corpus_id: str | None) -> Corpus:
    corpus = (
        session.get(Corpus, corpus_id)
        if corpus_id
        else session.scalar(
            select(Corpus).where(Corpus.language == "ru").order_by(Corpus.created_at)
        )
    )
    if corpus is None:
        raise SystemExit("Russian corpus not found")
    return corpus


def create(
    corpus_id: str | None,
    target_size: int,
    name: str,
    double_annotation_fraction: float,
) -> dict:
    with SessionLocal() as session:
        register_codebooks(session)
        corpus = resolve_corpus(session, corpus_id)
        snapshot = session.scalar(
            select(CorpusSnapshot)
            .where(CorpusSnapshot.corpus_id == corpus.id)
            .order_by(CorpusSnapshot.created_at.desc(), CorpusSnapshot.id.desc())
        )
        if snapshot is None:
            raise SystemExit("Corpus has no snapshot")
        annotation_set = AnnotationWorkbenchService(session).create_set(
            corpus_id=corpus.id,
            snapshot_id=snapshot.id,
            name=name,
            target_size=target_size,
            codebook_key="foundational-conversation-ru",
            codebook_version="0.1.0",
            seed=name,
            double_annotation_fraction=double_annotation_fraction,
        )
        statistics = AnnotationWorkbenchService(session).statistics(annotation_set.id)
        return {
            "annotation_set_id": annotation_set.id,
            "corpus_id": corpus.id,
            "snapshot_id": snapshot.id,
            "requested_units": target_size,
            "sampled_units": statistics["total_units"],
            "splits": statistics["split_counts"],
            "double_annotation": statistics["double_annotation"],
            "status": annotation_set.status,
        }


def status(annotation_set_id: str) -> dict:
    with SessionLocal() as session:
        annotation_set = session.get(AnnotationSet, annotation_set_id)
        if annotation_set is None:
            raise SystemExit("Annotation set not found")
        service = AnnotationWorkbenchService(session)
        units: list[dict] = []
        cursor = -1
        while True:
            page = service.list_units(
                annotation_set_id, after_ordinal=cursor, limit=200
            )
            if not page:
                break
            units.extend(page)
            cursor = page[-1]["ordinal"]
        return {
            "annotation_set_id": annotation_set.id,
            "name": annotation_set.name,
            "status": annotation_set.status,
            "manifest_hash": annotation_set.manifest_hash,
            "units": len(units),
            "unit_statuses": dict(Counter(unit["status"] for unit in units)),
            "splits": dict(Counter(unit["split"] for unit in units)),
            "annotations": sum(len(unit["annotations"]) for unit in units),
        }


def export(annotation_set_id: str, output: Path) -> dict:
    with SessionLocal() as session:
        payload = AnnotationWorkbenchService(session).export(annotation_set_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "annotation_set_id": annotation_set_id,
        "manifest_hash": payload["manifest_hash"],
        "output": str(output),
        "units": len(payload["units"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage a Russian gold annotation set")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--corpus-id")
    create_parser.add_argument("--target-size", type=int, default=1200)
    create_parser.add_argument("--name", default="gold-ru-v1")
    create_parser.add_argument("--double-annotation-fraction", type=float, default=0.3)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("annotation_set_id")
    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("annotation_set_id")
    export_parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "create":
        result = create(
            arguments.corpus_id,
            arguments.target_size,
            arguments.name,
            arguments.double_annotation_fraction,
        )
    elif arguments.command == "status":
        result = status(arguments.annotation_set_id)
    else:
        result = export(arguments.annotation_set_id, arguments.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
