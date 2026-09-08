import { AlertTriangle, Check, Snowflake, X } from 'lucide-react'

import type {
  AnnotationSet,
  AnnotationSetStatistics,
  AnnotationUnit,
  AnnotationUnitContext,
  JudgmentAnnotationDraft,
} from '../api/types'
import { ValidationCockpit } from './ValidationCockpit'

const kinds = [
  ['dialogue_act', 'Диалоговый акт'],
  ['proposition', 'Пропозиция'],
  ['stance', 'Позиция'],
  ['epistemic_state', 'Эпистемика'],
  ['grounding', 'Общее знание'],
  ['argumentation', 'Аргументация'],
  ['reply_target', 'Цель ответа'],
  ['discourse_relation', 'Дискурсивная связь'],
] as const

type AnnotationDeskProps = {
  sets: AnnotationSet[]
  activeSetId: string
  activeSet: AnnotationSet | undefined
  statistics: AnnotationSetStatistics | undefined
  usesTaskJudgments: boolean
  singleFinal: boolean
  unitContext: AnnotationUnitContext | undefined
  units: AnnotationUnit[]
  selectedUnit: AnnotationUnit | undefined
  kind: string
  label: string
  start: number
  end: number
  annotator: string
  reviewer: string
  slot: 'A' | 'B' | 'FINAL'
  judgmentStatus: 'PRESENT' | 'ABSENT' | 'ABSTAIN'
  draftAnnotations: JudgmentAnnotationDraft[]
  draftError: string
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
  onSlotChange: (value: 'A' | 'B' | 'FINAL') => void
  onJudgmentStatusChange: (value: 'PRESENT' | 'ABSENT' | 'ABSTAIN') => void
  onAddDraft: () => void
  onRemoveDraft: (draftId: number) => void
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
      {props.usesTaskJudgments ? (
        <label className="judgment-slot">
          Режим
          <select
            value={props.slot}
            onChange={(event) => props.onSlotChange(event.target.value as 'A' | 'B' | 'FINAL')}
          >
            {!props.singleFinal ? <option value="A">Аннотатор A · blind</option> : null}
            {!props.singleFinal && props.selectedUnit?.judgment_progress?.B ? (
              <option value="B">Аннотатор B · blind</option>
            ) : null}
            <option value="FINAL">FINAL · {props.singleFinal ? 'single reference' : 'adjudication'}</option>
          </select>
        </label>
      ) : null}
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
      {props.unitContext ? (
        <div className="annotation-context" aria-label="Контекст anchor-сообщения">
          <header>
            <strong>Контекст эпизода</strong>
            <span>
              {props.unitContext.blind ? `слепой режим ${props.unitContext.slot}` : 'adjudication'}
              {' · '}{props.unitContext.episode_size} сообщений в эпизоде
            </span>
          </header>
          {props.unitContext.messages.map((message) => (
            <article className={message.labelable ? 'anchor' : ''} key={message.message_id}>
              <div>
                <strong>{message.sender_name}</strong>
                <i>{message.context_role}</i>
                <time>{new Date(message.sent_at).toLocaleString('ru-RU')}</time>
              </div>
              <p>{message.text || '∅'}</p>
              <small>{message.labelable ? 'ANCHOR · размечается' : 'CONTEXT · не размечается'}</small>
            </article>
          ))}
        </div>
      ) : null}
      <blockquote>{unit.text}</blockquote>
      <div className="span-controls">
        <label>Начало<input type="number" min={0} max={unit.text.length} value={props.start} onChange={(event) => props.onStartChange(Number(event.target.value))} /></label>
        <label>Конец<input type="number" min={1} max={unit.text.length} value={safeEnd} onChange={(event) => props.onEndChange(Number(event.target.value))} /></label>
        <button type="button" onClick={() => { props.onStartChange(0); props.onEndChange(unit.text.length) }}>Весь текст</button>
      </div>
      <div className="span-preview">{unit.text.slice(props.start, safeEnd)}</div>
      <div className="annotation-form">
        {props.usesTaskJudgments ? (
          <label>
            Результат задачи
            <select
              value={props.judgmentStatus}
              onChange={(event) => props.onJudgmentStatusChange(
                event.target.value as 'PRESENT' | 'ABSENT' | 'ABSTAIN',
              )}
            >
              <option value="PRESENT">PRESENT</option>
              <option value="ABSENT">ABSENT</option>
              <option value="ABSTAIN">ABSTAIN</option>
            </select>
          </label>
        ) : null}
        <label>Измерение<select value={props.kind} onChange={(event) => props.onKindChange(event.target.value)}>{kinds.map(([value, title]) => <option value={value} key={value}>{title}</option>)}</select></label>
        <label>Метка / тип<input value={props.label} onChange={(event) => props.onLabelChange(event.target.value)} /></label>
        {!props.usesTaskJudgments ? (
          <label>Аннотатор<input value={props.annotator} onChange={(event) => props.onAnnotatorChange(event.target.value)} /></label>
        ) : null}
        {props.usesTaskJudgments && props.judgmentStatus === 'PRESENT' ? (
          <button type="button" className="secondary" onClick={props.onAddDraft}>
            Добавить экземпляр
          </button>
        ) : null}
        <button type="button" onClick={props.onAnnotate} disabled={props.annotatePending}>
          {props.usesTaskJudgments ? 'Сохранить суждение' : 'Сохранить наблюдение'}
        </button>
      </div>
      {props.draftAnnotations.length ? (
        <div className="annotation-drafts" aria-label="Экземпляры текущего суждения">
          {props.draftAnnotations.map((draft, index) => (
            <article key={draft.draft_id}>
              <strong>{draft.kind} #{index + 1}</strong>
              <span>
                span {draft.spans[0]?.start_codepoint}–{draft.spans[0]?.end_codepoint}
              </span>
              <code>{JSON.stringify(draft.value)}</code>
              <button type="button" onClick={() => props.onRemoveDraft(draft.draft_id)}>Убрать</button>
            </article>
          ))}
        </div>
      ) : null}
      {props.draftError || props.annotateError ? (
        <strong className="annotation-error">
          {props.draftError || String(props.annotateError)}
        </strong>
      ) : null}
    </section>
  )
}

