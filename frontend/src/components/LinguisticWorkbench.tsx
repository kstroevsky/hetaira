import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Braces, Play } from 'lucide-react'
import { useState } from 'react'

import { createLinguisticRun, fetchMessageLinguistics } from '../api/client'
import type { LinguisticAnnotation, MessageItem } from '../api/types'
import { ArtifactDetails } from './ArtifactDetails'
import { MethodTip } from './MethodTip'

type LinguisticWorkbenchProps = {
  corpusId: string
  messages: MessageItem[]
  initialMessageId: string
  onOpenEvidence: (messageId: string) => void
}

type Token = {
  id: number
  text: string
  lemma: string
  upos: string
  grammemes: string[]
  start_codepoint: number
  end_codepoint: number
}

type LinguisticFeatures = {
  tokens: Token[]
  noun_phrases: Array<{ start_codepoint: number; end_codepoint: number; token_ids: number[] }>
  negation_scopes: Array<{
    marker_token_id: number
    governed_token_id: number | null
    status: string
  }>
  modals: Array<{ token_id: number; lemma: string }>
  capability_status: Record<string, string>
}

type EntityMention = {
  mention_id: string
  text: string
  entity_type: string
  source_basis: string
  start_codepoint: number
  end_codepoint: number
  resolution_status: string
}

function annotationByKind(
  annotations: LinguisticAnnotation[] | undefined,
  kind: string,
): LinguisticAnnotation[] {
  return annotations?.filter((annotation) => annotation.kind === kind) ?? []
}

