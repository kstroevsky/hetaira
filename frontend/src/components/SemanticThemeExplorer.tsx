import { useState } from 'react'
import { AlertTriangle, ArrowDownRight, ArrowUpRight, ExternalLink, ScanSearch } from 'lucide-react'

import type { ObservatoryOverview, SemanticTheme } from '../api/types'
import { EpisodeMicroscope } from './EpisodeMicroscope'
import { MetricTip } from './MetricTip'
import { ParticipantIdentityPopover } from './ParticipantIdentityPopover'

type SemanticAnalysis = ObservatoryOverview['dimensions']['semantic_themes']

type SemanticThemeExplorerProps = {
  corpusId: string
  analysis: SemanticAnalysis
  onOpenEvidence: (messageId: string) => void
}

const number = new Intl.NumberFormat('ru-RU')
const percent = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 })
const CHART = { width: 900, height: 250, left: 54, right: 18, top: 20, bottom: 38 }
const qualityLabels = {
  high: 'хорошая разделимость',
  moderate: 'умеренная разделимость',
  low: 'низкая разделимость',
  unavailable: 'разделимость не оценена',
}

function ThemeTrajectory({ theme }: { theme: SemanticTheme }) {
  const data = theme.trajectory
  const innerWidth = CHART.width - CHART.left - CHART.right
  const innerHeight = CHART.height - CHART.top - CHART.bottom
  const maximum = Math.max(...data.map((item) => item.share), 0.01)
  const x = (index: number) =>
    CHART.left + (data.length <= 1 ? innerWidth / 2 : (index / (data.length - 1)) * innerWidth)
  const y = (share: number) => CHART.top + innerHeight * (1 - share / maximum)
  const points = data.map((item, index) => `${x(index)},${y(item.share)}`).join(' ')
  const area = data.length
    ? `${CHART.left},${CHART.top + innerHeight} ${points} ${x(data.length - 1)},${CHART.top + innerHeight}`
    : ''
  const changeMonths = new Set(theme.change_points.map((point) => point.month))
  const labelEvery = Math.max(Math.ceil(data.length / 7), 1)

  return (
    <svg
      className="theme-trajectory"
      viewBox={`0 0 ${CHART.width} ${CHART.height}`}
      role="img"
      aria-label={`Доля сообщений темы «${theme.label}» по месяцам`}
    >
      <title>Месячная доля сообщений, отнесённых к выбранной теме</title>
      {[0, 0.5, 1].map((fraction) => {
        const gridY = CHART.top + innerHeight * (1 - fraction)
        return (
          <g key={fraction}>
            <line x1={CHART.left} x2={CHART.width - CHART.right} y1={gridY} y2={gridY} />
            <text x={CHART.left - 8} y={gridY + 4} textAnchor="end">
              {percent.format(maximum * fraction)}
            </text>
          </g>
        )
      })}
      {area ? <polygon points={area} /> : null}
      {points ? <polyline points={points} /> : null}
      {data.map((item, index) => (
        <g key={item.month}>
          {changeMonths.has(item.month) ? (
            <circle className="change-marker" cx={x(index)} cy={y(item.share)} r="5">
              <title>{item.month}: изменение, доля {percent.format(item.share)}</title>
            </circle>
          ) : null}
          {index % labelEvery === 0 || index === data.length - 1 ? (
            <text x={x(index)} y={CHART.height - 12} textAnchor="middle">
              {item.month.slice(2)}
            </text>
          ) : null}
        </g>
      ))}
    </svg>
  )
}

