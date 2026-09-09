import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, Play } from 'lucide-react'

import { buildInteractionDynamics, fetchInteractionDynamics } from '../api/client'
import { ArtifactDetails } from './ArtifactDetails'

export function InteractionDynamicsWorkbench({ corpusId }: { corpusId: string }) {
  const client = useQueryClient()
  const query = useQuery({
    queryKey: ['interaction-dynamics', corpusId],
    queryFn: () => fetchInteractionDynamics(corpusId),
    retry: false,
  })
  const build = useMutation({
    mutationFn: () => buildInteractionDynamics(corpusId),
    onSuccess: () => client.invalidateQueries({ queryKey: ['interaction-dynamics', corpusId] }),
  })
  if (query.error && !query.data) return (
    <main className="interaction-empty" aria-label="Динамика взаимодействия">
      <Activity /><h1>Динамика взаимодействия ещё не рассчитана</h1>
      <button type="button" onClick={() => build.mutate()} disabled={build.isPending}>
        <Play />{build.isPending ? 'Рассчитываем…' : 'Рассчитать динамику'}
      </button>
    </main>
  )
  if (!query.data) return <main className="interaction-empty">Загружаем динамику…</main>
  const data = query.data
  const coordination = data.measurements['directional-coordination@0.1.0']
  const survival = data.measurements['response-survival@0.1.0']
  const relational = data.measurements['relational-event-choice@0.1.0']
  return (
    <main className="interaction-workbench" aria-label="Динамика взаимодействия">
      <header><span>DESCRIPTIVE / ASSOCIATIONAL</span><h1>Координация, survival и relational events</h1><p>{data.guardrail}</p></header>
      <section className="interaction-grid">
        <article>
          <h2>Направленная языковая координация</h2>
          <small>n={coordination.sample_size} / {coordination.denominator} explicit reply events</small>
          {coordination.estimate.map((item) => <div key={`${item.initiator_id}:${item.responder_id}`}>
            <strong>{item.initiator_id.slice(0, 6)} → {item.responder_id.slice(0, 6)}</strong>
            <span>{item.accommodation_delta.toFixed(3)} [{item.lower.toFixed(3)}, {item.upper.toFixed(3)}]</span>
          </div>)}
        </article>
        <article>
          <h2>Response survival</h2>
          <small>{survival.numerator} replies / {survival.denominator} messages · median {survival.estimate.median_minutes ?? '—'} min</small>
          {survival.estimate.survival_curve.slice(0, 12).map((point) => <div key={point.minutes}>
            <strong>{point.minutes.toFixed(1)} min</strong><span>S(t) {point.survival.toFixed(3)} · risk {point.at_risk} · censored {point.censored}</span>
          </div>)}
        </article>
        <article>
          <h2>Relational-event receiver choice</h2>
          <small>{relational.causal_status} · risk sets {relational.sample_size} / events {relational.denominator}</small>
          {Object.entries(relational.estimate.relative_choice_odds ?? {}).map(([name, value]) => <div key={name}><strong>{name}</strong><span>relative odds {value.toFixed(3)}</span></div>)}
          {'reason' in relational.uncertainty ? <p>{String(relational.uncertainty.reason)}</p> : null}
        </article>
        <article>
          <h2>Controls and missingness</h2>
          <dl><dt>Coordination</dt><dd>{coordination.controls.join(' · ')}</dd><dt>Survival</dt><dd>{survival.controls.join(' · ')}</dd><dt>REM</dt><dd>{relational.controls.join(' · ')}</dd></dl>
        </article>
      </section>
      <ArtifactDetails value={data} />
    </main>
  )
}
