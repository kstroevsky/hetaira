import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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
  schema: 'hetaira.observatory-overview.v1', analysis_version: 'observatory-overview@1.0.0',
  corpus: { id: 'c1', name: 'Архив команды', language: 'ru', privacy_policy: 'LOCAL_ONLY' },
  snapshot: { id: 'snapshot-12345678', manifest_hash: 'manifestabcdef123456', message_count: 1, created_at: '2025-01-01T00:00:00Z' },
  dimensions: {
    source: { sessions_8h: 1, participants: 1 },
    temporal: { monthly_activity: [{ month: '2025-01', messages: 1 }], busiest_month: { month: '2025-01', messages: 1 }, change_points: [], change_method: 'test', partial_month_warning: true },
    participation: { normalized_entropy: 1, gini: 0, top_1_share: 1, top_10_share: 1, top_participants: [{ participant_id: 'p1', participant: 'Участник 1', messages: 1, share: 1 }], interpretation_guardrail: 'Не влияние.' },
    reply_structure: { resolved_reply_relations: 0, target_resolution_rate: 0, median_response_minutes: 0, p90_response_minutes: 0 },
    network: { participants: 1, directed_dyads: 0, interaction_communities: [], top_nodes: [], interpretation_guardrail: 'Не власть.' },
    roles: { participant_profiles: [] },
    lexical_evolution: { method: 'test', themes: [], guardrail: 'Навигация.' },
    health_primitives: { participation_balance: 1, reply_target_resolution: 0, dyadic_reciprocity: 0, median_response_minutes: 0, missing_dimensions: [] },
    data_quality: {},
  },
  findings: [], measurement_result_ids: {}, epistemic_status: 'descriptive_provisional', generated_at: '2025-01-01T00:00:00Z',
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const data = url.includes('/observatory')
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
    expect(screen.queryByText('Чаще в первой половине')).not.toBeInTheDocument()
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
    expect(screen.getByRole('button', { name: 'Создать gold-ru-v0' })).toBeEnabled()
  })
})
