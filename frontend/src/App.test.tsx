import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
    expect(screen.getByRole('button', { name: 'Создать reference pilot' })).toBeEnabled()
  })

  it('keeps source replies and inferred graph proposals visibly separate', async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = []
    const graph = {
      run: {
        id: 'graph-run', snapshot_id: 'snapshot-12345678', run_type: 'conversation-graph',
        status: 'completed', progress: 1, configuration: {}, started_at: null,
        completed_at: '2025-01-01T10:00:00Z', error: null,
        tasks: [{
          id: 'encoder-task', task_key: 'encoder_challenger', status: 'unavailable',
          progress: 1, checkpoint: {}, error: 'not configured',
        }],
      },
      messages: [
        { id: 'm0', conversation_id: 'c0', external_id: '0', revision_id: 'r0', sender_id: 'p2', sender_name: 'Борис', sent_at: '2025-01-01T08:59:00Z', text: 'Проверим?', text_hash: 'zero-hash' },
        { id: 'm1', conversation_id: 'c0', external_id: '1', revision_id: 'r1', sender_id: 'p1', sender_name: 'Иван', sent_at: '2025-01-01T09:00:00Z', text: 'Да, проверим.', text_hash: 'one-hash' },
      ],
      explicit_replies: [{ source_message_id: 'm1', target_message_id: 'm0', relation_type: 'REPLIES_TO', source_native: true, confidence: 1 }],
      response_candidates: [{
        id: 'candidate-1', annotation_id: 'annotation-1', source_message_id: 'm1',
        target_message_id: 'm0', source_revision_id: 'r1', target_revision_id: 'r0',
        method: 'lexical-cosine-ru@0.1.0', rank: 1, raw_score: 0.5,
        score_semantics: 'uncalibrated_similarity', status: 'provisional', review: null,
      }],
      discourse_relations: [{
        id: 'discourse-1', annotation_id: 'annotation-2', source_message_id: 'm1',
        target_message_id: 'm0', source_revision_id: 'r1', target_revision_id: 'r0',
        relation_type: 'ANSWERS', method: 'conversation-graph-rules-ru@0.1.0',
        raw_score: 0.5, status: 'provisional', review: null,
      }],
      page: { offset: 0, limit: 250 },
      guardrail: 'Similarity is not probability.',
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push({ url, init })
      const data = url.includes('/annotations/annotation-1/reviews')
        ? { id: 'review-1', decision: 'confirmed' }
        : url.includes('/conversation-graph')
        ? graph
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

    fireEvent.click(await screen.findByRole('button', { name: 'Граф диалога' }))
    expect(await screen.findByText('Исходные ответы')).toBeVisible()
    expect(screen.getByText('Кандидаты ответа')).toBeVisible()
    expect(screen.getByText('Дискурсивные отношения')).toBeVisible()
    expect(screen.getAllByText('REPLIES_TO').length).toBeGreaterThan(0)
    expect(screen.getByText('отвечает')).toBeVisible()
    fireEvent.click(screen.getAllByLabelText('Подтвердить связь')[0])
    await waitFor(() => expect(
      calls.some((call) => call.url.includes('/annotations/annotation-1/reviews')),
    ).toBe(true))
  })

  it('shows full-set gold-ru-v1 validation statistics', async () => {
    const annotationSet = {
      id: 'set-v1', corpus_id: 'c1', snapshot_id: 'snapshot-12345678', name: 'archive-reference-ru-pilot-v1',
      language: 'ru', codebook_key: 'foundational-conversation-ru', codebook_version: '0.1.0',
      codebook_artifact_hash: 'hash', status: 'draft', target_size: 80,
      sampling_spec: { double_annotation_fraction: 0.3, judgment_protocol: 'blind_ab_final_v1' }, manifest_hash: null,
      frozen_at: null, created_at: '2025-01-01T00:00:00Z',
    }
    const statistics = {
      annotation_set_id: 'set-v1', name: 'archive-reference-ru-pilot-v1', status: 'draft', target_size: 80,
      total_units: 80, status_counts: { pending: 78, reviewed: 2 },
      split_counts: { train: 48, development: 16, test: 16 }, difficult_units: 40,
      confirmed_units: 2, coverage_by_kind: { proposition: 2 },
      task_completion: { dialogue_act: { completed: 2, required: 80 } },
      double_annotation: { required: 24, completed: 4, fraction: 0.3 },
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
    expect(await screen.findByText('48 / 16 / 16')).toBeVisible()
    expect(screen.getByText('4 / 24')).toBeVisible()
    expect(screen.getAllByText('2 / 80')).toHaveLength(2)
    expect(screen.getByText('75%')).toBeVisible()
  })

  it('keeps A/B judgments blind and submits an explicit absence', async () => {
    const annotationSet = {
      id: 'set-blind', corpus_id: 'c1', snapshot_id: 'snapshot-12345678',
      name: 'archive-reference-ru-pilot-v1', language: 'ru',
      codebook_key: 'foundational-conversation-ru', codebook_version: '0.1.0',
      codebook_artifact_hash: 'hash', status: 'draft', target_size: 80,
      sampling_spec: { judgment_protocol: 'blind_ab_final_v1' }, manifest_hash: null,
      frozen_at: null, created_at: '2025-01-01T00:00:00Z',
    }
    const unit = {
      id: 'unit-1', ordinal: 0, object_type: 'anchor_message', object_id: 'm1',
      revision_id: 'revision-1', group_id: 'episode-1', split: 'train',
      strata: { double_annotation_required: true, has_explicit_reply: true },
      status: 'pending', sender_id: 'p1', sent_at: '2025-01-01T09:00:00Z',
      text: 'Да, именно.', text_hash: 'text-hash', annotations: [],
      judgment_progress: {
        A: { completed: 0, required: 6 }, B: { completed: 1, required: 6 },
        FINAL: { completed: 0, required: 6 },
      },
    }
    const judgments = ['dialogue_act', 'proposition', 'stance', 'epistemic_state', 'grounding', 'argumentation']
      .map((task) => ({
        id: `a-${task}`, task, slot: 'A', stage: 'independent',
        status: 'NOT_ANNOTATED', annotator: null, submitted_at: null, annotations: [],
      }))
    const context = {
      unit_id: 'unit-1', annotation_set_id: 'set-blind', split: 'train',
      strata: unit.strata, slot: 'A', blind: true, anchor_message_id: 'm1',
      anchor_revision_id: 'revision-1', episode_id: 'episode-1', episode_size: 2,
      context_policy: { anchor_only_labelable: true },
      messages: [
        { message_id: 'm0', sender_id: 'p2', sender_name: 'Борис', sent_at: '2025-01-01T08:59:00Z', text: 'Это так?', context_role: 'reply_target', labelable: false },
        { message_id: 'm1', sender_id: 'p1', sender_name: 'Иван', sent_at: '2025-01-01T09:00:00Z', text: 'Да, именно.', context_role: 'anchor', labelable: true },
      ],
      judgments,
    }
    const statistics = {
      annotation_set_id: 'set-blind', name: annotationSet.name, status: 'draft', target_size: 80,
      total_units: 80, status_counts: { pending: 80 },
      split_counts: { train: 48, development: 16, test: 16 }, difficult_units: 40,
      confirmed_units: 0, coverage_by_kind: {},
      task_completion: Object.fromEntries(judgments.map(({ task }) => [task, { completed: 0, required: 80 }])),
      double_annotation: { required: 24, completed: 0, fraction: 0.3 },
      agreement: { comparable_unit_kinds: 0, exact: 0, raw_rate: null },
      freeze_ready: false, manifest_hash: null, judgment_protocol: 'blind_ab_final_v1',
    }
    const calls: Array<{ url: string; init?: RequestInit }> = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push({ url, init })
      const data = url.includes('/judgments/')
        ? { id: 'saved', task: 'dialogue_act', slot: 'A', stage: 'independent', status: 'ABSENT' }
        : url.includes('/annotation-units/unit-1/context')
        ? context
        : url.includes('/statistics')
        ? statistics
        : url.includes('/units')
        ? { items: [unit], next_ordinal: null }
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
    expect(await screen.findByText('слепой режим A · 2 сообщений в эпизоде')).toBeVisible()
    expect(screen.getByText('Это так?')).toBeVisible()
    expect(screen.getByText('ANCHOR · размечается')).toBeVisible()
    expect(screen.getByText('Blind mode: суждения другого аннотатора и FINAL скрыты.')).toBeVisible()
    expect(screen.queryByText('annotator-b')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Добавить экземпляр' }))
    fireEvent.change(screen.getByLabelText('Начало'), { target: { value: '4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Добавить экземпляр' }))
    expect(screen.getByLabelText('Экземпляры текущего суждения')).toHaveTextContent(
      'dialogue_act #2',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить суждение' }))
    await waitFor(() => expect(calls.some((call) => call.url.includes('/judgments/dialogue_act/A'))).toBe(true))
    const submission = calls.find((call) => call.url.includes('/judgments/dialogue_act/A'))
    const submittedPresent = JSON.parse(String(submission?.init?.body))
    expect(submittedPresent).toMatchObject({
      status: 'PRESENT', annotator: 'local-annotator',
    })
    expect(submittedPresent.annotations).toHaveLength(2)

    fireEvent.change(screen.getByLabelText('Измерение'), { target: { value: 'proposition' } })
    fireEvent.change(screen.getByLabelText('Результат задачи'), { target: { value: 'ABSENT' } })
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить суждение' }))
    await waitFor(() => expect(calls.some((call) => call.url.includes('/judgments/proposition/A'))).toBe(true))
    const absence = calls.find((call) => call.url.includes('/judgments/proposition/A'))
    expect(JSON.parse(String(absence?.init?.body))).toMatchObject({
      status: 'ABSENT', annotator: 'local-annotator', annotations: [],
    })
  })
})
