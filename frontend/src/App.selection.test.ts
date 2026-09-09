import { describe, expect, it } from 'vitest'

import type { Corpus } from './api/types'
import { selectDefaultCorpus } from './corpusSelection'

const corpus = (overrides: Partial<Corpus>): Corpus => ({
  id: 'corpus',
  name: 'Corpus',
  language: 'ru',
  source_type: 'telegram',
  privacy_policy: 'LOCAL_ONLY',
  is_validated_language: true,
  created_at: '2026-01-01T00:00:00Z',
  ...overrides,
})

describe('selectDefaultCorpus', () => {
  it('prefers Psychedelic Renaissance over synthetic demos', () => {
    const synthetic = corpus({ id: 'synthetic', name: 'Архив команды · 2024–2026' })
    const psychedelic = corpus({
      id: 'psychedelic',
      name: 'Psychedelic Renaissance 2.0',
      source_type: 'telegram_html',
    })

    expect(selectDefaultCorpus([synthetic, psychedelic])).toBe(psychedelic)
  })

  it('otherwise prefers a validated Telegram HTML corpus', () => {
    const synthetic = corpus({ id: 'synthetic' })
    const imported = corpus({ id: 'imported', name: 'Real export', source_type: 'telegram_html' })

    expect(selectDefaultCorpus([synthetic, imported])).toBe(imported)
  })
})
