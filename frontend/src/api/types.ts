export type Corpus = {
  id: string
  name: string
  language: string
  source_type: string
  privacy_policy: string
  is_validated_language: boolean
  created_at: string
}

export type MessageItem = {
  id: string
  external_id: string
  sender_id: string | null
  sender_name: string
  sender_initials: string
  sent_at: string
  text: string
  reply_count: number
  selected: boolean
}

export type Annotation = {
  id: string
  kind: string
  value: Record<string, unknown>
  evidence: Array<{
    object_type: string
    object_id: string
    revision_id?: string
    start_codepoint?: number
    end_codepoint?: number
    exact_text_hash?: string
  }>
  status: string
  raw_confidence: number | null
  calibrated_confidence: number | null
}

export type MicroscopeSection = {
  key: string
  title: string
  annotations: Annotation[]
}

export type EvidenceStage = {
  level: string
  title: string
  items: Array<Record<string, unknown>>
}

export type Microscope = {
  message: MessageItem
  revision_id: string
  text_hash: string
  sections: MicroscopeSection[]
  evidence_chain: EvidenceStage[]
  supporting_cases: Array<Record<string, unknown>>
  counterexamples: Array<Record<string, unknown>>
}

export type Run = {
  id: string
  run_type: string
  status: string
  progress: number
  configuration: Record<string, unknown>
  started_at: string | null
  completed_at: string | null
  error: string | null
}

export type Workspace = {
  corpus: Corpus
  messages: MessageItem[]
  selected_message_id: string
  microscope: Microscope
  run: Run | null
  overview: {
    message_count: number
    participant_count: number
    validated_language: boolean
    epistemic_levels: string[]
    snapshot_id: string
    snapshot_manifest_hash: string
  }
}

export type AnnotationSet = {
  id: string
  corpus_id: string
  snapshot_id: string
  name: string
  language: string
  codebook_key: string
  codebook_version: string
  codebook_artifact_hash: string
  status: string
  target_size: number
  sampling_spec: Record<string, unknown>
  manifest_hash: string | null
  frozen_at: string | null
  created_at: string
}

export type UnitAnnotation = {
  id: string
  kind: string
  value: Record<string, unknown>
  evidence: Array<Record<string, unknown>>
  role: string
  superseded_by: string | null
  review: {
    decision: string
    reviewer: string
    reviewed_at: string
  } | null
}

export type AnnotationUnit = {
  id: string
  ordinal: number
  object_type: string
  object_id: string
  revision_id: string
  group_id: string
  split: 'train' | 'development' | 'test'
  strata: Record<string, unknown>
  status: string
  sender_id: string | null
  sent_at: string
  text: string
  text_hash: string
  annotations: UnitAnnotation[]
}

export type ObservatoryFinding = {
  id: string
  dimension: string
  claim: string
  epistemic_level: string
  causal_status: string
  supporting_evidence: Array<{ object_type: string; object_id: string }>
  alternative_explanations: string[]
}

export type ObservatoryOverview = {
  artifact_id: string
  content_hash: string
  run_id: string
  schema: string
  analysis_version: string
  corpus: {
    id: string
    name: string
    language: string
    privacy_policy: string
  }
  snapshot: {
    id: string
    manifest_hash: string
    message_count: number
    created_at: string
  }
  dimensions: {
    source: Record<string, unknown>
    temporal: {
      monthly_activity: Array<{ month: string; messages: number }>
      busiest_month: { month: string; messages: number } | null
      change_points: Array<{
        month: string
        previous_messages: number
        messages: number
        robust_score: number
        direction: string
      }>
      change_method: string
      partial_month_warning: boolean
    }
    participation: {
      normalized_entropy: number
      gini: number
      top_1_share: number
      top_10_share: number
      top_participants: Array<{
        participant_id: string
        participant: string
        messages: number
        share: number
      }>
      interpretation_guardrail: string
    }
    reply_structure: Record<string, number | null>
    network: {
      participants: number
      directed_dyads: number
      interaction_communities: Array<{
        community_id: number
        size: number
        members: string[]
      }>
      top_nodes: Array<{
        participant_id: string
        participant: string
        pagerank: number
        betweenness: number
        degree: number
        messages: number
        replies_sent: number
        replies_received: number
      }>
      interpretation_guardrail: string
    }
    roles: {
      participant_profiles: Array<{
        participant_id: string
        participant: string
        profiles: string[]
        messages: number
        mean_message_characters: number
        question_rate: number
        reply_rate: number
        betweenness: number
        status: string
      }>
    }
    lexical_evolution: {
      method: string
      themes: Array<{
        theme_id: number
        terms: string[]
        document_frequency: number
      }>
      emerging_terms: Array<{
        term: string
        early_rate: number
        late_rate: number
        log_rate_ratio: number
        document_frequency: number
        sample_message_id: string | null
      }>
      declining_terms: Array<{
        term: string
        early_rate: number
        late_rate: number
        log_rate_ratio: number
        document_frequency: number
        sample_message_id: string | null
      }>
      guardrail: string
    }
    health_primitives: Record<string, unknown>
    data_quality: Record<string, unknown>
  }
  findings: ObservatoryFinding[]
  measurement_result_ids: Record<string, string>
  epistemic_status: string
  generated_at: string
}
