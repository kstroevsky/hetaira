import { ChevronDown, ChevronRight, Copy, GitCompareArrows } from 'lucide-react'
import { useMemo, useState } from 'react'

import type { Annotation, Microscope } from '../api/types'
import { MethodTip } from './MethodTip'

type AnalysisMicroscopeProps = {
  microscope: Microscope
}

const labelTranslations: Record<string, string> = {
  QUESTION: 'Запрос информации',
  PROPOSE: 'Предложение плана действий',
  AGREE: 'Согласие',
  DISAGREE: 'Возражение',
  COMMIT: 'Обязательство',
  ACKNOWLEDGE: 'Сигнал понимания',
  ASSERT: 'Утверждение',
  UNCERTAIN: 'Неуверенность',
  COMMITTED: 'Приверженность утверждению',
  REASON_GIVING: 'Обоснование',
  ACKNOWLEDGED: 'Получено и замечено',
  CLARIFICATION_REQUESTED: 'Запрошено уточнение',
  REPAIRED: 'Исправление понимания',
  support: 'Поддержка целевой пропозиции',
  oppose: 'Возражение против целевой пропозиции',
  suspend: 'Позиция не принята и не отвергнута',
}

function annotationLabel(annotation: Annotation): string {
  const label = String(
    annotation.value.label ??
      annotation.value.position ??
      annotation.value.text ??
      annotation.kind,
  )
  return labelTranslations[label] ?? label
}

function EvidenceText({ microscope }: { microscope: Microscope }) {
  const ranges = useMemo(() => {
    const output: Array<{ start: number; end: number; kind: string }> = []
    for (const section of microscope.sections) {
      for (const annotation of section.annotations) {
        const evidence = annotation.evidence[0]
        if (evidence?.start_codepoint !== undefined && evidence.end_codepoint !== undefined) {
          output.push({
            start: evidence.start_codepoint,
            end: evidence.end_codepoint,
            kind: section.key,
          })
        }
      }
    }
    return output
      .sort((a, b) => a.start - b.start || b.end - a.end)
      .filter(
        (range, index, all) =>
          index === 0 ||
          range.start !== all[index - 1].start ||
          range.end !== all[index - 1].end,
      )
  }, [microscope])
  const text = microscope.message.text
  if (!ranges.length) return <p>{text}</p>
  const parts: React.ReactNode[] = []
  let cursor = 0
  for (const range of ranges) {
    if (range.start < cursor) continue
    if (range.start > cursor) parts.push(text.slice(cursor, range.start))
    parts.push(
      <mark className={`highlight ${range.kind}`} key={`${range.start}-${range.end}`}>
        {text.slice(range.start, range.end)}
      </mark>,
    )
    cursor = range.end
  }
  if (cursor < text.length) parts.push(text.slice(cursor))
  return <p>{parts}</p>
}

export function AnalysisMicroscope({ microscope }: AnalysisMicroscopeProps) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set())
  const [compareOpen, setCompareOpen] = useState(false)
  const toggle = (key: string) => {
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }
  return (
    <section className="microscope-pane" aria-label="Микроскоп анализа">
      <div className="pane-heading microscope-heading">
        <h2 className="method-heading">
          Микроскоп анализа <MethodTip tip="analysisMicroscope" />
        </h2>
        <span className="message-id">ID: {microscope.message.external_id}</span>
      </div>
      <div className="source-block">
        <div className="source-title">
          <strong>Исходный текст сообщения</strong>
          <span>{new Date(microscope.message.sent_at).toLocaleString('ru-RU')}</span>
          <button className="plain-icon" type="button" aria-label="Копировать текст">
            <Copy />
          </button>
        </div>
        <div className="source-text">
          <EvidenceText microscope={microscope} />
        </div>
        <div className="source-foot">
          <span>SHA-256 · {microscope.text_hash.slice(0, 12)}…</span>
          <button type="button">Показать в контексте</button>
        </div>
      </div>
      <div className="annotation-sections">
        {microscope.sections.map((section) => {
          const isCollapsed = collapsed.has(section.key)
          return (
            <section className="annotation-group" key={section.key}>
              <button
                className="annotation-heading"
                type="button"
                onClick={() => toggle(section.key)}
              >
                {isCollapsed ? <ChevronRight /> : <ChevronDown />}
                <strong>{section.title}</strong>
                <span>{section.annotations.length}</span>
                <span className="column-label">Уверенность</span>
                <span className="column-label">Статус</span>
              </button>
              {isCollapsed ? null : (
                <div className="annotation-list">
                  {section.annotations.length ? (
                    section.annotations.map((annotation, index) => (
                      <div className="annotation-row" key={annotation.id}>
                        <span className="ordinal">{index + 1}</span>
                        <span className={`evidence-bar ${section.key}`} />
                        <span className="annotation-name">{annotationLabel(annotation)}</span>
                        <span className="confidence">
                          {annotation.raw_confidence?.toFixed(2) ?? '—'}
                        </span>
                        <span className="status">
                          <i />
                          {annotation.status === 'provisional'
                            ? 'Предварительно'
                            : annotation.status}
                        </span>
                      </div>
                    ))
                  ) : (
                    <div className="empty-annotation">Наблюдений этого типа пока нет.</div>
                  )}
                </div>
              )}
            </section>
          )
        })}
      </div>
      <div className="microscope-footer">
        <label>
          Схема кодирования:
          <select defaultValue="ru-v0.1">
            <option value="ru-v0.1">RU Codebook v0.1</option>
          </select>
        </label>
        <label>
          Модель:
          <select defaultValue="rules">
            <option value="rules">rules-ru-v1</option>
          </select>
        </label>
        <button type="button" onClick={() => setCompareOpen((value) => !value)}>
          <GitCompareArrows /> Сравнить модели
        </button>
      </div>
      {compareOpen ? (
        <div className="compare-notice">
          Подключите локальный или generic HTTP backend, чтобы сопоставить результаты.
          Детерминированная разметка остаётся отдельной версией.
        </div>
      ) : null}
    </section>
  )
}
