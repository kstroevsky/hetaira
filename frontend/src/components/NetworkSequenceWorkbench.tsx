import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Network, Play } from 'lucide-react'

import { buildNetworkSequence, fetchNetworkSequence } from '../api/client'
import { ArtifactDetails } from './ArtifactDetails'

export function NetworkSequenceWorkbench({ corpusId }: { corpusId: string }) {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['network-sequence', corpusId], queryFn: () => fetchNetworkSequence(corpusId), retry: false })
  const build = useMutation({ mutationFn: () => buildNetworkSequence(corpusId), onSuccess: () => client.invalidateQueries({ queryKey: ['network-sequence', corpusId] }) })
  if (query.error && !query.data) return <main className="network-empty" aria-label="Сети и последовательности"><Network /><h1>Сетевые модели ещё не рассчитаны</h1><button type="button" onClick={() => build.mutate()}><Play />Построить модели</button></main>
  if (!query.data) return <main className="network-empty">Загружаем сетевые модели…</main>
  const data = query.data
  return <main className="network-workbench" aria-label="Сети и последовательности">
    <header><span>PROVISIONAL · ASSOCIATIONAL</span><h1>Сети и последовательности</h1><p>{data.guardrail}</p></header>
    <section className="network-grid">
      <article><h2>Слои сообществ</h2>{Object.entries(data.multilayer_communities.layers).map(([name, layer]) => <div key={name}><strong>{name}</strong><span>{layer.status} · {layer.communities.length}</span></div>)}</article>
      <article><h2>Hawkes</h2><div><strong>{data.hawkes.status}</strong><span>{data.hawkes.method ?? data.hawkes.reason}</span></div><p>spectral radius: {data.hawkes.spectral_radius?.toFixed(3) ?? '—'}</p></article>
      <article><h2>Мотивы против null</h2>{Object.entries(data.network_motifs.motifs).map(([name, item]) => <div key={name}><strong>{name}</strong><span>{item.observed} vs {item.null_mean.toFixed(2)} ± {item.null_sd.toFixed(2)}</span></div>)}</article>
      <article><h2>Последовательности актов</h2>{data.dialogue_sequences.frequent_patterns.slice(0, 8).map((item) => <div key={item.sequence.join(':')}><strong>{item.sequence.join(' → ')}</strong><span>{item.count}</span></div>)}</article>
      <article><h2>Динамика interaction-сообществ</h2>{data.multilayer_communities.dynamic_interaction.map((item) => <div key={item.month}><strong>{item.month}</strong><span>{item.status} · {item.communities?.length ?? item.reason}</span></div>)}</article>
      <article><h2>Недоступные слои</h2><div><strong>knowledge flow</strong><span>{data.multilayer_communities.knowledge_flow.reason}</span></div>
        {data.multilayer_communities.stance ? <div><strong>stance</strong><span>{data.multilayer_communities.stance.reason}</span></div> : null}</article>
      <article><h2>Переходы диалоговых актов</h2>{data.dialogue_sequences.transitions.slice(0, 12).map((item) => <div key={`${item.from}:${item.to}`}><strong>{item.from} → {item.to}</strong><span>{item.count}</span></div>)}</article>
    </section>
    <ArtifactDetails value={data} />
  </main>
}
