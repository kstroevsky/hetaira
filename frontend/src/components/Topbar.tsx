import { Filter, Search, ShieldCheck, Upload } from 'lucide-react'

import type { Corpus } from '../api/types'

type TopbarProps = {
  corpora: Corpus[]
  corpusId: string
  query: string
  onCorpusChange: (id: string) => void
  onQueryChange: (value: string) => void
  onImport: () => void
}

export function Topbar({
  corpora,
  corpusId,
  query,
  onCorpusChange,
  onQueryChange,
  onImport,
}: TopbarProps) {
  return (
    <header className="topbar">
      <label className="corpus-selector">
        <span className="sr-only">Корпус</span>
        <select value={corpusId} onChange={(event) => onCorpusChange(event.target.value)}>
          {corpora.map((corpus) => (
            <option value={corpus.id} key={corpus.id}>
              {corpus.name}
            </option>
          ))}
        </select>
      </label>
      <label className="search-field">
        <Search aria-hidden="true" />
        <span className="sr-only">Поиск</span>
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Поиск по сообщениям, участникам, меткам…"
        />
        <kbd>⌘K</kbd>
      </label>
      <button className="icon-button" type="button" aria-label="Фильтры">
        <Filter aria-hidden="true" />
      </button>
      <div className="topbar-spacer" />
      <div className="privacy-state">
        <ShieldCheck aria-hidden="true" />
        <span>LOCAL ONLY</span>
      </div>
      <button className="import-button" type="button" onClick={onImport}>
        <Upload aria-hidden="true" />
        Импорт
      </button>
      <div className="profile" aria-label="Профиль пользователя">
        AK
      </div>
    </header>
  )
}
