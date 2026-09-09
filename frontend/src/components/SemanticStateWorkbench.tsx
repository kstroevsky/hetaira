import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, Play } from 'lucide-react'

import { buildSemanticState, fetchSemanticState } from '../api/client'
import { ArtifactDetails } from './ArtifactDetails'

export function SemanticStateWorkbench({ corpusId }: { corpusId: string }) {
  const client = useQueryClient()
  const state = useQuery({ queryKey: ['semantic-state', corpusId], queryFn: () => fetchSemanticState(corpusId), retry: false })
  const build = useMutation({ mutationFn: () => buildSemanticState(corpusId), onSuccess: () => client.invalidateQueries({ queryKey: ['semantic-state', corpusId] }) })
  if (state.error && !state.data) return (
    <main className="state-empty" aria-label="Семантика и состояния"><Activity /><h1>Динамические модели ещё не рассчитаны</h1>
      <button type="button" onClick={() => build.mutate()} disabled={build.isPending}><Play />{build.isPending ? 'Анализируем…' : 'Построить модели'}</button></main>
  )
  if (!state.data) return <main className="state-empty">Загружаем модели…</main>
  const data = state.data
  return <main className="state-workbench" aria-label="Семантика и состояния">
    <header><div><span>PROVISIONAL · MULTI-METHOD</span><h1>Семантика и состояния</h1><p>{data.guardrail}</p></div></header>
    <section className="state-grid">
      <article><h2>Тематические challengers</h2>{Object.entries(data.topic_challengers.models).map(([name, model]) => <div key={name}><strong>{name.toUpperCase()}</strong><span>{model.status} · {model.topic_count ?? model.reason}</span></div>)}
        <p>ARI: {data.topic_challengers.agreement?.adjusted_rand_index.toFixed(3) ?? '—'} · disagreement = uncertainty</p></article>
      <article><h2>Семантическое изменение</h2><small>{data.semantic_change.representation ?? data.semantic_change.status}</small>
        {data.semantic_change.terms.slice(0, 8).map((item) => <div key={item.term}><strong>{item.term}</strong><span>{item.average_pairwise_cosine_distance.toFixed(3)}</span></div>)}</article>
      <article><h2>Кандидаты точек изменения</h2>{data.change_points.message_activity.map((item) => <div key={item.method}><strong>{item.month}</strong><span>{item.method} · {item.score.toFixed(3)}</span></div>)}</article>
      <article><h2>Латентные состояния</h2><small>{data.conversation_states.status} · states unlabeled</small>
        {data.conversation_states.sequence?.map((item) => <div key={item.month}><strong>{item.month}</strong><span>{item.state}</span></div>)}</article>
      <article className="state-wide"><h2>Темы и траектории</h2>
        {Object.entries(data.topic_challengers.models).flatMap(([method, model]) =>
          (model.topics ?? []).map((topic) => <div key={`${method}:${topic.topic_id}`}>
            <strong>{method.toUpperCase()} #{topic.topic_id} · {topic.terms.join(' · ')}</strong>
            <span>{topic.trajectory.map((point) => `${point.month}: ${(point.share * 100).toFixed(0)}%`).join(' | ')}</span>
          </div>),
        )}
      </article>
      <article className="state-wide"><h2>HMM diagnostics</h2>
        <pre>{JSON.stringify({ features: data.conversation_states.features, transition_matrix: data.conversation_states.transition_matrix, state_means_standardized: data.conversation_states.state_means_standardized }, null, 2)}</pre>
      </article>
    </section>
    <ArtifactDetails value={data} />
  </main>
}
