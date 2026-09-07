import { AlertTriangle, Check, Snowflake, X } from 'lucide-react'

import type { AnnotationSet, AnnotationSetStatistics, AnnotationUnit } from '../api/types'
import { ValidationCockpit } from './ValidationCockpit'

const kinds = [
  ['dialogue_act', 'Диалоговый акт'],
  ['proposition', 'Пропозиция'],
  ['stance', 'Позиция'],
  ['epistemic_state', 'Эпистемика'],
  ['grounding', 'Общее знание'],
  ['argumentation', 'Аргументация'],
] as const

type AnnotationDeskProps = {
  sets: AnnotationSet[]
  activeSetId: string
  activeSet: AnnotationSet | undefined
  statistics: AnnotationSetStatistics | undefined
  units: AnnotationUnit[]
  selectedUnit: AnnotationUnit | undefined
  kind: string
  label: string
  start: number
  end: number
  annotator: string
  reviewer: string
  freezePending: boolean
  annotatePending: boolean
  freezeError: unknown
  annotateError: unknown
  reviewError: unknown
  onSetChange: (value: string) => void
  onUnitSelect: (unit: AnnotationUnit) => void
  onKindChange: (value: string) => void
  onLabelChange: (value: string) => void
  onStartChange: (value: number) => void
  onEndChange: (value: number) => void
  onAnnotatorChange: (value: string) => void
  onReviewerChange: (value: string) => void
  onAnnotate: () => void
  onReview: (annotationId: string, decision: 'confirmed' | 'disputed' | 'rejected') => void
  onFreeze: () => void
}

export function AnnotationDesk(props: AnnotationDeskProps) {
  return (
    <main className="annotation-workbench" aria-label="Рабочее место разметки">
      <DeskToolbar {...props} />
      {props.freezeError ? <div className="annotation-banner error">{String(props.freezeError)}</div> : null}
      <ValidationCockpit setName={props.activeSet?.name} statistics={props.statistics} />
      <div className="annotation-layout">
        <UnitQueue {...props} />
        <AnnotationEditor {...props} />
        <ReviewPanel {...props} />
      </div>
    </main>
  )
}

function DeskToolbar(props: AnnotationDeskProps) {
  const statusCounts = props.statistics?.status_counts ?? {}
  return (
    <header className="annotation-toolbar">
      <div>
        <span>Набор разметки</span>
        <select value={props.activeSetId} onChange={(event) => props.onSetChange(event.target.value)}>
          {props.sets.map((item) => (
            <option key={item.id} value={item.id}>{item.name} · {item.status}</option>
          ))}
        </select>
      </div>
      <div className="annotation-stats" aria-label="Состояние выборки">
        <span>Всего <strong>{props.statistics?.total_units ?? '—'}</strong></span>
        <span>Ожидают <strong>{statusCounts.pending ?? 0}</strong></span>
        <span>Размечены <strong>{statusCounts.annotated ?? 0}</strong></span>
        <span>Проверены <strong>{statusCounts.reviewed ?? 0}</strong></span>
        <span>Спорные <strong>{statusCounts.disputed ?? 0}</strong></span>
      </div>
      <button
        className="freeze-button"
        type="button"
        disabled={!props.activeSetId || props.activeSet?.status === 'frozen' || props.freezePending}
        onClick={props.onFreeze}
      >
        <Snowflake /> {props.activeSet?.status === 'frozen' ? 'Набор заморожен' : 'Заморозить'}
      </button>
    </header>
  )
}

function UnitQueue(props: AnnotationDeskProps) {
  const hasHiddenUnits = Boolean(
    props.statistics && props.statistics.total_units > props.units.length,
  )
  return (
    <aside className="unit-queue" aria-label="Очередь единиц разметки">
      <div className="annotation-panel-title">
        Очередь
        {hasHiddenUnits ? (
          <small>первые {props.units.length} из {props.statistics?.total_units}</small>
        ) : null}
      </div>
      <div className="unit-list">
        {props.units.map((unit) => (
          <button
            type="button"
            className={unit.id === props.selectedUnit?.id ? 'unit-card selected' : 'unit-card'}
            key={unit.id}
            onClick={() => props.onUnitSelect(unit)}
          >
            <span>
              #{unit.ordinal + 1} · {unit.split}
              {unit.strata.double_annotation_required ? ' · DOUBLE' : ''}
            </span>
            <strong>{unit.text.slice(0, 90)}</strong>
            <i className={`unit-status ${unit.status}`}>{unit.status}</i>
          </button>
        ))}
      </div>
    </aside>
  )
}

