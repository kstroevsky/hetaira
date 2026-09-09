import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FlaskConical, Play } from 'lucide-react'

import { buildExperimentalDynamics, fetchExperimentalDynamics } from '../api/client'
import { ArtifactDetails } from './ArtifactDetails'
import { MethodTip } from './MethodTip'

export function ExperimentalDynamicsWorkbench({ corpusId }: { corpusId: string }) {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['experimental-dynamics', corpusId], queryFn: () => fetchExperimentalDynamics(corpusId), retry: false })
  const build = useMutation({ mutationFn: () => buildExperimentalDynamics(corpusId), onSuccess: () => client.invalidateQueries({ queryKey: ['experimental-dynamics', corpusId] }) })
  if (query.error && !query.data) return <main className="experimental-empty" aria-label="Экспериментальные модели"><FlaskConical /><h1>Экспериментальные модели ещё не рассчитаны</h1><button type="button" onClick={() => build.mutate()}><Play />Рассчитать</button></main>
  if (!query.data) return <main className="experimental-empty">Загружаем экспериментальные модели…</main>
  const data = query.data
  return <main className="experimental-workbench" aria-label="Экспериментальные модели">
    <header><span>EXPERIMENTAL · NON-CAUSAL</span><h1>Информационная и affect-динамика</h1><p>{data.guardrail}</p></header>
    <section className="experimental-grid">
      <article><h2 className="method-heading">Semantic transfer entropy <MethodTip tip="transferEntropy" /></h2><small>{data.semantic_information_dynamics.status} · {data.semantic_information_dynamics.representation ?? data.semantic_information_dynamics.reason}</small>
        <p>{data.semantic_information_dynamics.bias_warning}</p>
        {data.semantic_information_dynamics.transfer_entropy?.slice(0, 12).map((item) => <div key={`${item.source_id}:${item.target_id}`}><strong>{item.source_id.slice(0, 6)} → {item.target_id.slice(0, 6)}</strong><span>{item.transfer_entropy_bits.toFixed(3)} bits · p {item.one_sided_p.toFixed(3)}</span></div>)}</article>
      <article><h2 className="method-heading">Лингвистический affect <MethodTip tip="affect" /></h2><small>{data.linguistic_affect_dynamics.interpretation}</small><p>{data.linguistic_affect_dynamics.messages_with_nonzero_signal} / {data.linguistic_affect_dynamics.messages} сообщений с ненулевым сигналом</p>
        {data.linguistic_affect_dynamics.monthly_trajectory.slice(0, 12).map((item) => <div key={String(item.month)}><strong>{String(item.month)}</strong><span>valence {Number(item.valence).toFixed(3)} · arousal {Number(item.arousal).toFixed(3)}</span></div>)}</article>
      <article className="experimental-wide"><h2 className="method-heading">Partial information decomposition <MethodTip tip="pid" /></h2>
        {data.semantic_information_dynamics.partial_information?.map((item) => <div key={`${item.left_source_id}:${item.right_source_id}:${item.target_id}`}><strong>{item.left_source_id.slice(0, 6)} + {item.right_source_id.slice(0, 6)} → {item.target_id.slice(0, 6)}</strong><span>R {item.redundancy_bits.toFixed(3)} · U₁ {item.unique_left_bits.toFixed(3)} · U₂ {item.unique_right_bits.toFixed(3)} · S {item.synergy_bits.toFixed(3)}</span></div>)}</article>
    </section>
    <ArtifactDetails value={data} />
  </main>
}
