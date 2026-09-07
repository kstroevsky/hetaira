from __future__ import annotations

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .analyzer import DeterministicAnalyzer
from .annotation_workbench import AnnotationWorkbenchService
from .config import get_settings
from .database import get_session
from .episode_microscope import EpisodeMicroscopeService
from .evaluation import evaluate_frozen_set
from .identity import ParticipantIdentityService
from .importers import ImportService
from .models import (
    AnalysisRun,
    AnnotationSet,
    CodebookArtifact,
    CodebookRelease,
    Corpus,
    ImportRun,
)
from .object_store import ContentAddressedStore
from .observatory import ObservatoryBuilder
from .ontology import PrivacyPolicy
from .research_planner import AnalysisPlan, BoundedPlannerRuntime
from .retrieval import HybridRetriever
from .schemas import (
    AnnotationReviewCreate,
    AnnotationSetCreate,
    AnnotationSetRead,
    CorpusCreate,
    CorpusRead,
    ImportResult,
    ImportRunRead,
    ManualAnnotationCreate,
    MessageListItem,
    MicroscopeResponse,
    RunRead,
    WorkspaceResponse,
)
from .workspace import WorkspaceService

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "prometheus-observatory", "version": "0.1.0"}


@router.get("/corpora", response_model=list[CorpusRead])
def list_corpora(session: Session = Depends(get_session)) -> list[Corpus]:
    return list(session.scalars(select(Corpus).order_by(Corpus.created_at)))


@router.post("/corpora", response_model=CorpusRead, status_code=201)
def create_corpus(payload: CorpusCreate, session: Session = Depends(get_session)) -> Corpus:
    corpus = Corpus(**payload.model_dump(mode="json"))
    session.add(corpus)
    session.commit()
    return corpus


