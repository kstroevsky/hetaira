import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, GitFork, PauseCircle, Play, RotateCcw, X } from 'lucide-react'
import { useMemo, useState } from 'react'

import {
  cancelConversationGraphRun,
  createConversationGraphReference,
  createConversationGraphRun,
  fetchAnnotationSets,
  fetchConversationGraph,
  fetchConversationGraphEvaluation,
  resumeConversationGraphRun,
  reviewManualAnnotation,
} from '../api/client'
import type {
  AnnotationReview,
  ConversationGraphMessage,
  DiscourseRelation,
  ResponseCandidate,
} from '../api/types'
import { ArtifactDetails } from './ArtifactDetails'
import { MethodTip } from './MethodTip'

type ConversationGraphWorkbenchProps = {
  corpusId: string
  onOpenEvidence: (messageId: string) => void
}

const relationLabels: Record<string, string> = {
  ANSWERS: 'отвечает',
  ELABORATES: 'развивает',
  CONTRASTS: 'противопоставляет',
  ACKNOWLEDGES: 'подтверждает получение',
  CORRECTS: 'исправляет',
  CLARIFIES: 'уточняет',
  ACCEPTS: 'принимает',
  REJECTS: 'отклоняет',
}

function ReviewStatus({ review }: { review: AnnotationReview | null }) {
  if (!review) return <span className="graph-review pending">не проверено</span>
  return <span className={`graph-review ${review.decision}`}>{review.decision}</span>
}

function MessageExcerpt({
  message,
  role,
  onOpen,
}: {
  message: ConversationGraphMessage | undefined
  role: string
  onOpen: () => void
}) {
  if (!message) return <div className="graph-message missing">Источник недоступен</div>
  return (
    <button className="graph-message" type="button" onClick={onOpen}>
      <small>{role} · {message.sender_name} · #{message.external_id}</small>
      <span>{message.text || '∅'}</span>
      <code>revision {message.revision_id.slice(0, 8)} · SHA {message.text_hash.slice(0, 10)}…</code>
    </button>
  )
}

