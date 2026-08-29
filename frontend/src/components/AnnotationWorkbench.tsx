import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Check, DatabaseZap, Snowflake, X } from 'lucide-react'
import { useMemo, useState } from 'react'

import {
  createGoldPilot,
  createManualAnnotation,
  fetchAnnotationSets,
  fetchAnnotationUnits,
  freezeAnnotationSet,
  reviewManualAnnotation,
} from '../api/client'
type AnnotationWorkbenchProps = {
  corpusId: string
  snapshotId: string
}

const kinds = [
  ['dialogue_act', 'Диалоговый акт'],
  ['proposition', 'Пропозиция'],
  ['stance', 'Позиция'],
  ['epistemic_state', 'Эпистемика'],
  ['grounding', 'Общее знание'],
  ['argumentation', 'Аргументация'],
] as const

function annotationValue(kind: string, label: string, selectedText: string) {
  if (kind === 'proposition') return { type: label || 'claim', text: selectedText }
  if (kind === 'stance') return { position: label || 'support', target_resolution: 'manual' }
  return { label: (label || 'ASSERT').toUpperCase() }
}

export function AnnotationWorkbench({ corpusId, snapshotId }: AnnotationWorkbenchProps) {
  const queryClient = useQueryClient()
  const [selectedSetId, setSelectedSetId] = useState('')
  const [selectedUnitId, setSelectedUnitId] = useState('')
  const [kind, setKind] = useState('dialogue_act')
  const [label, setLabel] = useState('ASSERT')
  const [start, setStart] = useState(0)
  const [end, setEnd] = useState(0)
  const [annotator, setAnnotator] = useState('local-annotator')
  const [reviewer, setReviewer] = useState('local-reviewer')

  const setsQuery = useQuery({
    queryKey: ['annotation-sets', corpusId],
    queryFn: () => fetchAnnotationSets(corpusId),
  })
  const activeSetId = selectedSetId || setsQuery.data?.[0]?.id || ''
  const activeSet = setsQuery.data?.find((item) => item.id === activeSetId)
  const unitsQuery = useQuery({
    queryKey: ['annotation-units', activeSetId],
    queryFn: () => fetchAnnotationUnits(activeSetId),
    enabled: Boolean(activeSetId),
  })
  const selectedUnit =
    unitsQuery.data?.find((unit) => unit.id === selectedUnitId) ?? unitsQuery.data?.[0]

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['annotation-sets', corpusId] }),
      queryClient.invalidateQueries({ queryKey: ['annotation-units', activeSetId] }),
    ])
  }
  const createSet = useMutation({
    mutationFn: () => createGoldPilot(corpusId, snapshotId),
    onSuccess: async (created) => {
      setSelectedSetId(created.id)
      await refresh()
    },
  })
  const annotate = useMutation({
    mutationFn: async () => {
      if (!selectedUnit) throw new Error('Выберите единицу разметки')
      const safeEnd = end || selectedUnit.text.length
      return createManualAnnotation(selectedUnit.id, {
        kind,
        value: annotationValue(kind, label, selectedUnit.text.slice(start, safeEnd)),
        spans: [{ start_codepoint: start, end_codepoint: safeEnd }],
        annotator,
      })
    },
    onSuccess: refresh,
  })
  const review = useMutation({
    mutationFn: ({
      annotationId,
      decision,
    }: {
      annotationId: string
      decision: 'confirmed' | 'disputed' | 'rejected'
    }) => reviewManualAnnotation(annotationId, decision, reviewer),
    onSuccess: refresh,
  })
  const freeze = useMutation({
    mutationFn: () => freezeAnnotationSet(activeSetId),
    onSuccess: refresh,
  })

  const summary = useMemo(() => {
    const units = unitsQuery.data ?? []
    return {
      total: units.length,
      pending: units.filter((unit) => unit.status === 'pending').length,
      annotated: units.filter((unit) => unit.status === 'annotated').length,
      reviewed: units.filter((unit) => unit.status === 'reviewed').length,
      disputed: units.filter((unit) => unit.status === 'disputed').length,
    }
  }, [unitsQuery.data])

  if (setsQuery.isLoading) return <div className="annotation-empty">Загружаем наборы…</div>
  if (!setsQuery.data?.length) {
    return (
      <main className="annotation-empty">
        <DatabaseZap aria-hidden="true" />
        <h1>Русский пилот разметки ещё не создан</h1>
        <p>
          Создайте детерминированную выборку до 200 сообщений из активного снимка.
          Группировка train/development/test сохраняет эпизоды целиком.
        </p>
        <button type="button" onClick={() => createSet.mutate()} disabled={createSet.isPending}>
          {createSet.isPending ? 'Создаём…' : 'Создать gold-ru-v0'}
        </button>
        {createSet.error ? <strong className="annotation-error">{String(createSet.error)}</strong> : null}
      </main>
    )
  }

  return (
    <main className="annotation-workbench" aria-label="Рабочее место разметки">
      <header className="annotation-toolbar">
        <div>
          <span>Набор разметки</span>
          <select value={activeSetId} onChange={(event) => setSelectedSetId(event.target.value)}>
            {setsQuery.data.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} · {item.status}
              </option>
            ))}
          </select>
        </div>
        <div className="annotation-stats" aria-label="Состояние выборки">
          <span>Всего <strong>{summary.total}</strong></span>
          <span>Ожидают <strong>{summary.pending}</strong></span>
          <span>Размечены <strong>{summary.annotated}</strong></span>
          <span>Проверены <strong>{summary.reviewed}</strong></span>
          <span>Спорные <strong>{summary.disputed}</strong></span>
        </div>
        <button
          className="freeze-button"
          type="button"
          disabled={!activeSetId || activeSet?.status === 'frozen' || freeze.isPending}
          onClick={() => freeze.mutate()}
        >
          <Snowflake /> {activeSet?.status === 'frozen' ? 'Набор заморожен' : 'Заморозить'}
        </button>
      </header>
      {freeze.error ? <div className="annotation-banner error">{String(freeze.error)}</div> : null}
      <div className="annotation-layout">
        <aside className="unit-queue" aria-label="Очередь единиц разметки">
          <div className="annotation-panel-title">Очередь</div>
          <div className="unit-list">
            {(unitsQuery.data ?? []).map((unit) => (
              <button
                type="button"
                className={unit.id === selectedUnit?.id ? 'unit-card selected' : 'unit-card'}
                key={unit.id}
                onClick={() => {
                  setSelectedUnitId(unit.id)
                  setStart(0)
                  setEnd(unit.text.length)
                }}
              >
                <span>#{unit.ordinal + 1} · {unit.split}</span>
                <strong>{unit.text.slice(0, 90)}</strong>
                <i className={`unit-status ${unit.status}`}>{unit.status}</i>
              </button>
            ))}
          </div>
        </aside>
        <section className="annotation-editor">
          <div className="annotation-panel-title">Источник и спан</div>
          {selectedUnit ? (
            <>
              <div className="unit-metadata">
                <span>revision {selectedUnit.revision_id.slice(0, 8)}</span>
                <span>SHA-256 {selectedUnit.text_hash.slice(0, 12)}…</span>
                <span>{selectedUnit.split}</span>
              </div>
              <blockquote>{selectedUnit.text}</blockquote>
              <div className="span-controls">
                <label>
                  Начало
                  <input
                    type="number"
                    min={0}
                    max={selectedUnit.text.length}
                    value={start}
                    onChange={(event) => setStart(Number(event.target.value))}
                  />
                </label>
                <label>
                  Конец
                  <input
                    type="number"
                    min={1}
                    max={selectedUnit.text.length}
                    value={end || selectedUnit.text.length}
                    onChange={(event) => setEnd(Number(event.target.value))}
                  />
                </label>
                <button type="button" onClick={() => { setStart(0); setEnd(selectedUnit.text.length) }}>
                  Весь текст
                </button>
              </div>
              <div className="span-preview">
                {selectedUnit.text.slice(start, end || selectedUnit.text.length)}
              </div>
              <div className="annotation-form">
                <label>
                  Измерение
                  <select value={kind} onChange={(event) => setKind(event.target.value)}>
                    {kinds.map(([value, title]) => <option value={value} key={value}>{title}</option>)}
                  </select>
                </label>
                <label>
                  Метка / тип
                  <input value={label} onChange={(event) => setLabel(event.target.value)} />
                </label>
                <label>
                  Аннотатор
                  <input value={annotator} onChange={(event) => setAnnotator(event.target.value)} />
                </label>
                <button type="button" onClick={() => annotate.mutate()} disabled={annotate.isPending}>
                  Сохранить наблюдение
                </button>
              </div>
              {annotate.error ? <strong className="annotation-error">{String(annotate.error)}</strong> : null}
            </>
          ) : <p>В наборе нет единиц.</p>}
        </section>
        <aside className="review-panel" aria-label="Проверка и adjudication">
          <div className="annotation-panel-title">Проверка</div>
          <label className="reviewer-field">
            Проверяющий
            <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} />
          </label>
          {selectedUnit?.annotations.length ? selectedUnit.annotations.map((annotation) => (
            <article className="review-card" key={annotation.id}>
              <header>
                <strong>{annotation.kind}</strong>
                <span>{annotation.role}</span>
              </header>
              <pre>{JSON.stringify(annotation.value, null, 2)}</pre>
              {annotation.review ? (
                <div className={`review-decision ${annotation.review.decision}`}>
                  {annotation.review.decision} · {annotation.review.reviewer}
                </div>
              ) : (
                <div className="review-actions">
                  <button aria-label="Подтвердить" type="button" onClick={() => review.mutate({ annotationId: annotation.id, decision: 'confirmed' })}><Check /></button>
                  <button aria-label="Оспорить" type="button" onClick={() => review.mutate({ annotationId: annotation.id, decision: 'disputed' })}><AlertTriangle /></button>
                  <button aria-label="Отклонить" type="button" onClick={() => review.mutate({ annotationId: annotation.id, decision: 'rejected' })}><X /></button>
                </div>
              )}
            </article>
          )) : <p className="review-empty">Сначала создайте наблюдение с точным спаном.</p>}
          {review.error ? <strong className="annotation-error">{String(review.error)}</strong> : null}
          <div className="freeze-note">
            <Snowflake /> Заморозка доступна только после подтверждения каждой единицы.
          </div>
        </aside>
      </div>
    </main>
  )
}
