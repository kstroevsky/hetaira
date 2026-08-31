import { CircleHelp } from 'lucide-react'

export function MetricTip({ title, children }: { title: string; children: string }) {
  return (
    <details className="metric-tip">
      <summary aria-label={`Что означает: ${title}`} title={`Что означает: ${title}`}>
        <CircleHelp aria-hidden="true" />
      </summary>
      <div role="note"><strong>{title}</strong><p>{children}</p></div>
    </details>
  )
}
