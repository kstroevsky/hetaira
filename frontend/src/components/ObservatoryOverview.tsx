import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  GitBranch,
  Network,
  RefreshCw,
  SearchCheck,
  ShieldCheck,
  Users,
} from 'lucide-react'

import { buildObservatory, fetchObservatory } from '../api/client'
import type { ObservatoryOverview } from '../api/types'

type ObservatoryOverviewProps = {
  corpusId: string
  onOpenEvidence: (messageId: string) => void
}

const number = new Intl.NumberFormat('ru-RU')
const compact = new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 1 })
const percent = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 })

function numeric(value: unknown): number {
  return typeof value === 'number' ? value : 0
}

function ActivityChart({ data }: { data: Array<{ month: string; messages: number }> }) {
  const width = 820
  const height = 210
  const padding = { left: 46, right: 12, top: 16, bottom: 34 }
  const innerWidth = width - padding.left - padding.right
  const innerHeight = height - padding.top - padding.bottom
  const maximum = Math.max(...data.map((item) => item.messages), 1)
  const barWidth = innerWidth / Math.max(data.length, 1)
  return (
    <svg
      className="activity-chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Количество сообщений по месяцам"
    >
      <title>Количество сообщений по месяцам</title>
      {[0, 0.5, 1].map((fraction) => {
        const y = padding.top + innerHeight * (1 - fraction)
        return (
          <g key={fraction}>
            <line x1={padding.left} x2={width - padding.right} y1={y} y2={y} />
            <text x={padding.left - 7} y={y + 4} textAnchor="end">
              {compact.format(maximum * fraction)}
            </text>
          </g>
        )
      })}
      {data.map((item, index) => {
        const barHeight = (item.messages / maximum) * innerHeight
        const x = padding.left + index * barWidth + 1
        const y = padding.top + innerHeight - barHeight
        return (
          <g key={item.month}>
            <rect x={x} y={y} width={Math.max(barWidth - 2, 2)} height={barHeight}>
              <title>{item.month}: {number.format(item.messages)} сообщений</title>
            </rect>
            {index % Math.max(Math.ceil(data.length / 7), 1) === 0 ? (
              <text x={x + barWidth / 2} y={height - 10} textAnchor="middle">
                {item.month.slice(2)}
              </text>
            ) : null}
          </g>
        )
      })}
    </svg>
  )
}

function KpiCard({
  icon: Icon,
  label,
  value,
  note,
}: {
  icon: typeof Activity
  label: string
  value: string
  note: string
}) {
  return (
    <article className="observatory-kpi">
      <Icon aria-hidden="true" />
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  )
}

export function ObservatoryOverview({ corpusId, onOpenEvidence }: ObservatoryOverviewProps) {
  const queryClient = useQueryClient()
  const overviewQuery = useQuery({
    queryKey: ['observatory', corpusId],
    queryFn: () => fetchObservatory(corpusId),
    retry: false,
  })
  const buildMutation = useMutation({
    mutationFn: () => buildObservatory(corpusId),
    onSuccess: (overview) => {
      queryClient.setQueryData(['observatory', corpusId], overview)
    },
  })
  if (overviewQuery.isLoading) {
    return <main className="observatory-empty">Загружаем аналитический снимок…</main>
  }
  const overview = overviewQuery.data
  if (!overview) {
    return (
      <main className="observatory-empty">
        <BarChart3 aria-hidden="true" />
        <h1>Многомерный обзор ещё не рассчитан</h1>
        <p>
          Расчёт создаст версионные L2-измерения активности, участия, ответов,
          сетевой структуры, функциональных профилей и лексической эволюции.
        </p>
        <button
          type="button"
          onClick={() => buildMutation.mutate()}
          disabled={buildMutation.isPending}
        >
          <RefreshCw /> {buildMutation.isPending ? 'Рассчитываем…' : 'Построить обзор'}
        </button>
        {buildMutation.error ? (
          <strong className="annotation-error">{String(buildMutation.error)}</strong>
        ) : null}
      </main>
    )
  }
  return <OverviewContent overview={overview} onOpenEvidence={onOpenEvidence} />
}