@router.post("/corpora/{corpus_id}/imports/{platform}", response_model=ImportResult)
def import_corpus(
    corpus_id: str,
    platform: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> ImportResult:
    if platform not in {"telegram", "telegram_html", "whatsapp"}:
        raise HTTPException(400, "platform must be telegram, telegram_html, or whatsapp")
    corpus = session.get(Corpus, corpus_id)
    if corpus is None:
        raise HTTPException(404, "corpus not found")
    settings = get_settings()
    stored = ContentAddressedStore(settings.object_store).put_stream(file.file)
    try:
        return ImportService(session).import_object(
            corpus,
            stored,
            file.filename or f"{platform}-export",
            file.content_type or "application/octet-stream",
            platform,
        )
    except (ValueError, KeyError) as error:
        session.rollback()
        raise HTTPException(422, str(error)) from error


@router.get("/corpora/{corpus_id}/imports", response_model=list[ImportRunRead])
def list_imports(corpus_id: str, session: Session = Depends(get_session)) -> list[ImportRun]:
    if session.get(Corpus, corpus_id) is None:
        raise HTTPException(404, "corpus not found")
    return list(
        session.scalars(
            select(ImportRun)
            .where(ImportRun.corpus_id == corpus_id)
            .order_by(ImportRun.created_at.desc())
        )
    )


@router.post("/imports/{import_run_id}/resume", response_model=ImportResult)
def resume_import(import_run_id: str, session: Session = Depends(get_session)) -> ImportResult:
    try:
        return ImportService(session).resume_import(import_run_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        raise HTTPException(422, str(error)) from error


@router.post("/corpora/{corpus_id}/analyze", response_model=RunRead)
def analyze_corpus(corpus_id: str, session: Session = Depends(get_session)) -> AnalysisRun:
    try:
        return DeterministicAnalyzer(session).analyze(corpus_id)
    except (LookupError, ValueError) as error:
        session.rollback()
        raise HTTPException(404 if isinstance(error, LookupError) else 422, str(error)) from error


@router.get("/corpora/{corpus_id}/observatory")
def get_observatory(corpus_id: str, session: Session = Depends(get_session)) -> dict:
    if session.get(Corpus, corpus_id) is None:
        raise HTTPException(404, "corpus not found")
    artifact = ObservatoryBuilder(session).latest(corpus_id)
    if artifact is None:
        raise HTTPException(404, "observatory overview has not been built")
    return {
        "artifact_id": artifact.id,
        "content_hash": artifact.content_hash,
        "run_id": artifact.run_id,
        **artifact.payload,
    }


@router.post("/corpora/{corpus_id}/observatory", status_code=201)
def build_observatory(corpus_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        artifact = ObservatoryBuilder(session).build(corpus_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {
        "artifact_id": artifact.id,
        "content_hash": artifact.content_hash,
        "run_id": artifact.run_id,
        **artifact.payload,
    }


@router.get("/participants/{participant_id}/identity")
def get_participant_identity(
    participant_id: str,
    session: Session = Depends(get_session),
) -> dict:
    try:
        return ParticipantIdentityService(session).profile(participant_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/corpora/{corpus_id}/episode-microscope")
def get_episode_microscope(
    corpus_id: str,
    message_id: str,
    session: Session = Depends(get_session),
) -> dict:
    try:
        return EpisodeMicroscopeService(session).inspect(corpus_id, message_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/corpora/{corpus_id}/messages", response_model=list[MessageListItem])
def list_messages(corpus_id: str, session: Session = Depends(get_session)) -> list[MessageListItem]:
    return WorkspaceService(session).messages(corpus_id)


@router.get("/corpora/{corpus_id}/search")
def search_corpus(
    corpus_id: str,
    q: str,
    limit: int = 20,
    participant_id: str | None = None,
    snapshot_id: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    if session.get(Corpus, corpus_id) is None:
        raise HTTPException(404, "corpus not found")
    try:
        trace, hits = HybridRetriever(session).search(
            corpus_id,
            q,
            limit=min(max(limit, 1), 100),
            participant_id=participant_id,
            snapshot_id=snapshot_id,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {
        "trace_id": trace.id,
        "coverage": trace.coverage,
        "hits": [hit.as_dict() for hit in hits],
    }


@router.get("/messages/{message_id}/microscope", response_model=MicroscopeResponse)
def get_microscope(message_id: str, session: Session = Depends(get_session)) -> MicroscopeResponse:
    try:
        return WorkspaceService(session).microscope(message_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/workspace", response_model=WorkspaceResponse)
def get_workspace(
    corpus_id: str | None = None, session: Session = Depends(get_session)
) -> WorkspaceResponse:
    try:
        return WorkspaceService(session).workspace(corpus_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/runs", response_model=list[RunRead])
def list_runs(session: Session = Depends(get_session)) -> list[AnalysisRun]:
    return list(session.scalars(select(AnalysisRun).order_by(AnalysisRun.created_at.desc())))


@router.get("/codebooks")
def list_codebooks(session: Session = Depends(get_session)) -> list[dict]:
    releases = session.execute(
        select(CodebookRelease, CodebookArtifact)
        .join(CodebookArtifact, CodebookArtifact.content_hash == CodebookRelease.artifact_hash)
        .order_by(CodebookRelease.language, CodebookRelease.codebook_key)
    ).all()
    return [
        {
            "id": release.id,
            "key": release.codebook_key,
            "version": release.semantic_version,
            "language": release.language,
            "validated": release.validated,
            "content_hash": release.artifact_hash,
            "content": yaml.safe_load(artifact.content),
        }
        for release, artifact in releases
    ]


@router.get("/codebooks/{codebook_key}/compare")
def compare_codebooks(
    codebook_key: str,
    left: str,
    right: str,
    session: Session = Depends(get_session),
) -> dict:
    releases = session.execute(
        select(CodebookRelease, CodebookArtifact)
        .join(CodebookArtifact, CodebookArtifact.content_hash == CodebookRelease.artifact_hash)
        .where(
            CodebookRelease.codebook_key == codebook_key,
            CodebookRelease.semantic_version.in_([left, right]),
        )
    ).all()
    by_version = {
        release.semantic_version: (release, yaml.safe_load(artifact.content))
        for release, artifact in releases
    }
    if left not in by_version or right not in by_version:
        raise HTTPException(404, "one or both codebook releases were not found")
    left_release, left_content = by_version[left]
    right_release, right_content = by_version[right]
    left_labels = left_content.get("labels", {})
    right_labels = right_content.get("labels", {})
    dimensions = sorted(set(left_labels) | set(right_labels))
    changes = []
    for dimension in dimensions:
        before = left_labels.get(dimension, {})
        after = right_labels.get(dimension, {})
        changes.append(
            {
                "dimension": dimension,
                "added": sorted(set(after) - set(before)),
                "removed": sorted(set(before) - set(after)),
                "changed": sorted(
                    label for label in set(before) & set(after) if before[label] != after[label]
                ),
            }
        )
    return {
        "codebook_key": codebook_key,
        "left": {"version": left, "artifact_hash": left_release.artifact_hash},
        "right": {"version": right, "artifact_hash": right_release.artifact_hash},
        "changes": changes,
    }


@router.post("/annotation-sets", response_model=AnnotationSetRead, status_code=201)
def create_annotation_set(
    payload: AnnotationSetCreate, session: Session = Depends(get_session)
) -> AnnotationSet:
    try:
        return AnnotationWorkbenchService(session).create_set(**payload.model_dump())
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/corpora/{corpus_id}/annotation-sets", response_model=list[AnnotationSetRead])
def list_annotation_sets(
    corpus_id: str, session: Session = Depends(get_session)
) -> list[AnnotationSet]:
    return list(
        session.scalars(
            select(AnnotationSet)
            .where(AnnotationSet.corpus_id == corpus_id)
            .order_by(AnnotationSet.created_at.desc())
        )
    )


@router.get("/annotation-sets/{annotation_set_id}/units")
def list_annotation_units(
    annotation_set_id: str,
    after_ordinal: int = -1,
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    try:
        units = AnnotationWorkbenchService(session).list_units(
            annotation_set_id, after_ordinal=after_ordinal, limit=limit
        )
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    return {"items": units, "next_ordinal": units[-1]["ordinal"] if units else None}


@router.get("/annotation-sets/{annotation_set_id}/statistics")
def annotation_set_statistics(
    annotation_set_id: str,
    session: Session = Depends(get_session),
) -> dict:
    try:
        return AnnotationWorkbenchService(session).statistics(annotation_set_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.post("/annotation-units/{unit_id}/annotations")
def add_manual_annotation(
    unit_id: str,
    payload: ManualAnnotationCreate,
    session: Session = Depends(get_session),
) -> dict:
    try:
        annotation = AnnotationWorkbenchService(session).add_annotation(
            unit_id,
            kind=payload.kind,
            value=payload.value,
            spans=[span.model_dump() for span in payload.spans],
            annotator=payload.annotator,
            supersedes_annotation_id=payload.supersedes_annotation_id,
        )
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"id": annotation.id, "status": annotation.status}


@router.post("/annotations/{annotation_id}/reviews")
def review_annotation(
    annotation_id: str,
    payload: AnnotationReviewCreate,
    session: Session = Depends(get_session),
) -> dict:
    try:
        review = AnnotationWorkbenchService(session).review(
            annotation_id, decision=payload.decision, reviewer=payload.reviewer
        )
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"id": review.id, "decision": review.decision}


@router.post("/annotation-sets/{annotation_set_id}/freeze", response_model=AnnotationSetRead)
def freeze_annotation_set(
    annotation_set_id: str, session: Session = Depends(get_session)
) -> AnnotationSet:
    try:
        return AnnotationWorkbenchService(session).freeze(annotation_set_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/annotation-sets/{annotation_set_id}/export")
def export_annotation_set(annotation_set_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        return AnnotationWorkbenchService(session).export(annotation_set_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/annotation-sets/{annotation_set_id}/evaluations/{analysis_run_id}")
def evaluate_analysis_run(
    annotation_set_id: str,
    analysis_run_id: str,
    session: Session = Depends(get_session),
) -> dict:
    try:
        return evaluate_frozen_set(session, annotation_set_id, analysis_run_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/privacy/preview")
def privacy_preview(policy: PrivacyPolicy, evidence_count: int = 1) -> dict:
    return {
        "policy": policy,
        "allowed": policy != PrivacyPolicy.LOCAL_ONLY,
        "evidence_count": evidence_count,
        "requires_explicit_confirmation": policy != PrivacyPolicy.LOCAL_ONLY,
        "payload_scope": {
            PrivacyPolicy.LOCAL_ONLY: "none",
            PrivacyPolicy.API_PSEUDONYMIZED_MINIMAL: "minimal_pseudonymized_spans",
            PrivacyPolicy.API_RAW_EVIDENCE_ONLY: "minimal_raw_spans",
            PrivacyPolicy.API_SELECTED_EPISODE: "selected_episode",
        }[policy],
    }


@router.post("/research-plans/validate")
def validate_research_plan(plan: AnalysisPlan) -> dict:
    try:
        validated = BoundedPlannerRuntime().validate(plan)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"status": "valid", "plan": validated.model_dump(mode="json")}