export function SemanticThemeExplorer({
  corpusId,
  analysis,
  onOpenEvidence,
}: SemanticThemeExplorerProps) {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [microscopeMessageId, setMicroscopeMessageId] = useState<string | null>(null)
  const themes = analysis?.themes ?? []
  const selected = themes.find((theme) => theme.theme_id === selectedId) ?? themes[0]

  return (
    <section className="observatory-panel semantic-explorer" aria-label="Динамика семантических тем">
      <header>
        <div>
          <span className="panel-kicker">Семантическая эволюция · provisional</span>
          <div className="panel-title-row">
            <h2>О чём говорили — и когда это менялось</h2>
            <MetricTip title="Семантические темы">
              Сообщения объединяются сначала в эпизоды по паузам, затем русские слова лемматизируются, а эпизоды группируются по TF-IDF-представлениям. Линия показывает долю всех сообщений месяца, попавших в тему.
            </MetricTip>
          </div>
        </div>
        {analysis ? (
          <div className="semantic-quality">
            <span>
              {number.format(analysis.episode_count)} окон · {number.format(analysis.structural_episode_count)} сессий
              <MetricTip title="Тематические окна">
                Сессии разделены паузой более восьми часов, а длинные сессии — на локальные окна до 40 последовательных сообщений. Это не позволяет одному длинному дню разговора скрыть смену тем внутри него.
              </MetricTip>
            </span>
            <span>
              <i className={`semantic-separation ${analysis.separation_quality}`}>
                {qualityLabels[analysis.separation_quality]}
              </i>
              · silhouette {analysis.silhouette === null ? '—' : analysis.silhouette.toFixed(2)}
              <MetricTip title="Silhouette">
                {`${analysis.quality_note} Silhouette — внутренняя мера от −1 до 1; она не подтверждает смысл названий тем.`}
              </MetricTip>
            </span>
          </div>
        ) : null}
      </header>

      {!analysis || !selected ? (
        <div className="semantic-empty">
          Семантический слой отсутствует в этом аналитическом снимке. Пересчитайте обзор новой версией.
        </div>
      ) : (
        <>
          <div className="semantic-layout">
          <nav className="semantic-theme-list" aria-label="Автоматические темы">
            {themes.map((theme, index) => (
              <button
                type="button"
                key={theme.theme_id}
                className={theme.theme_id === selected.theme_id ? 'active' : ''}
                aria-pressed={theme.theme_id === selected.theme_id}
                onClick={() => {
                  setSelectedId(theme.theme_id)
                  setMicroscopeMessageId(null)
                }}
              >
                <span>Тема {index + 1}</span>
                <strong>{theme.label}</strong>
                <small>
                  {number.format(theme.messages)} сообщений · {number.format(theme.episodes)} окон
                </small>
              </button>
            ))}
          </nav>

          <div className="semantic-detail">
            <div className="semantic-heading">
              <div>
                <span>Выбранная тема</span>
                <h3>{selected.label}</h3>
              </div>
              <div className="semantic-terms">
                {selected.terms.slice(0, 8).map((term) => <span key={term}>{term}</span>)}
              </div>
            </div>

            <ThemeTrajectory theme={selected} />

            <div className="semantic-explanation-grid">
              <section>
                <h4>
                  Обнаруженные изменения
                  <MetricTip title="Изменение темы">
                    Необычный месячный скачок доли темы относительно её обычных колебаний. Устойчивость показывает, сколько следующих месяцев доля оставалась по новую сторону порога; причина не устанавливается.
                  </MetricTip>
                </h4>
                {selected.change_points.length ? (
                  selected.change_points.slice(0, 4).map((change) => (
                    <div className="semantic-change" key={`${change.month}-${change.direction}`}>
                      {change.direction === 'increase' ? <ArrowUpRight /> : <ArrowDownRight />}
                      <strong>{change.month}</strong>
                      <span>{percent.format(change.previous_share)} → {percent.format(change.share)}</span>
                      <small>устойчивость: {change.persistence_months} мес.</small>
                    </div>
                  ))
                ) : <p>На доступной временной шкале резких устойчивых сдвигов не найдено.</p>}
              </section>

              <section>
                <h4>
                  Кто участвовал в теме
                  <MetricTip title="Участники темы">
                    Доля сообщений участника внутри эпизодов этой темы. Это участие в тематических эпизодах, а не авторство темы, экспертность или влияние.
                  </MetricTip>
                </h4>
                {selected.top_participants.slice(0, 6).map((participant) => (
                  <div className="semantic-participant" key={participant.participant_id}>
                    <ParticipantIdentityPopover
                      participantId={participant.participant_id}
                      name={participant.participant}
                      onOpenEvidence={onOpenEvidence}
                    />
                    <i><b style={{ width: `${Math.max(participant.share * 100, 1)}%` }} /></i>
                    <strong>{percent.format(participant.share)}</strong>
                  </div>
                ))}
              </section>

              <section>
                <h4>
                  Репрезентативные сообщения
                  <MetricTip title="Репрезентативное сообщение">
                    Сообщение, наиболее близкое к центру темы внутри одного из типичных эпизодов. Оно служит проверяемым примером, но не исчерпывает тему.
                  </MetricTip>
                </h4>
                <div className="semantic-evidence-buttons">
                  {selected.representative_message_ids.map((messageId, index) => (
                    <div key={messageId}>
                      <button type="button" onClick={() => setMicroscopeMessageId(messageId)}>
                        Разобрать {index + 1}<ScanSearch />
                      </button>
                      <button type="button" onClick={() => onOpenEvidence(messageId)}>
                        Источник<ExternalLink />
                      </button>
                    </div>
                  ))}
                </div>
              </section>
            </div>
          </div>
          </div>
          {microscopeMessageId ? (
            <EpisodeMicroscope
              corpusId={corpusId}
              messageId={microscopeMessageId}
              onClose={() => setMicroscopeMessageId(null)}
              onOpenEvidence={onOpenEvidence}
            />
          ) : null}
        </>
      )}
      <p className="guardrail"><AlertTriangle /> {analysis?.guardrail ?? 'Слой ещё не рассчитан.'}</p>
    </section>
  )
}