function AnnotationEditor(props: AnnotationDeskProps) {
  const unit = props.selectedUnit
  if (!unit) {
    return <section className="annotation-editor"><p>В наборе нет единиц.</p></section>
  }
  const safeEnd = props.end || unit.text.length
  return (
    <section className="annotation-editor">
      <div className="annotation-panel-title">Источник и спан</div>
      <div className="unit-metadata">
        <span>revision {unit.revision_id.slice(0, 8)}</span>
        <span>SHA-256 {unit.text_hash.slice(0, 12)}…</span>
        <span>{unit.split}</span>
      </div>
      <blockquote>{unit.text}</blockquote>
      <div className="span-controls">
        <label>Начало<input type="number" min={0} max={unit.text.length} value={props.start} onChange={(event) => props.onStartChange(Number(event.target.value))} /></label>
        <label>Конец<input type="number" min={1} max={unit.text.length} value={safeEnd} onChange={(event) => props.onEndChange(Number(event.target.value))} /></label>
        <button type="button" onClick={() => { props.onStartChange(0); props.onEndChange(unit.text.length) }}>Весь текст</button>
      </div>
      <div className="span-preview">{unit.text.slice(props.start, safeEnd)}</div>
      <div className="annotation-form">
        <label>Измерение<select value={props.kind} onChange={(event) => props.onKindChange(event.target.value)}>{kinds.map(([value, title]) => <option value={value} key={value}>{title}</option>)}</select></label>
        <label>Метка / тип<input value={props.label} onChange={(event) => props.onLabelChange(event.target.value)} /></label>
        <label>Аннотатор<input value={props.annotator} onChange={(event) => props.onAnnotatorChange(event.target.value)} /></label>
        <button type="button" onClick={props.onAnnotate} disabled={props.annotatePending}>Сохранить наблюдение</button>
      </div>
      {props.annotateError ? <strong className="annotation-error">{String(props.annotateError)}</strong> : null}
    </section>
  )
}

function ReviewPanel(props: AnnotationDeskProps) {
  const annotations = props.selectedUnit?.annotations ?? []
  return (
    <aside className="review-panel" aria-label="Проверка и adjudication">
      <div className="annotation-panel-title">Проверка</div>
      <label className="reviewer-field">Проверяющий<input value={props.reviewer} onChange={(event) => props.onReviewerChange(event.target.value)} /></label>
      {annotations.length ? annotations.map((annotation) => (
        <article className="review-card" key={annotation.id}>
          <header><strong>{annotation.kind}</strong><span>{annotation.role}</span></header>
          <pre>{JSON.stringify(annotation.value, null, 2)}</pre>
          {annotation.review ? (
            <div className={`review-decision ${annotation.review.decision}`}>{annotation.review.decision} · {annotation.review.reviewer}</div>
          ) : (
            <div className="review-actions">
              <button aria-label="Подтвердить" type="button" onClick={() => props.onReview(annotation.id, 'confirmed')}><Check /></button>
              <button aria-label="Оспорить" type="button" onClick={() => props.onReview(annotation.id, 'disputed')}><AlertTriangle /></button>
              <button aria-label="Отклонить" type="button" onClick={() => props.onReview(annotation.id, 'rejected')}><X /></button>
            </div>
          )}
        </article>
      )) : <p className="review-empty">Сначала создайте наблюдение с точным спаном.</p>}
      {props.reviewError ? <strong className="annotation-error">{String(props.reviewError)}</strong> : null}
      <div className="freeze-note"><Snowflake /> Заморозка требует подтверждения каждой единицы и двух аннотаторов для DOUBLE.</div>
    </aside>
  )
}
