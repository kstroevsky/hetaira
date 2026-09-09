from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from prometheus_observatory.annotation_workbench import AnnotationWorkbenchService
from prometheus_observatory.conversation_graph import ConversationGraphService
from prometheus_observatory.importers import ImportService
from prometheus_observatory.model_gateway import (
    EmbeddingResult,
    EvidenceBundle,
    LocalOpenAICompatibleEmbeddingAdapter,
    ModelPolicy,
)
from prometheus_observatory.models import (
    AnalysisTask,
    Annotation,
    AnnotationReview,
    Conversation,
    Corpus,
    CorpusSnapshot,
    DiscourseRelation,
    Message,
    MessageFeature,
    MessageRevision,
    ResponseRelation,
    SnapshotMessageRevision,
)
from prometheus_observatory.object_store import ContentAddressedStore
from prometheus_observatory.text import text_hash

FIXTURE = Path(__file__).parent / "fixtures" / "telegram.json"


def imported_corpus(db_session: Session, tmp_path: Path) -> Corpus:
    corpus = Corpus(name="Граф диалога", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    with FIXTURE.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    ImportService(db_session).import_object(
        corpus, stored, FIXTURE.name, "application/json", "telegram"
    )
    return corpus


def test_corpus_graph_keeps_source_reply_and_provisional_rankings_separate(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = imported_corpus(db_session, tmp_path)

    run = ConversationGraphService(db_session).create(corpus.id, include_encoder=False)
    result = ConversationGraphService(db_session).graph(corpus.id, run_id=run.id)

    assert run.status == "completed"
    assert len(result["explicit_replies"]) == 1
    assert result["explicit_replies"][0]["relation_type"] == "REPLIES_TO"
    assert len(result["response_candidates"]) == 1
    candidate = result["response_candidates"][0]
    assert candidate["method"].startswith("lexical-cosine")
    assert candidate["score_semantics"] == "uncalibrated_similarity"
    assert candidate["status"] == "provisional"
    annotation = db_session.get(Annotation, candidate["annotation_id"])
    assert annotation is not None
    assert annotation.raw_confidence is None
    assert annotation.value["accepted_edge"] is False
    assert {item["revision_id"] for item in annotation.evidence}
    assert db_session.scalar(select(ResponseRelation).where(ResponseRelation.run_id == run.id))
    assert db_session.scalar(select(DiscourseRelation).where(DiscourseRelation.run_id == run.id))
    assert (
        ConversationGraphService(db_session).create(corpus.id, include_encoder=False).id == run.id
    )


def test_graph_run_can_cancel_before_execution_and_resume_idempotently(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = imported_corpus(db_session, tmp_path)
    service = ConversationGraphService(db_session)
    run = service.create(corpus.id, include_encoder=False, execute=False)

    assert service.cancel(run.id).status == "cancelled"
    resumed = service.resume(run.id)
    assert resumed.status == "completed"
    first_count = len(
        list(db_session.scalars(select(ResponseRelation).where(ResponseRelation.run_id == run.id)))
    )
    assert service.resume(run.id).status == "completed"
    assert (
        len(
            list(
                db_session.scalars(
                    select(ResponseRelation).where(ResponseRelation.run_id == run.id)
                )
            )
        )
        == first_count
    )
    assert all(
        task.status in {"completed", "disabled"}
        for task in db_session.scalars(select(AnalysisTask).where(AnalysisTask.run_id == run.id))
    )


def test_machine_graph_proposal_accepts_human_review_without_becoming_gold(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = imported_corpus(db_session, tmp_path)
    run = ConversationGraphService(db_session).create(corpus.id, include_encoder=False)
    annotation = db_session.scalar(
        select(Annotation).where(
            Annotation.run_id == run.id,
            Annotation.kind == "responds_to_candidates",
        )
    )
    assert annotation is not None

    review = AnnotationWorkbenchService(db_session).review(
        annotation.id, decision="confirmed", reviewer="human-reviewer"
    )

    assert isinstance(review, AnnotationReview)
    assert annotation.status == "provisional"


def test_conversation_graph_reference_uses_single_final_and_full_conversation_groups(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = imported_corpus(db_session, tmp_path)
    service = AnnotationWorkbenchService(db_session)
    annotation_set = service.create_conversation_graph_reference(corpus.id)
    units = service.list_units(annotation_set.id, limit=100)

    assert annotation_set.sampling_spec["judgment_protocol"] == "single_final_reference_v1"
    assert annotation_set.sampling_spec["required_tasks"] == [
        "reply_target",
        "discourse_relation",
    ]
    assert len({unit["group_id"] for unit in units}) == 1
    context = service.unit_context(units[0]["id"], "FINAL")
    assert {judgment["slot"] for judgment in context["judgments"]} == {"FINAL"}
    with pytest.raises(LookupError):
        service.submit_task_judgment(
            units[0]["id"],
            "reply_target",
            "A",
            status="ABSENT",
            annotator="human",
            annotations=[],
        )


def test_full_conversation_search_is_independent_of_candidate_horizon(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = imported_corpus(db_session, tmp_path)
    message = db_session.scalar(select(Message).where(Message.external_id == "2"))
    assert message is not None

    items = ConversationGraphService(db_session).search_conversation_messages(
        corpus.id, message.conversation_id, query="проверим"
    )

    assert [item["external_id"] for item in items] == ["1"]


def test_frozen_single_human_reference_reports_endpoint_metrics(
    db_session: Session, tmp_path: Path
) -> None:
    corpus = imported_corpus(db_session, tmp_path)
    graph_service = ConversationGraphService(db_session)
    run = graph_service.create(corpus.id, include_encoder=False)
    annotation_service = AnnotationWorkbenchService(db_session)
    annotation_set = annotation_service.create_conversation_graph_reference(corpus.id)
    units = annotation_service.list_units(annotation_set.id, limit=100)
    messages = {message.id: message for message in db_session.scalars(select(Message))}
    first = next(unit for unit in units if messages[unit["object_id"]].external_id == "1")
    second = next(unit for unit in units if messages[unit["object_id"]].external_id == "2")
    for task in ("reply_target", "discourse_relation"):
        annotation_service.submit_task_judgment(
            first["id"],
            task,
            "FINAL",
            status="ABSENT",
            annotator="single-human",
            annotations=[],
        )
    annotation_service.submit_task_judgment(
        second["id"],
        "reply_target",
        "FINAL",
        status="PRESENT",
        annotator="single-human",
        annotations=[
            {
                "kind": "reply_target",
                "value": {
                    "source_message_id": second["object_id"],
                    "target_message_id": first["object_id"],
                },
                "spans": [{"start_codepoint": 0, "end_codepoint": len(second["text"])}],
            }
        ],
    )
    annotation_service.submit_task_judgment(
        second["id"],
        "discourse_relation",
        "FINAL",
        status="PRESENT",
        annotator="single-human",
        annotations=[
            {
                "kind": "discourse_relation",
                "value": {
                    "source_message_id": second["object_id"],
                    "target_message_id": first["object_id"],
                    "relation_type": "ACCEPTS",
                },
                "spans": [{"start_codepoint": 0, "end_codepoint": len(second["text"])}],
            }
        ],
    )
    annotation_service.freeze(annotation_set.id)

    report = graph_service.evaluate_reference(annotation_set.id, run.id)

    assert report["status"] == "single_human_provisional"
    lexical = report["reply_ranking"]["lexical-cosine-ru@0.1.0"]
    assert lexical["candidate_recall"] == 1
    assert lexical["mean_reciprocal_rank"] == 1
    assert report["discourse"]["by_label"]["ACCEPTS"]["recall"] == 1
    assert report["calibration"]["ece"] is None


def test_graph_records_empty_and_missing_context_without_crossing_time_horizon(
    db_session: Session,
) -> None:
    corpus = Corpus(name="Границы", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.flush()
    conversation = Conversation(
        corpus_id=corpus.id,
        platform="telegram",
        source_namespace="boundary",
        external_id="boundary-chat",
        title="Границы",
    )
    db_session.add(conversation)
    db_session.flush()
    snapshot = CorpusSnapshot(
        corpus_id=corpus.id,
        source_hash="a" * 64,
        manifest_hash="b" * 64,
        message_count=4,
        label="boundary",
    )
    db_session.add(snapshot)
    db_session.flush()
    started = datetime(2025, 1, 1, 9, tzinfo=UTC)
    inputs = [
        ("1", started, "Привет 🙂", None),
        ("2", started + timedelta(hours=9), "", None),
        ("3", started + timedelta(hours=9, minutes=1), "Это ответ", "missing"),
        ("4", started + timedelta(hours=9, minutes=2), "Да 🙂", None),
    ]
    message_ids: dict[str, str] = {}
    for external_id, sent_at, text, reply_to in inputs:
        message = Message(
            conversation_id=conversation.id,
            external_id=external_id,
            sender_id=None,
            sent_at=sent_at,
            source_local_timestamp=sent_at.isoformat(),
            source_timezone_assumption="UTC",
            resolved_timestamp=sent_at,
            reply_to_external_id=reply_to,
        )
        db_session.add(message)
        db_session.flush()
        revision = MessageRevision(
            message_id=message.id,
            revision_number=1,
            text=text,
            text_hash=text_hash(text),
            language="ru",
        )
        db_session.add(revision)
        db_session.flush()
        db_session.add(
            SnapshotMessageRevision(
                snapshot_id=snapshot.id,
                message_id=message.id,
                revision_id=revision.id,
            )
        )
        message_ids[external_id] = message.id
    db_session.commit()

    service = ConversationGraphService(db_session)
    run = service.create(corpus.id, include_encoder=False)
    payload = service.run_payload(run.id)
    checkpoint = next(
        task["checkpoint"]
        for task in payload["tasks"]
        if task["task_key"] == "candidate_generation"
    )
    relations = list(
        db_session.scalars(select(ResponseRelation).where(ResponseRelation.run_id == run.id))
    )

    assert checkpoint["diagnostics"] == {
        "empty_source_messages": 1,
        "missing_explicit_targets": 1,
    }
    assert all(relation.target_message_id != message_ids["1"] for relation in relations)
    final_annotation = db_session.scalar(
        select(Annotation).where(
            Annotation.run_id == run.id,
            Annotation.object_id == message_ids["4"],
            Annotation.kind == "responds_to_candidates",
        )
    )
    assert final_annotation is not None
    assert final_annotation.evidence[0]["end_codepoint"] == len("Да 🙂")


def test_encoder_failure_preserves_completed_baseline(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = imported_corpus(db_session, tmp_path)
    service = ConversationGraphService(db_session)
    monkeypatch.setattr(service.settings, "local_embedding_base_url", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(service.settings, "local_embedding_revision", "pinned-test-revision")

    run = service.create(corpus.id, include_encoder=True)
    payload = service.run_payload(run.id)
    encoder = next(task for task in payload["tasks"] if task["task_key"] == "encoder_challenger")

    assert run.status == "completed"
    assert encoder["status"] == "failed"
    assert encoder["error"]
    assert db_session.scalar(
        select(ResponseRelation).where(
            ResponseRelation.run_id == run.id,
            ResponseRelation.scoring_method == "lexical-cosine-ru@0.1.0",
        )
    )


def test_local_encoder_challenger_caches_features_and_keeps_scores_uncalibrated(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = imported_corpus(db_session, tmp_path)
    service = ConversationGraphService(db_session)
    monkeypatch.setattr(service.settings, "local_embedding_base_url", "http://127.0.0.1:8080/v1")
    monkeypatch.setattr(service.settings, "local_embedding_revision", "pinned-test-revision")

    def embed(
        adapter: LocalOpenAICompatibleEmbeddingAdapter,
        bundle: EvidenceBundle,
        _policy: ModelPolicy,
    ) -> EmbeddingResult:
        items = bundle.items
        return EmbeddingResult(
            vectors=[[1.0, float(index + 1)] for index, _item in enumerate(items)],
            provider=adapter.provider,
            model=adapter.model,
            latency_ms=1,
            request_hash=bundle.request_hash(),
            truncated=[False] * len(items),
        )

    monkeypatch.setattr(LocalOpenAICompatibleEmbeddingAdapter, "embed", embed)

    run = service.create(corpus.id, include_encoder=True)
    payload = service.run_payload(run.id)
    encoder = next(task for task in payload["tasks"] if task["task_key"] == "encoder_challenger")
    graph = service.graph(corpus.id, run_id=run.id)

    assert encoder["status"] == "completed"
    assert db_session.scalar(select(MessageFeature).where(MessageFeature.run_id == run.id))
    encoder_candidates = [
        candidate
        for candidate in graph["response_candidates"]
        if candidate["method"] == "multilingual-e5-cosine@0.1.0"
    ]
    assert encoder_candidates
    assert all(
        candidate["score_semantics"] == "uncalibrated_similarity"
        for candidate in encoder_candidates
    )


def test_discourse_proposals_do_not_expand_across_all_ranked_candidates(
    db_session: Session, tmp_path: Path
) -> None:
    payload = {
        "id": "precision",
        "name": "Precision",
        "messages": [
            {
                "id": 1,
                "type": "message",
                "date": "2026-01-01T10:00:00+00:00",
                "from": "Анна",
                "from_id": "anna",
                "text": "Сервер и релиз.",
            },
            {
                "id": 2,
                "type": "message",
                "date": "2026-01-01T10:01:00+00:00",
                "from": "Борис",
                "from_id": "boris",
                "text": "Кофе и погода.",
            },
            {
                "id": 3,
                "type": "message",
                "date": "2026-01-01T10:02:00+00:00",
                "from": "Вера",
                "from_id": "vera",
                "text": "Согласна.",
            },
            {
                "id": 4,
                "type": "message",
                "date": "2026-01-01T10:03:00+00:00",
                "from": "Вера",
                "from_id": "vera",
                "reply_to_message_id": 1,
                "text": "Согласна, сервер и релиз.",
            },
        ],
    }
    path = tmp_path / "precision.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    corpus = Corpus(name="Precision", language="ru", privacy_policy="LOCAL_ONLY")
    db_session.add(corpus)
    db_session.commit()
    with path.open("rb") as source:
        stored = ContentAddressedStore(tmp_path / "objects").put_stream(source)
    ImportService(db_session).import_object(
        corpus, stored, path.name, "application/json", "telegram"
    )

    service = ConversationGraphService(db_session)
    run = service.create(corpus.id, include_encoder=False)
    messages = {message.external_id: message for message in db_session.scalars(select(Message))}
    inferred = service.graph(corpus.id, run_id=run.id)
    third_candidates = [
        item
        for item in inferred["response_candidates"]
        if item["source_message_id"] == messages["3"].id
    ]
    fourth_relations = list(
        db_session.scalars(
            select(DiscourseRelation).where(
                DiscourseRelation.run_id == run.id,
                DiscourseRelation.source_message_id == messages["4"].id,
            )
        )
    )

    assert len(third_candidates) == 2
    assert all(item["proposal_eligible"] is False for item in third_candidates)
    assert not db_session.scalar(
        select(DiscourseRelation).where(
            DiscourseRelation.run_id == run.id,
            DiscourseRelation.source_message_id == messages["3"].id,
        )
    )
    assert fourth_relations
    assert {item.target_message_id for item in fourth_relations} == {messages["1"].id}
