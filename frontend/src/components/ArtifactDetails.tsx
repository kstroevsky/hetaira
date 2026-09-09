import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'

import { MethodTip } from './MethodTip'

export function ArtifactDetails({ value, title = 'Полный технический результат' }: {
  value: unknown
  title?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <section className="artifact-details">
      <header className="artifact-details-heading">
        <button aria-expanded={open} onClick={() => setOpen((value) => !value)} type="button">
          {open ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}
          <strong>{title}</strong>
        </button>
        <MethodTip tip="technicalResult" />
      </header>
      {open ? <pre>{JSON.stringify(value, null, 2)}</pre> : null}
    </section>
  )
}
