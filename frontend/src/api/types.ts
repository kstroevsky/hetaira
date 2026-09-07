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

export type AnnotationSetStatistics = {
  annotation_set_id: string
  name: string
  status: string
  target_size: number
  total_units: number
  status_counts: Record<string, number>
  split_counts: Record<string, number>
  difficult_units: number
  confirmed_units: number
  coverage_by_kind: Record<string, number>
  double_annotation: {
    required: number
    completed: number
    fraction: number
  }
  agreement: {
    comparable_unit_kinds: number
    exact: number
    raw_rate: number | null
  }
  freeze_ready: boolean
  manifest_hash: string | null
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

export type SemanticThemeChange = {
  month: string
  direction: 'increase' | 'decrease'
  previous_share: number
  share: number
  share_delta: number
  robust_score: number
  persistence_months: number
}

export type SemanticTheme = {
  theme_id: number
  label: string
  terms: string[]
  episodes: number
  messages: number
  trajectory: Array<{ month: string; messages: number; share: number }>
  change_points: SemanticThemeChange[]
  top_participants: Array<{
    participant_id: string
    participant: string
    messages: number
    share: number
  }>
  representative_message_ids: string[]
}

export type ParticipantIdentityProfile = {
  participant_id: string
  corpus_id: string
  display_name: string
  message_count: number
  identities: Array<{
    platform: string
    source_namespace: string
    external_id: string
    display_name: string
  }>
  observed_names: Array<{ name: string; messages: number }>
  identity_basis: Array<{ basis: string; messages: number }>
  roster_aliases: Array<{
    external_id: string
    alias: string
    evidence_message_ids: string[]
  }>
  status: string
  guardrail: string
}

export type EpisodeMicroscope = {
  analysis_version: string
  status: string
  corpus_id: string
  snapshot_id: string
  window: {
    episode_id: string
    episode_title: string
    window_index: number
    message_limit: number
    selected_message_id: string
    message_count: number
    start_at: string | null
    end_at: string | null
  }
  messages: Array<{
    message_id: string
    external_id: string
    sender_id: string | null
    sender: string
    sent_at: string
    text: string
    reply_to_external_id: string | null
    selected: boolean
    ordinal: number
    dialogue_acts: string[]
    propositions: EpisodeProposition[]
    grounding: Array<EpisodeGrounding>
  }>
  propositions: EpisodeProposition[]
  stance_edges: Array<{
    source_message_id: string
    holder_id: string | null
    holder: string
    target_message_id: string
    target_proposition_id: string | null
    target_text: string | null
    position: 'SUPPORT' | 'OPPOSE' | 'ABSTAIN'
    resolution_status: string
    alternatives: Array<{ proposition_id: string; text: string }>
    confidence: number | null
    evidence: { object_type: string; object_id: string; exact_text: string }
  }>
  grounding_events: EpisodeGrounding[]
  agreement_structure: {
    support: number
    oppose: number
    abstain: number
    participant_positions: Array<{
      participant_id: string | null
      participant: string
      support: number
      oppose: number
      abstain: number
    }>
  }
  guardrail: string
}

export type EpisodeProposition = {
  proposition_id: string
  message_id: string
  holder_id: string | null
  holder: string
  text: string
  type: string
  evidence: {
    object_type: string
    object_id: string
    revision_id: string
    start_codepoint: number
    end_codepoint: number
    exact_text: string
  }
  status: string
}

export type EpisodeGrounding = {
  label: string
  holder_id: string | null
  message_id: string
  evidence: {
    object_type: string
    object_id: string
    revision_id: string
    start_codepoint: number
    end_codepoint: number
    exact_text: string
  }
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
      guardrail: string
    }
    semantic_themes?: {
      method: string
      status: string
      unit: string
      structural_episode_count: number
      window_message_limit: number
      episode_count: number
      cluster_count: number
      silhouette: number | null
      separation_quality: 'high' | 'moderate' | 'low' | 'unavailable'
      quality_note: string
      explained_variance: number | null
      themes: SemanticTheme[]
      change_events: Array<SemanticThemeChange & {
        theme_id: number
        theme_label: string
        representative_message_id: string | null
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
