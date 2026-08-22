import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
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
  },
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const data = url.includes('/api/corpora')
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
    expect(await screen.findByText('Микроскоп анализа')).toBeInTheDocument()
    expect(screen.getByText('Цепочка доказательств')).toBeInTheDocument()
    expect(screen.getByText('LOCAL ONLY')).toBeInTheDocument()
  })
})
