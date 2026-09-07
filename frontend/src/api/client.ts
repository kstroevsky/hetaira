import type {
  AnnotationSet,
  AnnotationSetStatistics,
  AnnotationUnit,
  AnnotationUnitContext,
  Corpus,
  Microscope,
  ObservatoryOverview,
  EpisodeMicroscope,
  ParticipantIdentityProfile,
  Workspace,
} from './types'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function fetchCorpora(): Promise<Corpus[]> {
  return request('/api/corpora')
}

export function fetchWorkspace(corpusId?: string): Promise<Workspace> {
  const suffix = corpusId ? `?corpus_id=${encodeURIComponent(corpusId)}` : ''
  return request(`/api/workspace${suffix}`)
}

export function fetchMicroscope(messageId: string): Promise<Microscope> {
  return request(`/api/messages/${messageId}/microscope`)
}

export function uploadExport(
  corpusId: string,
  platform: 'telegram' | 'whatsapp',
  file: File,
): Promise<{ imported_messages: number; warnings: string[] }> {
  const data = new FormData()
  data.append('file', file)
  return request(`/api/corpora/${corpusId}/imports/${platform}`, {
    method: 'POST',
    body: data,
  })
}

export function fetchAnnotationSets(corpusId: string): Promise<AnnotationSet[]> {
  return request(`/api/corpora/${corpusId}/annotation-sets`)
}

export function createReferencePilot(corpusId: string): Promise<AnnotationSet> {
  return request(`/api/corpora/${corpusId}/reference-pilot`, { method: 'POST' })
}

export function fetchAnnotationSetStatistics(
  annotationSetId: string,
): Promise<AnnotationSetStatistics> {
  return request(`/api/annotation-sets/${annotationSetId}/statistics`)
}

export function fetchAnnotationUnitContext(
  unitId: string,
  slot: 'A' | 'B' | 'FINAL',
): Promise<AnnotationUnitContext> {
  return request(`/api/annotation-units/${unitId}/context?slot=${slot}`)
}

export function submitTaskJudgment(
  unitId: string,
  task: string,
  slot: 'A' | 'B' | 'FINAL',
  payload: {
    status: 'PRESENT' | 'ABSENT' | 'ABSTAIN'
    annotator: string
    annotations: Array<{
      kind: string
      value: Record<string, unknown>
      spans: Array<{ start_codepoint: number; end_codepoint: number }>
    }>
  },
): Promise<{ id: string; task: string; slot: string; stage: string; status: string }> {
  return request(`/api/annotation-units/${unitId}/judgments/${task}/${slot}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function fetchAnnotationUnits(annotationSetId: string): Promise<AnnotationUnit[]> {
  const result = await request<{ items: AnnotationUnit[] }>(
    `/api/annotation-sets/${annotationSetId}/units?limit=200`,
  )
  return result.items
}

export function createManualAnnotation(
  unitId: string,
  payload: {
    kind: string
    value: Record<string, unknown>
    spans: Array<{ start_codepoint: number; end_codepoint: number }>
    annotator: string
    supersedes_annotation_id?: string
  },
): Promise<{ id: string; status: string }> {
  return request(`/api/annotation-units/${unitId}/annotations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function reviewManualAnnotation(
  annotationId: string,
  decision: 'confirmed' | 'disputed' | 'rejected',
  reviewer: string,
): Promise<{ id: string; decision: string }> {
  return request(`/api/annotations/${annotationId}/reviews`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, reviewer }),
  })
}

export function freezeAnnotationSet(annotationSetId: string): Promise<AnnotationSet> {
  return request(`/api/annotation-sets/${annotationSetId}/freeze`, { method: 'POST' })
}

export function fetchObservatory(corpusId: string): Promise<ObservatoryOverview> {
  return request(`/api/corpora/${corpusId}/observatory`)
}

export function buildObservatory(corpusId: string): Promise<ObservatoryOverview> {
  return request(`/api/corpora/${corpusId}/observatory`, { method: 'POST' })
}

export function fetchParticipantIdentity(
  participantId: string,
): Promise<ParticipantIdentityProfile> {
  return request(`/api/participants/${participantId}/identity`)
}

export function fetchEpisodeMicroscope(
  corpusId: string,
  messageId: string,
): Promise<EpisodeMicroscope> {
  const query = new URLSearchParams({ message_id: messageId })
  return request(`/api/corpora/${corpusId}/episode-microscope?${query}`)
}
