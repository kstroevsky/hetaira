import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { GitMerge, Play } from 'lucide-react'

import { createReasoningRun, fetchReasoningGraph } from '../api/client'

export function ReasoningGraphWorkbench({ corpusId }: { corpusId: string }) {
  const client = useQueryClient()
  const graph = useQuery({
    queryKey: ['reasoning-graph', corpusId],
    queryFn: () => fetchReasoningGraph(corpusId),
    retry: false,
  })
  const create = useMutation({
    mutationFn: () => createReasoningRun(corpusId),
    onSuccess: () => client.invalidateQueries({ queryKey: ['reasoning-graph', corpusId] }),
  })
  if (graph.error && !graph.data) {
    return (
      <main className="reasoning-empty" aria-label="Граф аргументации">
        <GitMerge />
        <h1>Граф аргументации ещё не рассчитан</h1>
        <p>Компоненты и связи будут построены из версионированных пропозиций и графа ответа.</p>
        <button type="button" onClick={() => create.mutate()} disabled={create.isPending}>
          <Play /> {create.isPending ? 'Анализируем…' : 'Построить reasoning graph'}
        </button>
      </main>
    )
  }
  if (!graph.data) return <main className="reasoning-empty">Загружаем reasoning graph…</main>
  const propositions = new Map(graph.data.propositions.map((item) => [item.id, item]))
  const nliTask = graph.data.run.tasks.find((task) => task.task_key === 'nli_challenger')
  return (
    <main className="reasoning-workbench" aria-label="Граф аргументации">
      <header>
        <div><span>PROVISIONAL · L1</span><h1>Аргументы и NLI</h1><p>{graph.data.guardrail}</p></div>
        <strong>NLI: {nliTask?.status ?? '—'}</strong>
      </header>
      <section>
        {graph.data.relations.map((relation) => (
          <article key={relation.id}>
            <div><small>ИСТОЧНИК</small><p>{propositions.get(relation.source_proposition_id)?.text}</p></div>
            <div className={`reasoning-relation ${relation.relation_type.toLowerCase()}`}>
              <strong>{relation.relation_type}</strong>
              <small>{relation.method}</small>
              <span>{relation.raw_score === null ? 'не калибровано' : relation.raw_score.toFixed(3)}</span>
            </div>
            <div><small>ЦЕЛЬ</small><p>{propositions.get(relation.target_proposition_id)?.text}</p></div>
          </article>
        ))}
        {!graph.data.relations.length ? <p>Правила воздержались от создания связей.</p> : null}
      </section>
    </main>
  )
}
