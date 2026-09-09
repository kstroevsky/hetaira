import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { InteractionDynamicsWorkbench } from './InteractionDynamicsWorkbench'

afterEach(() => cleanup())

it('renders coordination, censoring, relational-event gates, and full diagnostics', async () => {
  const payload = {
    run: { id: 'run', snapshot_id: 'snapshot', status: 'completed', progress: 1, configuration: { analysis_version: 'interaction-dynamics@0.1.0' } },
    measurements: {
      'directional-coordination@0.1.0': {
        estimate: [{ initiator_id: 'participant-a', responder_id: 'participant-b', events: 3, accommodation_delta: 0.2, lower: 0.1, upper: 0.3 }],
        sample_size: 3, denominator: 4, uncertainty: { method: 'normal' }, missingness: { missing_sender: 1 }, controls: ['baseline'],
      },
      'response-survival@0.1.0': {
        estimate: { median_minutes: 12, survival_curve: [{ minutes: 12, survival: 0.5, at_risk: 4, replies: 2, censored: 1 }] },
        sample_size: 4, numerator: 2, denominator: 4, uncertainty: { method: 'KM' }, missingness: {}, controls: ['right_censor'],
      },
      'relational-event-choice@0.1.0': {
        estimate: {}, sample_size: 2, denominator: 4,
        uncertainty: { method: 'not_estimated', reason: 'fewer_than_10_informative_risk_sets' },
        missingness: { uninformative: 2 }, controls: ['risk_set'], causal_status: 'associational',
      },
    },
    guardrail: 'No causal claim.',
  }
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(payload), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  })))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><InteractionDynamicsWorkbench corpusId="c1" /></QueryClientProvider>)

  expect(await screen.findByText('Направленная языковая координация')).toBeVisible()
  expect(screen.getByText(/S\(t\) 0.500/)).toBeVisible()
  expect(screen.getByText('fewer_than_10_informative_risk_sets')).toBeVisible()
  fireEvent.click(screen.getByText('Полный технический результат'))
  expect(screen.getByText(/interaction-dynamics@0.1.0/)).toBeVisible()
})