function OverviewContent({
  overview,
  onOpenEvidence,
}: {
  overview: ObservatoryOverview
  onOpenEvidence: (messageId: string) => void
}) {
  const { dimensions } = overview
  const reply = dimensions.reply_structure
  const source = dimensions.source
  const health = dimensions.health_primitives
  return (
    <main className="observatory" aria-label="Многомерный обзор корпуса">
      <header className="observatory-header">
        <div>
          <span className="eyebrow">COMPUTATIONAL CONVERSATION OBSERVATORY</span>
          <h1>{overview.corpus.name}</h1>
          <p>
            Снимок {overview.snapshot.id.slice(0, 8)} · {overview.analysis_version} ·{' '}
            {new Date(overview.generated_at).toLocaleString('ru-RU')}
          </p>
        </div>
        <div className="epistemic-badge">
          <ShieldCheck /> Описательно · предварительно
        </div>
      </header>

      <section className="observatory-kpis" aria-label="Ключевые показатели">
        <KpiCard icon={Activity} label="Сообщения" value={number.format(overview.snapshot.message_count)} note={`${numeric(source.sessions_8h)} сессий по границе 8ч`} />
        <KpiCard icon={Users} label="Участники" value={number.format(numeric(source.participants))} note={`баланс ${percent.format(dimensions.participation.normalized_entropy)}`} />
        <KpiCard icon={GitBranch} label="Разрешённые ответы" value={number.format(numeric(reply.resolved_reply_relations))} note={`${percent.format(numeric(reply.target_resolution_rate))} известных целей`} />
        <KpiCard icon={Network} label="Направленные диады" value={number.format(dimensions.network.directed_dyads)} note={`${dimensions.network.interaction_communities.length} сообществ взаимодействия`} />
        <KpiCard icon={SearchCheck} label="Медиана ответа" value={`${Math.round(numeric(reply.median_response_minutes))} мин`} note={`p90 ${Math.round(numeric(reply.p90_response_minutes))} мин`} />
      </section>

      <section className="observatory-grid primary">
        <article className="observatory-panel activity-panel">
          <header>
            <div><span className="panel-kicker">Движение</span><h2>Активность во времени</h2></div>
            <span>{dimensions.temporal.change_method}</span>
          </header>
          <ActivityChart data={dimensions.temporal.monthly_activity} />
          <div className="change-points">
            {dimensions.temporal.change_points.slice(0, 4).map((point) => (
              <div key={point.month}>
                {point.direction === 'increase' ? <ArrowUpRight /> : <ArrowDownRight />}
                <strong>{point.month}</strong>
                <span>{number.format(point.previous_messages)} → {number.format(point.messages)}</span>
              </div>
            ))}
          </div>
        </article>

        <article className="observatory-panel finding-panel">
          <header><div><span className="panel-kicker">L2</span><h2>Наблюдаемые выводы</h2></div></header>
          <div className="finding-feed">
            {overview.findings.map((finding) => (
              <article key={finding.id}>
                <div><span>{finding.dimension}</span><i>{finding.causal_status}</i></div>
                <p>{finding.claim}</p>
                <small>{finding.alternative_explanations[0]}</small>
                {finding.supporting_evidence[0]?.object_id ? (
                  <button type="button" onClick={() => onOpenEvidence(finding.supporting_evidence[0].object_id)}>
                    Открыть доказательство
                  </button>
                ) : null}
              </article>
            ))}
          </div>
        </article>
      </section>

      <section className="observatory-grid secondary">
        <article className="observatory-panel participation-panel">
          <header><div><span className="panel-kicker">Структура участия</span><h2>Кто создаёт объём</h2></div><span>Gini {dimensions.participation.gini.toFixed(2)}</span></header>
          <div className="rank-bars">
            {dimensions.participation.top_participants.slice(0, 10).map((participant) => (
              <div key={participant.participant_id}>
                <span>{participant.participant}</span>
                <div><i style={{ width: `${Math.max(participant.share * 100, 1)}%` }} /></div>
                <strong>{percent.format(participant.share)}</strong>
              </div>
            ))}
          </div>
          <p className="guardrail"><AlertTriangle /> {dimensions.participation.interpretation_guardrail}</p>
        </article>

        <article className="observatory-panel network-panel">
          <header><div><span className="panel-kicker">Interaction graph</span><h2>Центральность и сообщества</h2></div></header>
          <div className="community-strip">
            {dimensions.network.interaction_communities.slice(0, 6).map((community) => (
              <div key={community.community_id}>
                <strong>{community.size}</strong><span>участников</span>
                <small>{community.members.slice(0, 3).join(' · ')}</small>
              </div>
            ))}
          </div>
          <table>
            <thead><tr><th>Участник</th><th>PageRank</th><th>Brokerage</th><th>Ответы</th></tr></thead>
            <tbody>
              {dimensions.network.top_nodes.slice(0, 7).map((node) => (
                <tr key={node.participant_id}>
                  <td>{node.participant}</td><td>{node.pagerank.toFixed(3)}</td>
                  <td>{compact.format(node.betweenness)}</td><td>{number.format(node.replies_sent)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="guardrail"><AlertTriangle /> {dimensions.network.interpretation_guardrail}</p>
        </article>
      </section>

      <section className="observatory-grid tertiary">
        <article className="observatory-panel lexical-panel">
          <header><div><span className="panel-kicker">Лексическая эволюция</span><h2>Темы-навигация</h2></div></header>
          <div className="theme-grid">
            {dimensions.lexical_evolution.themes.slice(0, 8).map((theme) => (
              <div key={theme.theme_id}>
                <span>Кластер {theme.theme_id + 1}</span>
                <strong>{theme.terms.join(' · ')}</strong>
                <small>{number.format(theme.document_frequency)} совокупных употреблений</small>
              </div>
            ))}
          </div>
          <div className="term-movement">
            <div><strong>Чаще во второй половине</strong>{dimensions.lexical_evolution.emerging_terms.slice(0, 8).map((term) => <span key={term.term}>{term.term}</span>)}</div>
            <div><strong>Чаще в первой половине</strong>{dimensions.lexical_evolution.declining_terms.slice(0, 8).map((term) => <span key={term.term}>{term.term}</span>)}</div>
          </div>
          <p className="guardrail"><AlertTriangle /> {dimensions.lexical_evolution.guardrail}</p>
        </article>

        <article className="observatory-panel role-panel">
          <header><div><span className="panel-kicker">Participant × episode</span><h2>Функциональные профили</h2></div><span>предварительно</span></header>
          <div className="role-list">
            {dimensions.roles.participant_profiles.slice(0, 10).map((role) => (
              <div key={role.participant_id}>
                <strong>{role.participant}</strong>
                <span>{role.profiles.join(' · ')}</span>
                <small>{number.format(role.messages)} сообщений · ответы {percent.format(role.reply_rate)}</small>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="observatory-panel health-panel">
        <header><div><span className="panel-kicker">Не агрегируется в один score</span><h2>Примитивы здоровья разговора</h2></div></header>
        <div>
          <Metric label="Баланс участия" value={percent.format(numeric(health.participation_balance))} />
          <Metric label="Разрешение reply-целей" value={percent.format(numeric(health.reply_target_resolution))} />
          <Metric label="Диадическая взаимность" value={percent.format(numeric(health.dyadic_reciprocity))} />
          <Metric label="Медиана ответа" value={`${Math.round(numeric(health.median_response_minutes))} мин`} />
        </div>
        <p>Пока отсутствуют: {Array.isArray(health.missing_dimensions) ? health.missing_dimensions.join(' · ') : 'семантические измерения'}</p>
      </section>
      <footer className="observatory-provenance">
        <span>artifact {overview.artifact_id.slice(0, 8)}</span>
        <span>SHA-256 {overview.content_hash.slice(0, 16)}…</span>
        <span>manifest {overview.snapshot.manifest_hash.slice(0, 16)}…</span>
        <span>{overview.corpus.privacy_policy}</span>
      </footer>
    </main>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="health-metric"><span>{label}</span><strong>{value}</strong></div>
}