function ReviewPanel(props: AnnotationDeskProps) {
  if (props.usesTaskJudgments) {
    return <JudgmentPanel {...props} />
  }
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

function JudgmentPanel(props: AnnotationDeskProps) {
  const judgments = props.unitContext?.judgments ?? []
  return (
    <aside className="review-panel judgment-panel" aria-label="Task completeness и adjudication">
      <div className="annotation-panel-title">
        {props.slot === 'FINAL' ? 'A/B → FINAL' : `Независимое суждение ${props.slot}`}
      </div>
      <label className="reviewer-field">
        {props.slot === 'FINAL' ? 'Эксперт-adjudicator' : `Аннотатор ${props.slot}`}
        <input
          value={props.slot === 'FINAL' ? props.reviewer : props.annotator}
          onChange={(event) => (
            props.slot === 'FINAL'
              ? props.onReviewerChange(event.target.value)
              : props.onAnnotatorChange(event.target.value)
          )}
        />
      </label>
      <div className="judgment-task-list">
        {judgments.map((judgment) => (
          <article key={judgment.id}>
            <header><strong>{judgment.task}</strong><span>{judgment.slot}</span></header>
            <i className={judgment.status.toLocaleLowerCase()}>{judgment.status}</i>
            {judgment.annotator ? <small>{judgment.annotator}</small> : null}
            {judgment.annotations.map((annotation) => (
              <pre key={annotation.id}>{JSON.stringify(annotation.value, null, 2)}</pre>
            ))}
          </article>
        ))}
      </div>
      <div className="freeze-note">
        <Snowflake />
        {props.unitContext?.blind
          ? 'Blind mode: суждения другого аннотатора и FINAL скрыты.'
          : 'FINAL доступен после завершения всех независимых суждений по задаче.'}
      </div>
    </aside>
  )
}
