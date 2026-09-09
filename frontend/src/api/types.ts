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

export type ConversationGraphTask = {
  id: string
  task_key: string
  status: string
  progress: number
  checkpoint: Record<string, unknown>
  error: string | null
}

export type ConversationGraphRun = Run & {
  snapshot_id: string
  tasks: ConversationGraphTask[]
}

export type ConversationGraphMessage = {
  id: string
  conversation_id: string
  external_id: string
  revision_id: string
  sender_id: string | null
  sender_name: string
  sent_at: string
  text: string
  text_hash: string
}

export type AnnotationReview = {
  id: string
  decision: 'confirmed' | 'disputed' | 'rejected'
  reviewer: string
  rationale?: string | null
}

export type ResponseCandidate = {
  id: string
  annotation_id: string
  source_message_id: string
  target_message_id: string
  source_revision_id: string
  target_revision_id: string
  method: string
  rank: number
  raw_score: number
  score_semantics: 'uncalibrated_similarity'
  proposal_eligible: boolean
  eligibility_reasons: string[]
  status: string
  review: AnnotationReview | null
}

export type DiscourseRelation = {
  id: string
  annotation_id: string
  source_message_id: string
  target_message_id: string
  source_revision_id: string
  target_revision_id: string
  relation_type: string
  method: string
  raw_score: number | null
  status: string
  review: AnnotationReview | null
}

export type ConversationGraph = {
  run: ConversationGraphRun
  messages: ConversationGraphMessage[]
  explicit_replies: Array<{
    source_message_id: string
    target_message_id: string
    relation_type: 'REPLIES_TO'
    source_native: true
    confidence: 1
  }>
  response_candidates: ResponseCandidate[]
  discourse_relations: DiscourseRelation[]
  page: { offset: number; limit: number }
  guardrail: string
}

export type ConversationGraphEvaluation = {
  status: string
  reply_ranking: Record<string, {
    reference_targets?: number
    hits?: number
    candidate_recall?: number | null
    mean_reciprocal_rank?: number | null
    coverage?: number | null
    comparable_sources?: number
    disagreements?: number
    rate?: number | null
  }>
  discourse: {
    reference_relations: number
    predicted_relations: number
    true_positive: number
    precision: number | null
    recall: number | null
    f1: number | null
    by_label: Record<string, unknown>
  }
  reference_judgments: Record<string, number>
  calibration: { ece: number | null; brier: number | null; reason: string }
}

export type LinguisticAnnotation = {
  id: string
  kind: string
  value: Record<string, unknown>
  evidence: Annotation['evidence']
  status: string
  raw_confidence: number | null
  calibrated_confidence: number | null
  alternatives: Array<{ value: Record<string, unknown> }>
  provenance: Record<string, unknown>
}

export type LinguisticAnalysis = {
  run: ConversationGraphRun
  message_id: string
  revision_id: string
  annotations: LinguisticAnnotation[]
  guardrail: string
}

export type ReasoningGraph = {
  run: ConversationGraphRun
  propositions: Array<{ id: string; text: string; type: string }>
  relations: Array<{
    id: string
    annotation_id: string
    source_proposition_id: string
    target_proposition_id: string
    relation_type: string
    method: string
    raw_score: number | null
    status: string
  }>
  argument_components: Array<{
    id: string
    proposition_id: string
    component_type: string
    status: string
    evidence: Annotation['evidence']
  }>
  relation_candidates: Array<{
    id: string
    source_proposition_id: string
    target_proposition_id: string
    accepted_relation: null
    proposal_eligible: boolean
    eligibility_reasons: string[]
    status: string
    evidence: Annotation['evidence']
  }>
  nli_challengers: Array<{
    id: string
    source_proposition_id: string
    target_proposition_id: string
    label: string
    scores: Record<string, number>
    truth_status: string
    status: string
    calibrated_confidence: number | null
  }>
  guardrail: string
}

export type SemanticStateArtifact = {
  artifact_id: string
  content_hash: string
  analysis_version: string
  corpus_id: string
  snapshot_id: string
  semantic_change: {
    status: string
    representation?: string
    terms: Array<{ term: string; average_pairwise_cosine_distance: number }>
  }
  topic_challengers: {
    models: Record<string, {
      status: string
      topic_count?: number
      reason?: string
      topics?: Array<{
        topic_id: number
        terms: string[]
        trajectory: Array<{ month: string; documents: number; share: number }>
      }>
    }>
    agreement: { adjusted_rand_index: number; interpretation: string } | null
  }
  change_points: {
    message_activity: Array<{ method: string; month: string; score: number }>
    topic_prevalence?: Record<string, Array<{
      topic_id: number
      candidates: Array<{ method: string; month: string; score: number }>
    }>>
  }
  conversation_states: {
    status: string
    states_are_unlabeled?: boolean
    sequence?: Array<{ month: string; state: string }>
    transition_matrix?: number[][]
    state_means_standardized?: number[][]
    features?: string[]
    reason?: string
  }
  guardrail: string
}

