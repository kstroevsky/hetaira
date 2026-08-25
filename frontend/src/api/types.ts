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
