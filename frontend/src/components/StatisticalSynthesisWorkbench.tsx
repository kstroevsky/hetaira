import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Calculator, Play } from 'lucide-react'

import { buildStatisticalSynthesis, fetchStatisticalSynthesis } from '../api/client'

export function StatisticalSynthesisWorkbench({ corpusId }: { corpusId: string }) {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['statistical-synthesis', corpusId], queryFn: () => fetchStatisticalSynthesis(corpusId), retry: false })
  const build = useMutation({ mutationFn: () => buildStatisticalSynthesis(corpusId), onSuccess: () => client.invalidateQueries({ queryKey: ['statistical-synthesis', corpusId] }) })
  if (query.error && !query.data) return <main className="statistics-empty" aria-label="Статистический синтез"><Calculator /><h1>Статистический синтез ещё не рассчитан</h1><button type="button" onClick={() => build.mutate()}><Play />Рассчитать модели</button></main>
  if (!query.data) return <main className="statistics-empty">Загружаем статистику…</main>
  const data = query.data
  return <main className="statistics-workbench" aria-label="Статистический синтез">
    <header><span>PROVISIONAL · ASSOCIATIONAL</span><h1>Null-модели и иерархическая статистика</h1><p>{data.guardrail}</p></header>
    <section className="statistics-grid">
      <article><h2>Перестановочные проверки диад</h2><small>{data.null_models.null ?? data.null_models.reason}</small>
        {data.null_models.tests?.slice(0, 12).map((item) => <div key={`${item.source_id}:${item.target_id}`}><strong>{item.source_id.slice(0, 6)} → {item.target_id.slice(0, 6)}</strong><span>z {item.z_score?.toFixed(2) ?? '—'} · p {item.one_sided_p.toFixed(3)}</span></div>)}</article>
      <article><h2>Иерархическая reply-модель</h2><small>{data.hierarchical_reply_model.status} · n={data.hierarchical_reply_model.sample_size ?? '—'}</small>
        {Object.entries(data.hierarchical_reply_model.fixed_effects ?? {}).map(([name, value]) => <div key={name}><strong>{name}</strong><span>OR {value.odds_ratio.toFixed(3)}</span></div>)}
        {data.hierarchical_reply_model.reason ? <p>{data.hierarchical_reply_model.reason}</p> : null}</article>
    </section>
  </main>
}
