import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

const workspace = {
  corpus: {
    id: 'c1', name: 'Архив команды', language: 'ru', source_type: 'telegram',
    privacy_policy: 'LOCAL_ONLY', is_validated_language: true,
    created_at: '2025-01-01T00:00:00Z',
  },
  messages: [{
    id: 'm1', external_id: '1', sender_id: 'p1', sender_name: 'Иван',
    sender_initials: 'И', sent_at: '2025-01-01T09:00:00Z',
    text: 'Давайте проверим стенд.', reply_count: 0, selected: true,
  }],
  selected_message_id: 'm1',
  microscope: {
    message: {
      id: 'm1', external_id: '1', sender_id: 'p1', sender_name: 'Иван',
      sender_initials: 'И', sent_at: '2025-01-01T09:00:00Z',
      text: 'Давайте проверим стенд.', reply_count: 0, selected: true,
    },
    revision_id: 'r1', text_hash: 'abcdef123456', sections: [],
    evidence_chain: [], supporting_cases: [], counterexamples: [],
  },
  run: null,
  overview: {
    message_count: 1, participant_count: 1, validated_language: true,
    epistemic_levels: ['L0'],
    snapshot_id: 'snapshot-12345678',
    snapshot_manifest_hash: 'manifestabcdef123456',
  },
}

const observatory = {
  artifact_id: 'artifact-1', content_hash: 'a'.repeat(64), run_id: 'run-1',
  schema: 'hetaira.observatory-overview.v1', analysis_version: 'observatory-overview@1.4.2',
  corpus: { id: 'c1', name: 'Архив команды', language: 'ru', privacy_policy: 'LOCAL_ONLY' },
  snapshot: { id: 'snapshot-12345678', manifest_hash: 'manifestabcdef123456', message_count: 1, created_at: '2025-01-01T00:00:00Z' },
  dimensions: {
    source: { sessions_8h: 1, participants: 1, unresolved_sender_messages: 3 },
    temporal: { monthly_activity: [{ month: '2025-01', messages: 1 }], busiest_month: { month: '2025-01', messages: 1 }, change_points: [], change_method: 'test', partial_month_warning: true },
    participation: { normalized_entropy: 1, gini: 0, top_1_share: 1, top_10_share: 1, top_participants: [{ participant_id: 'p1', participant: 'Иван', messages: 1, share: 1 }], interpretation_guardrail: 'Не влияние.' },
    reply_structure: { resolved_reply_relations: 0, target_resolution_rate: 0, median_response_minutes: 0, p90_response_minutes: 0 },
    network: { participants: 1, directed_dyads: 0, interaction_communities: [], top_nodes: [], interpretation_guardrail: 'Не власть.' },
    roles: { participant_profiles: [] },
    lexical_evolution: { method: 'test', themes: [], guardrail: 'Навигация.' },
    semantic_themes: {
      method: 'test', status: 'provisional_semantic_navigation', unit: 'episode_window',
      structural_episode_count: 4, window_message_limit: 40, episode_count: 8,
      cluster_count: 2, silhouette: 0.61, separation_quality: 'high',
      quality_note: 'Темы хорошо разделены.', explained_variance: 0.72,
      themes: [
        {
          theme_id: 0, label: 'терапия · интеграция · поддержка',
          terms: ['терапия', 'интеграция', 'поддержка'], episodes: 4, messages: 20,
          trajectory: [
            { month: '2025-01', messages: 5, share: 0.1 },
            { month: '2025-02', messages: 15, share: 0.3 },
          ],
          change_points: [],
          top_participants: [{ participant_id: 'p1', participant: 'Иван', messages: 20, share: 1 }],
          representative_message_ids: ['m1'],
        },
        {
          theme_id: 1, label: 'рецептор · молекула · исследование',
          terms: ['рецептор', 'молекула', 'исследование'], episodes: 4, messages: 10,
          trajectory: [
            { month: '2025-01', messages: 8, share: 0.16 },
            { month: '2025-02', messages: 2, share: 0.04 },
          ],
          change_points: [], top_participants: [], representative_message_ids: ['m1'],
        },
      ],
      change_events: [], guardrail: 'Предварительные темы.',
    },
    health_primitives: { participation_balance: 1, reply_target_resolution: 0, dyadic_reciprocity: 0, median_response_minutes: 0, missing_dimensions: [] },
    data_quality: {},
  },
  findings: [], measurement_result_ids: {}, epistemic_status: 'descriptive_provisional', generated_at: '2025-01-01T00:00:00Z',
}

const identityProfile = {
  participant_id: 'p1', corpus_id: 'c1', display_name: 'Иван', message_count: 20,
  identities: [{ platform: 'telegram_html', source_namespace: 'test', external_id: 'user42', display_name: 'Иван' }],
  observed_names: [{ name: 'Иван', messages: 20 }],
  identity_basis: [{ basis: 'telegram_user_id', messages: 20 }],
  roster_aliases: [{ external_id: 'user42', alias: 'Иван Старый', evidence_message_ids: ['m1'] }],
  status: 'source_backed', guardrail: 'Псевдоним подтверждён источником.',
}

