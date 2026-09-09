import type {
  AnnotationSet,
  AnnotationSetStatistics,
  AnnotationUnit,
  AnnotationUnitContext,
  Corpus,
  ConversationGraph,
  ConversationGraphRun,
  ConversationGraphEvaluation,
  LinguisticAnalysis,
  ReasoningGraph,
  SemanticStateArtifact,
  NetworkSequenceArtifact,
  StatisticalSynthesisArtifact,
  ExperimentalDynamicsArtifact,
  InteractionDynamicsArtifact,
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

export function createConversationGraphRun(
  corpusId: string,
  includeEncoder = true,
): Promise<ConversationGraphRun> {
  return request(`/api/corpora/${corpusId}/conversation-graph-runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      include_encoder: includeEncoder,
      execute: true,
      candidate_limit: 40,
      result_limit: 5,
    }),
  })
}

export function fetchConversationGraph(
  corpusId: string,
  messageId?: string,
): Promise<ConversationGraph> {
  const query = new URLSearchParams({ limit: '250' })
  if (messageId) query.set('message_id', messageId)
  return request(`/api/corpora/${corpusId}/conversation-graph?${query}`)
}

export function cancelConversationGraphRun(runId: string): Promise<ConversationGraphRun> {
  return request(`/api/conversation-graph-runs/${runId}/cancel`, { method: 'POST' })
}

export function resumeConversationGraphRun(runId: string): Promise<ConversationGraphRun> {
  return request(`/api/conversation-graph-runs/${runId}/resume`, { method: 'POST' })
}

export function createConversationGraphReference(corpusId: string): Promise<AnnotationSet> {
  return request(`/api/corpora/${corpusId}/conversation-graph-reference`, { method: 'POST' })
}

export function fetchConversationGraphEvaluation(
  annotationSetId: string,
  runId: string,
): Promise<ConversationGraphEvaluation> {
  const query = new URLSearchParams({ run_id: runId })
  return request(`/api/annotation-sets/${annotationSetId}/conversation-graph-evaluation?${query}`)
}

export function fetchConversationMessages(
  corpusId: string,
  conversationId: string,
  query = '',
  beforeMessageId?: string,
): Promise<{ items: Array<{
  message_id: string
  revision_id: string
  external_id: string
  sender_id: string | null
  sender_name: string
  sent_at: string
  text: string
  text_hash: string
}> }> {
  const params = new URLSearchParams({ q: query, limit: '500' })
  if (beforeMessageId) params.set('before_message_id', beforeMessageId)
  return request(
    `/api/corpora/${corpusId}/conversations/${conversationId}/messages?${params}`,
  )
}

export function createLinguisticRun(corpusId: string): Promise<ConversationGraphRun> {
  return request(`/api/corpora/${corpusId}/linguistic-runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ include_local_parser: true, execute: true }),
  })
}

export function fetchMessageLinguistics(
  corpusId: string,
  messageId: string,
): Promise<LinguisticAnalysis> {
  return request(`/api/corpora/${corpusId}/messages/${messageId}/linguistics`)
}

export function createReasoningRun(corpusId: string): Promise<ConversationGraphRun> {
  return request(`/api/corpora/${corpusId}/reasoning-runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ include_nli: true }),
  })
}

export function fetchReasoningGraph(corpusId: string): Promise<ReasoningGraph> {
  return request(`/api/corpora/${corpusId}/reasoning-graph`)
}

export function fetchSemanticState(corpusId: string): Promise<SemanticStateArtifact> {
  return request(`/api/corpora/${corpusId}/semantic-state`)
}

export function buildSemanticState(corpusId: string): Promise<SemanticStateArtifact> {
  return request(`/api/corpora/${corpusId}/semantic-state`, { method: 'POST' })
}

export function fetchNetworkSequence(corpusId: string): Promise<NetworkSequenceArtifact> {
  return request(`/api/corpora/${corpusId}/network-sequence`)
}

export function buildNetworkSequence(corpusId: string): Promise<NetworkSequenceArtifact> {
  return request(`/api/corpora/${corpusId}/network-sequence`, { method: 'POST' })
}

export function fetchStatisticalSynthesis(corpusId: string): Promise<StatisticalSynthesisArtifact> {
  return request(`/api/corpora/${corpusId}/statistical-synthesis`)
}

export function buildStatisticalSynthesis(corpusId: string): Promise<StatisticalSynthesisArtifact> {
  return request(`/api/corpora/${corpusId}/statistical-synthesis`, { method: 'POST' })
}

export function fetchExperimentalDynamics(corpusId: string): Promise<ExperimentalDynamicsArtifact> {
  return request(`/api/corpora/${corpusId}/experimental-dynamics`)
}

export function buildExperimentalDynamics(corpusId: string): Promise<ExperimentalDynamicsArtifact> {
  return request(`/api/corpora/${corpusId}/experimental-dynamics`, { method: 'POST' })
}

export function fetchInteractionDynamics(corpusId: string): Promise<InteractionDynamicsArtifact> {
  return request(`/api/corpora/${corpusId}/interaction-dynamics`)
}

export function buildInteractionDynamics(corpusId: string): Promise<InteractionDynamicsArtifact> {
  return request(`/api/corpora/${corpusId}/interaction-dynamics`, { method: 'POST' })
}