export function ConversationGraphWorkbench({
  corpusId,
  onOpenEvidence,
}: ConversationGraphWorkbenchProps) {
  const client = useQueryClient()
  const [selectedMessageId, setSelectedMessageId] = useState('')
  const [reviewer, setReviewer] = useState('local-reviewer')
  const graphQuery = useQuery({
    queryKey: ['conversation-graph', corpusId, selectedMessageId],
    queryFn: () => fetchConversationGraph(corpusId, selectedMessageId || undefined),
    retry: false,
  })
  const setsQuery = useQuery({
    queryKey: ['annotation-sets', corpusId],
    queryFn: () => fetchAnnotationSets(corpusId),
  })
  const graphReference = setsQuery.data?.find(
    (item) => item.sampling_spec?.judgment_protocol === 'single_final_reference_v1',
  )
  const refresh = () => client.invalidateQueries({ queryKey: ['conversation-graph', corpusId] })
  const createRun = useMutation({
    mutationFn: () => createConversationGraphRun(corpusId, true),
    onSuccess: refresh,
  })
  const cancelRun = useMutation({
    mutationFn: (runId: string) => cancelConversationGraphRun(runId),
    onSuccess: refresh,
  })
  const resumeRun = useMutation({
    mutationFn: (runId: string) => resumeConversationGraphRun(runId),
    onSuccess: refresh,
  })
  const review = useMutation({
    mutationFn: ({ annotationId, decision }: {
      annotationId: string
      decision: 'confirmed' | 'disputed' | 'rejected'
    }) => reviewManualAnnotation(annotationId, decision, reviewer),
    onSuccess: refresh,
  })
  const createReference = useMutation({
    mutationFn: () => createConversationGraphReference(corpusId),
    onSuccess: () => client.invalidateQueries({ queryKey: ['annotation-sets', corpusId] }),
  })
  const messages = useMemo(
    () => new Map(graphQuery.data?.messages.map((message) => [message.id, message]) ?? []),
    [graphQuery.data?.messages],
  )
  const run = graphQuery.data?.run
  const evaluationQuery = useQuery({
    queryKey: ['conversation-graph-evaluation', graphReference?.id, run?.id],
    queryFn: () => fetchConversationGraphEvaluation(graphReference!.id, run!.id),
    enabled: Boolean(graphReference?.status === 'frozen' && run?.id),
    retry: false,
  })

  if (graphQuery.isLoading) {
    return <main className="conversation-graph-empty">Загружаем граф диалога…</main>
  }
  if (graphQuery.error && !run) {
    return (
      <main className="conversation-graph-empty" aria-label="Граф диалога">
        <GitFork aria-hidden="true" />
        <h1>Граф диалога ещё не рассчитан</h1>
        <p>
          Запустите корпусный анализ. Исходные ответы, ранжированные кандидаты и
          дискурсивные связи останутся отдельными и будут привязаны к ревизиям сообщений.
        </p>
        <button type="button" onClick={() => createRun.mutate()} disabled={createRun.isPending}>
          <Play aria-hidden="true" /> {createRun.isPending ? 'Анализируем…' : 'Построить граф'}
        </button>
        {createRun.error ? <strong className="annotation-error">{String(createRun.error)}</strong> : null}
      </main>
    )
  }
  if (!graphQuery.data || !run) return null

  const reviewButtons = (edge: ResponseCandidate | DiscourseRelation) => (
    <div className="graph-review-actions">
      <ReviewStatus review={edge.review} />
      <button
        type="button"
        aria-label="Подтвердить связь"
        onClick={() => review.mutate({ annotationId: edge.annotation_id, decision: 'confirmed' })}
      ><Check /></button>
      <button
        type="button"
        aria-label="Оспорить связь"
        onClick={() => review.mutate({ annotationId: edge.annotation_id, decision: 'disputed' })}
      ><PauseCircle /></button>
      <button
        type="button"
        aria-label="Отклонить связь"
        onClick={() => review.mutate({ annotationId: edge.annotation_id, decision: 'rejected' })}
      ><X /></button>
    </div>
  )

  return (
    <main className="conversation-graph" aria-label="Граф диалога">
      <header className="conversation-graph-header">
        <div>
          <span className="eyebrow">PROVISIONAL · L1 OBSERVATIONS</span>
          <h1>Граф ответа и дискурса</h1>
          <p>{graphQuery.data.guardrail}</p>
        </div>
        <div className="graph-run-card">
          <strong>{run.status}</strong>
          <span>{Math.round(run.progress * 100)}%</span>
          <button type="button" onClick={() => resumeRun.mutate(run.id)} disabled={run.status === 'completed'}>
            <RotateCcw /> Продолжить
          </button>
          <button type="button" onClick={() => cancelRun.mutate(run.id)} disabled={run.status === 'completed'}>
            <PauseCircle /> Остановить
          </button>
        </div>
      </header>

      <section className="graph-controls">
        <label>
          Проверяющий
          <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} />
        </label>
        {selectedMessageId ? (
          <button type="button" onClick={() => setSelectedMessageId('')}>Показать весь граф</button>
        ) : null}
        <span>
          Энкодер: {run.tasks.find((task) => task.task_key === 'encoder_challenger')?.status ?? '—'}
        </span>
      </section>

      <section className="graph-section">
        <header><h2 className="method-heading">Исходные ответы <MethodTip tip="sourceReplies" /></h2><span>REPLIES_TO · источник</span></header>
        {graphQuery.data.explicit_replies.length ? graphQuery.data.explicit_replies.map((edge) => (
          <article className="graph-edge source-edge" key={`${edge.source_message_id}:${edge.target_message_id}`}>
            <MessageExcerpt
              message={messages.get(edge.source_message_id)} role="ответ"
              onOpen={() => onOpenEvidence(edge.source_message_id)}
            />
            <strong>REPLIES_TO</strong>
            <MessageExcerpt
              message={messages.get(edge.target_message_id)} role="цель"
              onOpen={() => onOpenEvidence(edge.target_message_id)}
            />
          </article>
        )) : <p className="graph-empty-row">В этой выборке нет исходных reply-связей.</p>}
      </section>

      <section className="graph-section">
        <header><h2 className="method-heading">Кандидаты ответа <MethodTip tip="responseCandidates" /></h2><span>RESPONDS_TO · не калибровано</span></header>
        {graphQuery.data.response_candidates.map((edge) => (
          <article className="graph-edge" key={edge.id}>
            <MessageExcerpt
              message={messages.get(edge.source_message_id)} role="сообщение"
              onOpen={() => {
                setSelectedMessageId(edge.source_message_id)
                onOpenEvidence(edge.source_message_id)
              }}
            />
            <div className="graph-edge-label">
              <strong>#{edge.rank}</strong>
              <span>{edge.raw_score.toFixed(3)}</span>
              <small>{edge.method}</small>
              <i className={edge.proposal_eligible ? 'eligible' : 'ranking-only'}>
                {edge.proposal_eligible ? 'relation candidate' : 'ranking only'}
              </i>
              <small>{edge.eligibility_reasons.join(' · ')}</small>
            </div>
            <MessageExcerpt
              message={messages.get(edge.target_message_id)} role="кандидат"
              onOpen={() => onOpenEvidence(edge.target_message_id)}
            />
            {reviewButtons(edge)}
          </article>
        ))}
      </section>

      <section className="graph-section">
        <header><h2 className="method-heading">Дискурсивные отношения <MethodTip tip="discourseRelations" /></h2><span>правила · допускают множественность</span></header>
        {graphQuery.data.discourse_relations.map((edge) => (
          <article className="graph-edge" key={edge.id}>
            <MessageExcerpt
              message={messages.get(edge.source_message_id)} role="источник"
              onOpen={() => onOpenEvidence(edge.source_message_id)}
            />
            <div className="graph-edge-label discourse">
              <strong>{relationLabels[edge.relation_type] ?? edge.relation_type}</strong>
              <small>{edge.relation_type}</small>
            </div>
            <MessageExcerpt
              message={messages.get(edge.target_message_id)} role="цель"
              onOpen={() => onOpenEvidence(edge.target_message_id)}
            />
            {reviewButtons(edge)}
          </article>
        ))}
      </section>

      <section className="graph-section graph-evaluation">
        <header><h2 className="method-heading">Reference evaluation <MethodTip tip="referenceEvaluation" /></h2><span>single-human provisional</span></header>
        {!graphReference ? (
          <div className="graph-evaluation-empty">
            <p>Reference-набор для reply/discourse ещё не создан.</p>
            <button type="button" onClick={() => createReference.mutate()}>
              Создать reference-набор
            </button>
          </div>
        ) : graphReference.status !== 'frozen' ? (
          <div className="graph-evaluation-empty">
            <p>{graphReference.name} · {graphReference.status}. Завершите FINAL-разметку и заморозьте набор во вкладке «Разметка».</p>
          </div>
        ) : evaluationQuery.data ? (
          <div className="graph-evaluation-grid">
            <div><span>Candidate recall</span><strong>{evaluationQuery.data.reply_ranking['lexical-cosine-ru@0.1.0']?.candidate_recall?.toFixed(3) ?? '—'}</strong></div>
            <div><span>MRR</span><strong>{evaluationQuery.data.reply_ranking['lexical-cosine-ru@0.1.0']?.mean_reciprocal_rank?.toFixed(3) ?? '—'}</strong></div>
            <div><span>Discourse precision</span><strong>{evaluationQuery.data.discourse.precision?.toFixed(3) ?? '—'}</strong></div>
            <div><span>Discourse recall</span><strong>{evaluationQuery.data.discourse.recall?.toFixed(3) ?? '—'}</strong></div>
            <div><span>Discourse F1</span><strong>{evaluationQuery.data.discourse.f1?.toFixed(3) ?? '—'}</strong></div>
            <div><span>Calibration</span><strong>{evaluationQuery.data.calibration.reason}</strong></div>
          </div>
        ) : <div className="graph-evaluation-empty"><p>Evaluation недоступна: {String(evaluationQuery.error ?? 'загрузка')}</p></div>}
      </section>
      <section className="graph-section">
        <header><h2 className="method-heading">Run diagnostics <MethodTip tip="runDiagnostics" /></h2><span>{run.configuration.analysis_version as string}</span></header>
        <div className="graph-task-grid">
          {run.tasks.map((task) => <article key={task.id}>
            <strong>{task.task_key}</strong><span>{task.status} · {Math.round(task.progress * 100)}%</span>
            {task.error ? <small>{task.error}</small> : null}
          </article>)}
        </div>
      </section>
      <ArtifactDetails value={graphQuery.data} />
    </main>
  )
}