export type NetworkSequenceArtifact = {
  artifact_id: string
  content_hash: string
  hawkes: { status: string; method?: string; spectral_radius?: number; reason?: string }
  multilayer_communities: {
    layers: Record<string, { status: string; communities: Array<{ community_id: number; participants: Array<{ id: string; name: string }> }> }>
    dynamic_interaction: Array<{
      month: string
      status: string
      communities?: Array<{ community_id: number; participants: Array<{ id: string; name: string }> }>
      reason?: string
    }>
    knowledge_flow: { status: string; reason: string }
    stance?: { status: string; reason: string }
  }
  network_motifs: {
    status: string
    permutations: number
    motifs: Record<string, { observed: number; null_mean: number; null_sd: number }>
  }
  dialogue_sequences: {
    status: string
    transitions: Array<{ from: string; to: string; count: number }>
    frequent_patterns: Array<{ sequence: string[]; count: number }>
  }
  guardrail: string
}

export type StatisticalSynthesisArtifact = {
  artifact_id: string
  content_hash: string
  null_models: {
    status: string
    null?: string
    tests?: Array<{
      source_id: string
      target_id: string
      observed: number
      null_mean: number
      null_sd: number
      z_score: number | null
      one_sided_p: number
    }>
    reason?: string
  }
  hierarchical_reply_model: {
    status: string
    reason?: string
    sample_size?: number
    events?: number
    fixed_effects?: Record<string, { log_odds: number; odds_ratio: number }>
    participant_random_intercepts?: Record<string, number>
    conversation_random_intercepts?: Record<string, number>
    controls?: string[]
    uncertainty?: Record<string, string>
  }
  guardrail: string
}

export type ExperimentalDynamicsArtifact = {
  artifact_id: string
  content_hash: string
  semantic_information_dynamics: {
    status: string
    reason?: string | null
    representation?: string
    bias_warning?: string
    transfer_entropy?: Array<{
      source_id: string
      target_id: string
      transfer_entropy_bits: number
      one_sided_p: number
    }>
    partial_information?: Array<{
      left_source_id: string
      right_source_id: string
      target_id: string
      redundancy_bits: number
      unique_left_bits: number
      unique_right_bits: number
      synergy_bits: number
      estimator: string
    }>
  }
  linguistic_affect_dynamics: {
    status: string
    messages: number
    messages_with_nonzero_signal: number
    interpretation: string
    monthly_trajectory: Array<Record<string, number | string>>
  }
  guardrail: string
}

export type InteractionDynamicsArtifact = {
  run: { id: string; snapshot_id: string; status: string; progress: number; configuration: Record<string, unknown> }
  measurements: {
    'directional-coordination@0.1.0': {
      estimate: Array<{ initiator_id: string; responder_id: string; events: number; accommodation_delta: number; lower: number; upper: number }>
      sample_size: number
      denominator: number
      uncertainty: Record<string, unknown>
      missingness: Record<string, number>
      controls: string[]
    }
    'response-survival@0.1.0': {
      estimate: { median_minutes: number | null; survival_curve: Array<{ minutes: number; survival: number; at_risk: number; replies: number; censored: number }> }
      sample_size: number
      numerator: number
      denominator: number
      uncertainty: Record<string, unknown>
      missingness: Record<string, number>
      controls: string[]
    }
    'relational-event-choice@0.1.0': {
      estimate: { coefficients?: Record<string, number>; relative_choice_odds?: Record<string, number>; converged?: boolean }
      sample_size: number
      denominator: number
      uncertainty: Record<string, unknown>
      missingness: Record<string, number>
      controls: string[]
      causal_status: string
    }
  }
  guardrail: string
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
  task_completion?: Record<string, { completed: number; required: number }>
  double_annotation: {
    required: number
    completed: number
    fraction: number
  }
  agreement: {
    comparable_unit_kinds: number
    exact: number
    raw_rate: number | null
    by_task?: Record<string, { comparable: number; exact: number; raw_rate: number | null }>
    stage?: string
  }
  freeze_ready: boolean
  manifest_hash: string | null
  judgment_protocol?: string
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
  judgment_progress?: Record<string, { completed: number; required: number }>
}

export type GoldTaskJudgment = {
  id: string
  task: string
  slot: 'A' | 'B' | 'FINAL'
  stage: 'independent' | 'adjudicated'
  status: 'PRESENT' | 'ABSENT' | 'ABSTAIN' | 'NOT_ANNOTATED'
  annotator: string | null
  submitted_at: string | null
  annotations: Array<{
    id: string
    kind: string
    value: Record<string, unknown>
    evidence: Array<Record<string, unknown>>
    status: string
  }>
}

export type JudgmentAnnotationDraft = {
  draft_id: number
  kind: string
  value: Record<string, unknown>
  spans: Array<{ start_codepoint: number; end_codepoint: number }>
}

export type AnnotationUnitContext = {
  unit_id: string
  annotation_set_id: string
  split: 'train' | 'development' | 'test'
  strata: Record<string, unknown>
  slot: 'A' | 'B' | 'FINAL'
  blind: boolean
  anchor_message_id: string
  anchor_conversation_id: string
  anchor_revision_id: string
  episode_id: string | null
  episode_size: number
  context_policy: Record<string, unknown>
  messages: Array<{
    message_id: string
    sender_id: string | null
    sender_name: string
    sent_at: string
    text: string
    context_role: 'reply_target' | 'previous' | 'anchor' | 'next'
    labelable: boolean
  }>
  judgments: GoldTaskJudgment[]
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
