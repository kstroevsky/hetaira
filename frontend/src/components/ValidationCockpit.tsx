import { ShieldCheck } from 'lucide-react'

import type { AnnotationSetStatistics } from '../api/types'

type ValidationCockpitProps = {
  setName: string | undefined
  statistics: AnnotationSetStatistics | undefined
}

export function ValidationCockpit({ setName, statistics }: ValidationCockpitProps) {
  const splitValue = statistics
    ? `${statistics.split_counts.train ?? 0} / ${statistics.split_counts.development ?? 0} / ${statistics.split_counts.test ?? 0}`
    : '—'
  const confirmedValue = statistics
    ? `${statistics.confirmed_units} / ${statistics.total_units}`
    : '—'
  const doubleValue = statistics
    ? `${statistics.double_annotation.completed} / ${statistics.double_annotation.required}`
    : '—'
  const agreementValue = statistics?.agreement.raw_rate == null
    ? '—'
    : `${Math.round(statistics.agreement.raw_rate * 100)}%`
  return (
    <section className="validation-cockpit" aria-label="Контроль научной валидации">
      <header>
        <div><ShieldCheck /><span>VALIDATION GATE</span><strong>{setName}</strong></div>
        <i className={statistics?.freeze_ready ? 'ready' : ''}>
          {statistics?.freeze_ready ? 'готов к заморозке' : 'сбор gold продолжается'}
        </i>
      </header>
      <div>
        <ValidationMetric label="Train / dev / test" value={splitValue} />
        <ValidationMetric label="Подтверждённые единицы" value={confirmedValue} />
        <ValidationMetric label="Двойная разметка" value={doubleValue} />
        <ValidationMetric label="Сырые совпадения" value={agreementValue} />
        <ValidationMetric
          label="Сложные случаи"
          value={statistics ? String(statistics.difficult_units) : '—'}
        />
      </div>
    </section>
  )
}

function ValidationMetric({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>
}
