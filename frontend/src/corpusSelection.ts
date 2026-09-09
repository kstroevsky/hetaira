import type { Corpus } from './api/types'

export function selectDefaultCorpus(corpora: Corpus[] | undefined): Corpus | undefined {
  if (!corpora?.length) return undefined
  return corpora.find((corpus) => corpus.name === 'Psychedelic Renaissance 2.0')
    ?? corpora.find(
      (corpus) => corpus.is_validated_language && corpus.source_type === 'telegram_html',
    )
    ?? corpora.find((corpus) => corpus.is_validated_language && corpus.language === 'ru')
    ?? corpora.find((corpus) => corpus.language === 'ru')
    ?? corpora[0]
}