export function LinguisticWorkbench({
  corpusId,
  messages,
  initialMessageId,
  onOpenEvidence,
}: LinguisticWorkbenchProps) {
  const client = useQueryClient()
  const [selectedMessageId, setSelectedMessageId] = useState(initialMessageId)
  const effectiveMessageId = selectedMessageId || initialMessageId || messages[0]?.id || ''
  const analysisQuery = useQuery({
    queryKey: ['message-linguistics', corpusId, effectiveMessageId],
    queryFn: () => fetchMessageLinguistics(corpusId, effectiveMessageId),
    enabled: Boolean(effectiveMessageId),
    retry: false,
  })
  const createRun = useMutation({
    mutationFn: () => createLinguisticRun(corpusId),
    onSuccess: () => client.invalidateQueries({ queryKey: ['message-linguistics', corpusId] }),
  })

  if (analysisQuery.error && !analysisQuery.data) {
    return (
      <main className="linguistic-empty" aria-label="Лингвистический анализ">
        <Braces aria-hidden="true" />
        <h1>Лингвистические признаки ещё не рассчитаны</h1>
        <p>
          Локальная базовая обработка добавит токены, леммы, части речи, морфологию,
          языковые маркеры и неопределённые кандидаты кореференции.
        </p>
        <button type="button" onClick={() => createRun.mutate()} disabled={createRun.isPending}>
          <Play /> {createRun.isPending ? 'Анализируем…' : 'Запустить анализ'}
        </button>
      </main>
    )
  }
  if (analysisQuery.isLoading || !analysisQuery.data) {
    return <main className="linguistic-empty">Загружаем лингвистический слой…</main>
  }

  const analysis = analysisQuery.data
  const featureAnnotation = annotationByKind(analysis.annotations, 'linguistic_features')[0]
  const features = featureAnnotation?.value as LinguisticFeatures | undefined
  const mentions = annotationByKind(analysis.annotations, 'entity_mention')
  const coreference = annotationByKind(analysis.annotations, 'coreference_candidates')
  const parser = annotationByKind(analysis.annotations, 'linguistic_parser_output')[0]
  const selectedMessage = messages.find((message) => message.id === effectiveMessageId)
  const parserTask = analysis.run.tasks.find((task) => task.task_key === 'local_parser')

  return (
    <main className="linguistic-workbench" aria-label="Лингвистический анализ">
      <header className="linguistic-header">
        <div>
          <span>PROVISIONAL · RUSSIAN-FIRST · L1</span>
          <h1>Морфосинтаксис и сущности</h1>
          <p>{analysis.guardrail}</p>
        </div>
        <div>
          <strong>{analysis.run.status}</strong>
          <small>локальный parser: {parserTask?.status ?? '—'}</small>
        </div>
      </header>
      <div className="linguistic-layout">
        <aside className="linguistic-message-list">
          {messages.map((message) => (
            <button
              className={message.id === effectiveMessageId ? 'selected' : ''}
              key={message.id}
              type="button"
              onClick={() => setSelectedMessageId(message.id)}
            >
              <small>{message.sender_name} · #{message.external_id}</small>
              <span>{message.text || '∅'}</span>
            </button>
          ))}
        </aside>
        <section className="linguistic-analysis-pane">
          <article className="linguistic-source">
            <header>
              <strong>{selectedMessage?.sender_name}</strong>
              <button type="button" onClick={() => onOpenEvidence(effectiveMessageId)}>
                Открыть источник
              </button>
            </header>
            <p>{selectedMessage?.text}</p>
            <code>revision {analysis.revision_id}</code>
          </article>

          <section className="linguistic-panel">
            <header><h2 className="method-heading">Токены и морфология <MethodTip tip="tokensMorphology" /></h2><span>pymorphy3 baseline</span></header>
            <div className="token-table" role="table" aria-label="Токены и морфология">
              {features?.tokens.map((token) => (
                <div role="row" key={token.id}>
                  <strong>{token.text}</strong>
                  <span>{token.lemma}</span>
                  <code>{token.upos}</code>
                  <small>{token.grammemes.join(' · ') || '—'}</small>
                  <i>{token.start_codepoint}:{token.end_codepoint}</i>
                </div>
              ))}
            </div>
          </section>

          <div className="linguistic-columns">
            <section className="linguistic-panel">
              <header><h2 className="method-heading">Интерпретируемые признаки <MethodTip tip="interpretableFeatures" /></h2></header>
              <dl>
                <div><dt>Именные группы</dt><dd>{features?.noun_phrases.length ?? 0}</dd></div>
                <div><dt>Области отрицания</dt><dd>{features?.negation_scopes.length ?? 0}</dd></div>
                <div><dt>Модальные маркеры</dt><dd>{features?.modals.length ?? 0}</dd></div>
              </dl>
              <pre>{JSON.stringify({ noun_phrases: features?.noun_phrases, negation_scopes: features?.negation_scopes, modals: features?.modals }, null, 2)}</pre>
              <div className="capability-grid">
                {Object.entries(features?.capability_status ?? {}).map(([name, status]) => (
                  <span className={status.startsWith('unavailable') ? 'unavailable' : ''} key={name}>
                    {name}<strong>{status}</strong>
                  </span>
                ))}
              </div>
            </section>
            <section className="linguistic-panel">
              <header><h2 className="method-heading">Упоминания сущностей <MethodTip tip="entityMentions" /></h2><span>{mentions.length}</span></header>
              <div className="entity-list">
                {mentions.map((annotation) => {
                  const mention = annotation.value as EntityMention
                  return (
                    <article key={annotation.id}>
                      <strong>{mention.text}</strong><span>{mention.entity_type}</span>
                      <small>{mention.source_basis} · {mention.resolution_status}</small>
                    </article>
                  )
                })}
              </div>
            </section>
          </div>

          <section className="linguistic-panel">
            <header><h2 className="method-heading">Кандидаты кореференции <MethodTip tip="coreference" /></h2><span>не калибровано</span></header>
            {coreference.length ? coreference.map((annotation) => (
              <article className="coreference-row" key={annotation.id}>
                <strong>{String(annotation.value.mention_id)}</strong>
                <span>принятая цель: отсутствует</span>
                <code>{JSON.stringify(annotation.alternatives)}</code>
              </article>
            )) : <p className="linguistic-empty-row">Для сообщения нет предложенных антецедентов.</p>}
          </section>

          {parser ? (
            <section className="linguistic-panel">
              <header><h2 className="method-heading">Локальный dependency / NER / SRL <MethodTip tip="localParser" /></h2><span>pinned model</span></header>
              <pre>{JSON.stringify(parser.value, null, 2)}</pre>
            </section>
          ) : null}
          <ArtifactDetails value={analysis} />
        </section>
      </div>
    </main>
  )
}