const episodeMicroscope = {
  analysis_version: 'episode-microscope-rules-ru@0.1.0', status: 'provisional_rules',
  corpus_id: 'c1', snapshot_id: 'snapshot-12345678',
  window: { episode_id: 'e1', episode_title: 'Эпизод 1', window_index: 0, message_limit: 40, selected_message_id: 'm1', message_count: 1, start_at: '2025-01-01T09:00:00Z', end_at: '2025-01-01T09:00:00Z' },
  messages: [{ message_id: 'm1', external_id: '1', sender_id: 'p1', sender: 'Иван', sent_at: '2025-01-01T09:00:00Z', text: 'Давайте проверим стенд.', reply_to_external_id: null, selected: true, ordinal: 0, dialogue_acts: ['PROPOSE'], propositions: [], grounding: [] }],
  propositions: [{ proposition_id: 'pr1', message_id: 'm1', holder_id: 'p1', holder: 'Иван', text: 'Давайте проверим стенд', type: 'proposal', evidence: { object_type: 'message', object_id: 'm1', revision_id: 'r1', start_codepoint: 0, end_codepoint: 23, exact_text: 'Давайте проверим стенд.' }, status: 'provisional_rules' }],
  stance_edges: [], grounding_events: [],
  agreement_structure: { support: 0, oppose: 0, abstain: 0, participant_positions: [] },
  guardrail: 'Предварительный разбор.',
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const data = url.includes('/episode-microscope')
      ? episodeMicroscope
      : url.includes('/participants/')
      ? identityProfile
      : url.includes('/observatory')
      ? observatory
      : url.includes('/annotation-sets')
      ? []
      : url.includes('/api/corpora')
      ? [workspace.corpus]
      : url.includes('/microscope')
        ? workspace.microscope
        : workspace
    return new Response(JSON.stringify(data), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }))
})

afterEach(() => cleanup())

describe('Prometheus workbench', () => {
  it('renders the evidence-first workspace', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>,
    )
    expect(await screen.findByLabelText('Многомерный обзор корпуса')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Что означает: Сообщения'))
    expect(screen.getByText(/Число сообщений и системных событий/)).toBeVisible()
    fireEvent.click(screen.getByLabelText('Что означает: Участники'))
    expect(screen.getByText(/не объединяются в вымышленного участника/)).toBeVisible()
    expect(screen.queryByText('Чаще в первой половине')).not.toBeInTheDocument()
    expect(screen.getByText('О чём говорили — и когда это менялось')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /рецептор · молекула/ }))
    expect(screen.getByRole('heading', { name: 'рецептор · молекула · исследование' })).toBeVisible()
    fireEvent.click(screen.getAllByLabelText('Идентичность участника: Иван')[0])
    expect(await screen.findByText('Иван Старый')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: /Разобрать 1/ }))
    expect(await screen.findByLabelText('Микроскоп эпизода')).toBeVisible()
    expect(await screen.findByText('Давайте проверим стенд')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Корпусы' }))
    expect(await screen.findByText('Микроскоп анализа')).toBeInTheDocument()
    expect(screen.getByText('Цепочка доказательств')).toBeInTheDocument()
    expect(screen.getByText('LOCAL ONLY')).toBeInTheDocument()
    expect(screen.getByLabelText('Активный снимок корпуса')).toHaveTextContent('snapshot')
  })

  it('opens the Russian annotation desk from primary navigation', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Разметка' }))
    expect(await screen.findByText('Русский пилот разметки ещё не создан')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Создать gold-ru-v1' })).toBeEnabled()
  })

  it('shows full-set gold-ru-v1 validation statistics', async () => {
    const annotationSet = {
      id: 'set-v1', corpus_id: 'c1', snapshot_id: 'snapshot-12345678', name: 'gold-ru-v1',
      language: 'ru', codebook_key: 'foundational-conversation-ru', codebook_version: '0.1.0',
      codebook_artifact_hash: 'hash', status: 'draft', target_size: 1200,
      sampling_spec: { double_annotation_fraction: 0.3 }, manifest_hash: null,
      frozen_at: null, created_at: '2025-01-01T00:00:00Z',
    }
    const statistics = {
      annotation_set_id: 'set-v1', name: 'gold-ru-v1', status: 'draft', target_size: 1200,
      total_units: 1200, status_counts: { pending: 1190, reviewed: 10 },
      split_counts: { train: 720, development: 240, test: 240 }, difficult_units: 600,
      confirmed_units: 10, coverage_by_kind: { proposition: 10 },
      double_annotation: { required: 360, completed: 4, fraction: 0.3 },
      agreement: { comparable_unit_kinds: 4, exact: 3, raw_rate: 0.75 },
      freeze_ready: false, manifest_hash: null,
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const data = url.includes('/statistics')
        ? statistics
        : url.includes('/units')
        ? { items: [], next_ordinal: null }
        : url.includes('/annotation-sets')
        ? [annotationSet]
        : url.includes('/observatory')
        ? observatory
        : url.includes('/api/corpora')
        ? [workspace.corpus]
        : url.includes('/microscope')
        ? workspace.microscope
        : workspace
      return new Response(JSON.stringify(data), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Разметка' }))
    expect(await screen.findByLabelText('Контроль научной валидации')).toBeVisible()
    expect(await screen.findByText('720 / 240 / 240')).toBeVisible()
    expect(screen.getByText('4 / 360')).toBeVisible()
    expect(screen.getByText('75%')).toBeVisible()
  })
})
