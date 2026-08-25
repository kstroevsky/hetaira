from __future__ import annotations

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .analyzer import DeterministicAnalyzer
from .config import get_settings
from .database import get_session
from .importers import ImportService
from .models import AnalysisRun, CodebookArtifact, CodebookRelease, Corpus
from .object_store import ContentAddressedStore
from .ontology import PrivacyPolicy
from .research_planner import AnalysisPlan, BoundedPlannerRuntime
from .retrieval import HybridRetriever
from .schemas import (
    CorpusCreate,
    CorpusRead,
    ImportResult,
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
    if platform not in {"telegram", "whatsapp"}:
        raise HTTPException(400, "platform must be telegram or whatsapp")
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


@router.post("/corpora/{corpus_id}/analyze", response_model=RunRead)
def analyze_corpus(corpus_id: str, session: Session = Depends(get_session)) -> AnalysisRun:
    try:
        return DeterministicAnalyzer(session).analyze(corpus_id)
    except (LookupError, ValueError) as error:
        session.rollback()
        raise HTTPException(404 if isinstance(error, LookupError) else 422, str(error)) from error


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
