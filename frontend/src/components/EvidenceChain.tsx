import { ChevronUp } from 'lucide-react'

import type { EvidenceStage, Microscope } from '../api/types'
import { MethodTip } from './MethodTip'

type EvidenceChainProps = { microscope: Microscope }

function itemText(stage: EvidenceStage, item: Record<string, unknown>): string {
  if (stage.level === 'L0') {
    return `Сообщение ${String(item.external_id)} · ${String(item.text_hash).slice(0, 10)}…`
  }
  if (stage.level === 'L1') {
    const value = item.value as Record<string, unknown> | undefined
    return String(value?.label ?? value?.text ?? item.kind ?? 'Наблюдение')
  }
  if (stage.level === 'L2') {
    return `${String(item.definition_id)} · n=${String(item.sample_size ?? '—')}`
  }
  return String(item.claim ?? 'Интерпретация не сформирована')
}

function itemKey(stage: EvidenceStage, item: Record<string, unknown>): string {
  const value = item.value as Record<string, unknown> | undefined
  return [
    stage.level,
    item.message_id,
    item.external_id,
    item.definition_id,
    item.claim,
    item.kind,
    value?.label,
    value?.text,
  ]
    .filter(Boolean)
    .join(':')
}

export function EvidenceChain({ microscope }: EvidenceChainProps) {
  return (
    <aside className="evidence-pane" aria-label="Цепочка доказательств">
      <div className="pane-heading">
        <h2 className="method-heading">
          Цепочка доказательств <MethodTip tip="evidenceChain" />
        </h2>
        <button className="plain-icon" type="button" aria-label="Свернуть панель">
          <ChevronUp />
        </button>
      </div>
      <div className="evidence-chain">
        {microscope.evidence_chain.map((stage, index) => (
          <section className={`evidence-stage level-${index}`} key={stage.level}>
            <span className="level-code">{stage.level}</span>
            <div className="stage-content">
              <div className="stage-heading">
                <strong>{stage.title}</strong>
                <span>{stage.items.length}</span>
              </div>
              {stage.items.slice(0, 3).map((item) => (
                <div className="stage-item" key={itemKey(stage, item)}>
                  {itemText(stage, item)}
                </div>
              ))}
              {stage.items.length > 3 ? (
                <button type="button">Показать ещё {stage.items.length - 3}</button>
              ) : null}
            </div>
          </section>
        ))}
      </div>
      <CaseList
        title={`Подтверждающие случаи (${microscope.supporting_cases.length})`}
        items={microscope.supporting_cases}
        tone="support"
      />
      <CaseList
        title={`Кодбук: сложные отрицательные примеры (${microscope.counterexamples.length})`}
        items={microscope.counterexamples}
        tone="counter"
      />
    </aside>
  )
}

function CaseList({
  title,
  items,
  tone,
}: {
  title: string
  items: Array<Record<string, unknown>>
  tone: 'support' | 'counter'
}) {
  return (
    <section className={`case-list ${tone}`}>
      <div className="case-heading">
        <strong>{title}</strong>
        <button type="button">Смотреть все</button>
      </div>
      {items.length ? (
        items.map((item) => (
          <div className="case-row" key={String(item.annotation_id ?? item.text)}>
            <span>{String(item.text ?? '').slice(0, 62)}</span>
            <strong>{Number(item.confidence ?? 0).toFixed(2)}</strong>
          </div>
        ))
      ) : (
        <p>
          {tone === 'counter'
            ? 'Для этой задачи нет размеченных сложных отрицательных примеров.'
            : 'Нет доступных подтверждающих случаев.'}
        </p>
      )}
    </section>
  )
}
