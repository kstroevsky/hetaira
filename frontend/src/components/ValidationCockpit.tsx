import { ShieldCheck } from 'lucide-react'

import type { AnnotationSetStatistics } from '../api/types'
import { MethodTip } from './MethodTip'
import { MetricTip } from './MetricTip'

type ValidationCockpitProps = {
  setName: string | undefined
  statistics: AnnotationSetStatistics | undefined
}

const taskLabels: Record<string, string> = {
  dialogue_act: 'Диалоговые акты',
  proposition: 'Пропозиции',
  stance: 'Позиция',
  epistemic_state: 'Эпистемика',
  grounding: 'Grounding',
  argumentation: 'Аргументация',
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
        <div><ShieldCheck /><span>VALIDATION GATE</span><MethodTip tip="validationGate" /><strong>{setName}</strong></div>
        <i className={statistics?.freeze_ready ? 'ready' : ''}>
          {statistics?.freeze_ready ? 'готов к заморозке' : 'сбор gold продолжается'}
        </i>
      </header>
      <div>
        <ValidationMetric label="Train / dev / test" value={splitValue} tip="Разделение reference-данных: train используют для настройки, development — для выбора решений, test — только для финальной независимой проверки." />
        <ValidationMetric label="Подтверждённые единицы" value={confirmedValue} tip="Число единиц, для которых существует итоговое проверенное суждение, относительно всей выборки." />
        <ValidationMetric label="Двойная разметка" value={doubleValue} tip="Сколько единиц независимо проверили два аннотатора. Независимость нужна, чтобы измерить воспроизводимость кодбука." />
        <ValidationMetric label="Сырые совпадения" value={agreementValue} tip="Доля одинаковых решений A и B без поправки на случайное совпадение. Показатель читают вместе с типом задачи и числом примеров." />
        <ValidationMetric
          label="Сложные случаи"
          value={statistics ? String(statistics.difficult_units) : '—'}
          tip="Единицы с расхождением, воздержанием или другой причиной для отдельного разбора при adjudication."
        />
      </div>
      {statistics?.task_completion ? (
        <div className="task-gate-grid" aria-label="Полнота обязательных задач">
          {Object.entries(statistics.task_completion).map(([task, progress]) => (
            <div key={task}>
              <span>{taskLabels[task] ?? task}</span>
              <strong>{progress.completed} / {progress.required}</strong>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  )
}

function ValidationMetric({ label, value, tip }: { label: string; value: string; tip: string }) {
  return <div><span className="method-heading">{label}<MetricTip title={label}>{tip}</MetricTip></span><strong>{value}</strong></div>
}
