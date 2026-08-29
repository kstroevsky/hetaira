from __future__ import annotations

import argparse
import json
import resource
import time
import tracemalloc
from pathlib import Path

from generate_scale_fixture import generate
from prometheus_observatory.database import Base, SessionLocal, engine
from prometheus_observatory.importers.service import ImportInterrupted, ImportService
from prometheus_observatory.models import (
    Conversation,
    Corpus,
    ImportRun,
    Message,
    MessageRevision,
    SnapshotMessageRevision,
)
from prometheus_observatory.object_store import ContentAddressedStore
from sqlalchemy import func, select


def count_for_corpus(session, model, corpus_id: str) -> int:
    if model is Message:
        statement = (
            select(func.count())
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.corpus_id == corpus_id)
        )
    elif model is MessageRevision:
        statement = (
            select(func.count())
            .select_from(MessageRevision)
            .join(Message, Message.id == MessageRevision.message_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.corpus_id == corpus_id)
        )
    else:
        raise ValueError(f"unsupported count model: {model}")
    return session.scalar(statement) or 0


def run_gate(
    count: int, fixture: Path, object_root: Path, interrupt_after: int
) -> dict:
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
    if not fixture.exists():
        generate(count, fixture)
    tracemalloc.start()
    started = time.monotonic()
    with SessionLocal() as session:
        corpus = Corpus(
            name=f"Scale gate {count}",
            language="ru",
            source_type="telegram",
            privacy_policy="LOCAL_ONLY",
        )
        session.add(corpus)
        session.commit()
        corpus_id = corpus.id
        with fixture.open("rb") as source:
            stored = ContentAddressedStore(object_root).put_stream(source)
        try:
            ImportService(session).import_object(
                corpus,
                stored,
                fixture.name,
                "application/json",
                "telegram",
                interrupt_after=interrupt_after,
            )
        except ImportInterrupted as interruption:
            run_id = interruption.run_id
        else:
            raise AssertionError("scale gate did not exercise interruption")
    with SessionLocal() as session:
        interrupted = session.get(ImportRun, run_id)
        if interrupted is None or interrupted.processed_messages != interrupt_after:
            raise AssertionError(
                "durable checkpoint does not match interruption boundary"
            )
        result = ImportService(session).resume_import(run_id)
    elapsed = time.monotonic() - started
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    with SessionLocal() as session:
        messages = count_for_corpus(session, Message, corpus_id)
        revisions = count_for_corpus(session, MessageRevision, corpus_id)
        memberships = (
            session.scalar(
                select(func.count())
                .select_from(SnapshotMessageRevision)
                .where(SnapshotMessageRevision.snapshot_id == result.snapshot_id)
            )
            or 0
        )
        run = session.get(ImportRun, run_id)
        if run is None:
            raise AssertionError("import run disappeared")
        report = {
            "count": count,
            "messages": messages,
            "revisions": revisions,
            "memberships": memberships,
            "run_id": run_id,
            "snapshot_id": result.snapshot_id,
            "manifest_hash": run.checkpoint.get("manifest_hash"),
            "processed_messages": run.processed_messages,
            "status": run.status,
            "elapsed_seconds": round(elapsed, 3),
            "messages_per_second": round(count / elapsed, 2),
            "tracemalloc_current_bytes": current_bytes,
            "tracemalloc_peak_bytes": peak_bytes,
            "process_max_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
    expected = {messages, revisions, memberships, report["processed_messages"]}
    if expected != {count} or report["status"] != "completed":
        raise AssertionError(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the resumable bounded-memory import gate"
    )
    parser.add_argument("--count", type=int, default=1_000_000)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--object-root", type=Path, required=True)
    parser.add_argument("--interrupt-after", type=int)
    arguments = parser.parse_args()
    boundary = arguments.interrupt_after or max(1, arguments.count // 3)
    print(
        json.dumps(
            run_gate(
                arguments.count, arguments.fixture, arguments.object_root, boundary
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
