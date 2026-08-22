import { Check, Circle, Pause, Square } from 'lucide-react'

import type { Run } from '../api/types'

type RunStripProps = { run: Run | null; messageCount: number }

const stages = [
  { title: 'Загрузка', complete: true },
  { title: 'Предобработка', complete: true },
  { title: 'Разметка', complete: true },
  { title: 'Агрегация', complete: false },
  { title: 'Отчёты', complete: false },
]

export function RunStrip({ run, messageCount }: RunStripProps) {
  return (
    <footer className="run-strip">
      <div className="run-identity">
        <span>Текущий запуск</span>
        <strong>{run?.id.slice(0, 13) ?? 'нет запуска'}</strong>
        <small>
          <i /> {run?.status === 'completed' ? 'Завершён' : 'Ожидание'}
        </small>
      </div>
      <div className="pipeline">
        <span className="pipeline-label">Пайплайн</span>
        {stages.map((stage, index) => (
          <div className="pipeline-step" key={stage.title}>
            {index ? <span className="pipeline-arrow">→</span> : null}
            <div className={stage.complete ? 'step-icon done' : 'step-icon'}>
              {stage.complete ? <Check /> : <Circle />}
            </div>
            <div>
              <strong>{stage.title}</strong>
              <span>{stage.complete ? `${messageCount} / ${messageCount}` : '—'}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="run-actions">
        <span>
          Готово
          <br />
          <strong>{Math.round((run?.progress ?? 0) * 100)}%</strong>
        </span>
        <Pause />
        <Square />
      </div>
    </footer>
  )
}
