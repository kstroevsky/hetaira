import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { DatabaseZap } from 'lucide-react'
import { useEffect, useReducer, useState } from 'react'

import {
  createReferencePilot,
  createConversationGraphReference,
  createManualAnnotation,
  fetchAnnotationSets,
  fetchAnnotationSetStatistics,
  fetchAnnotationUnitContext,
  fetchAnnotationUnits,
  fetchConversationMessages,
  freezeAnnotationSet,
  reviewManualAnnotation,
  submitTaskJudgment,
} from '../api/client'
import type { JudgmentAnnotationDraft } from '../api/types'
import { AnnotationDesk } from './AnnotationDesk'
import { MethodTip } from './MethodTip'
type AnnotationWorkbenchProps = {
  corpusId: string
}

type DraftState = {
  items: JudgmentAnnotationDraft[]
  error: string
  nextId: number
}

type DraftAction =
  | { type: 'add'; annotation: Omit<JudgmentAnnotationDraft, 'draft_id'> }
  | { type: 'remove'; draftId: number }
  | { type: 'error'; message: string }
  | { type: 'clear' }

function reduceDrafts(state: DraftState, action: DraftAction): DraftState {
  if (action.type === 'add') {
    return {
      items: [...state.items, { ...action.annotation, draft_id: state.nextId }],
      error: '',
      nextId: state.nextId + 1,
    }
  }
  if (action.type === 'remove') {
    return { ...state, items: state.items.filter((item) => item.draft_id !== action.draftId) }
  }
  if (action.type === 'error') return { ...state, error: action.message }
  return { items: [], error: '', nextId: state.nextId }
}

function annotationValue(
  kind: string,
  label: string,
  selectedText: string,
  holderId: string | null = null,
  sourceMessageId: string | undefined = undefined,
  sourceRevisionId: string | undefined = undefined,
  start = 0,
  end = selectedText.length,
  targetMessageId: string | undefined = undefined,
) {
  if (kind === 'proposition') return { type: label || 'claim', text: selectedText }
  if (kind === 'stance') return {
    position: label || 'support',
    holder_id: holderId,
    target_type: targetMessageId ? 'message' : 'span',
    target_id: targetMessageId
      ?? (sourceRevisionId ? `${sourceRevisionId}:${start}:${end}` : undefined),
  }
  if (kind === 'epistemic_state') return {
    label: (label || 'COMMITTED').toUpperCase(),
    holder_id: holderId,
    target_type: 'span',
    target_id: sourceRevisionId ? `${sourceRevisionId}:${start}:${end}` : undefined,
  }
  if (kind === 'grounding') return {
    label: (label || 'ACKNOWLEDGED').toUpperCase(),
    target_type: 'message',
    target_id: targetMessageId,
  }
  if (kind === 'argumentation') return {
    relation_type: (label || 'SUPPORTS').toUpperCase(),
    source_type: 'span',
    source_id: sourceRevisionId ? `${sourceRevisionId}:${start}:${end}` : sourceMessageId,
    target_type: 'message',
    target_id: targetMessageId,
  }
  if (kind === 'reply_target') return {
    relation_type: 'RESPONDS_TO',
    source_message_id: sourceMessageId,
    target_message_id: targetMessageId,
  }
  if (kind === 'discourse_relation') return {
    relation_type: (label || 'ANSWERS').toUpperCase(),
    source_message_id: sourceMessageId,
    target_message_id: targetMessageId,
  }
  return { label: (label || 'ASSERT').toUpperCase() }
}

export function AnnotationWorkbench({ corpusId }: AnnotationWorkbenchProps) {
  const queryClient = useQueryClient()
  const [selectedSetId, setSelectedSetId] = useState('')
  const [selectedUnitId, setSelectedUnitId] = useState('')
  const [kind, setKind] = useState('dialogue_act')
  const [label, setLabel] = useState('ASSERT')
  const [start, setStart] = useState(0)
  const [end, setEnd] = useState(0)
  const [annotator, setAnnotator] = useState('local-annotator')
  const [reviewer, setReviewer] = useState('local-reviewer')
  const [slot, setSlot] = useState<'A' | 'B' | 'FINAL'>('A')
  const [judgmentStatus, setJudgmentStatus] = useState<'PRESENT' | 'ABSENT' | 'ABSTAIN'>(
    'PRESENT',
  )
  const [targetQuery, setTargetQuery] = useState('')
  const [targetMessageId, setTargetMessageId] = useState('')
  const [drafts, dispatchDraft] = useReducer(reduceDrafts, { items: [], error: '', nextId: 1 })

  const setsQuery = useQuery({
    queryKey: ['annotation-sets', corpusId],
    queryFn: () => fetchAnnotationSets(corpusId),
  })
  const activeSetId = selectedSetId || setsQuery.data?.[0]?.id || ''
  const activeSet = setsQuery.data?.find((item) => item.id === activeSetId)
  const unitsQuery = useQuery({
    queryKey: ['annotation-units', activeSetId],
    queryFn: () => fetchAnnotationUnits(activeSetId),
    enabled: Boolean(activeSetId),
  })
  const statisticsQuery = useQuery({
    queryKey: ['annotation-set-statistics', activeSetId],
    queryFn: () => fetchAnnotationSetStatistics(activeSetId),
    enabled: Boolean(activeSetId),
  })
  const selectedUnit =
    unitsQuery.data?.find((unit) => unit.id === selectedUnitId) ?? unitsQuery.data?.[0]
  const protocol = activeSet?.sampling_spec.judgment_protocol
  const singleFinal = protocol === 'single_final_reference_v1'
  const usesTaskJudgments = protocol === 'blind_ab_final_v1' || singleFinal
  const effectiveSlot = singleFinal ? 'FINAL' : slot
  const contextQuery = useQuery({
    queryKey: ['annotation-unit-context', selectedUnit?.id, effectiveSlot],
    queryFn: () => fetchAnnotationUnitContext(selectedUnit!.id, effectiveSlot),
    enabled: Boolean(selectedUnit && usesTaskJudgments),
  })
  const conversationMessagesQuery = useQuery({
    queryKey: [
      'conversation-reference-messages',
      corpusId,
      contextQuery.data?.anchor_conversation_id,
      contextQuery.data?.anchor_message_id,
      targetQuery,
    ],
    queryFn: () => fetchConversationMessages(
      corpusId,
      contextQuery.data!.anchor_conversation_id,
      targetQuery,
      contextQuery.data!.anchor_message_id,
    ),
    enabled: Boolean(singleFinal && contextQuery.data?.anchor_conversation_id),
  })
  useEffect(() => {
    if (singleFinal) {
      setSlot('FINAL')
      setKind('reply_target')
      setLabel('RESPONDS_TO')
    }
    setTargetMessageId('')
  }, [activeSetId, singleFinal])

  const buildCurrentAnnotation = (): Omit<JudgmentAnnotationDraft, 'draft_id'> => {
    if (!selectedUnit) throw new Error('Выберите единицу разметки')
    const safeEnd = end || selectedUnit.text.length
    const anchor = contextQuery.data?.messages.find((message) => message.labelable)
    const replyTarget = contextQuery.data?.messages.find(
      (message) => message.context_role === 'reply_target',
    )
    const resolvedTargetMessageId = targetMessageId || replyTarget?.message_id
    if (
      ['grounding', 'argumentation', 'reply_target', 'discourse_relation'].includes(kind)
      && !resolvedTargetMessageId
    ) {
      throw new Error(
        'Для этой relation-задачи нужна явная reply-цель; выберите ABSTAIN, если цель не разрешена.',
      )
    }
    return {
      kind,
      value: annotationValue(
        kind,
        label,
        selectedUnit.text.slice(start, safeEnd),
        anchor?.sender_id ?? selectedUnit.sender_id,
        anchor?.message_id,
        contextQuery.data?.anchor_revision_id,
        start,
        safeEnd,
        resolvedTargetMessageId,
      ),
      spans: [{ start_codepoint: start, end_codepoint: safeEnd }],
    }
  }

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['annotation-sets', corpusId] }),
      queryClient.invalidateQueries({ queryKey: ['annotation-units', activeSetId] }),
      queryClient.invalidateQueries({ queryKey: ['annotation-set-statistics', activeSetId] }),
      queryClient.invalidateQueries({ queryKey: ['annotation-unit-context', selectedUnit?.id] }),
    ])
  }
  const createSet = useMutation({
    mutationFn: () => createReferencePilot(corpusId),
    onSuccess: async (created) => {
      setSelectedSetId(created.id)
      await refresh()
    },
  })
  const createGraphSet = useMutation({
    mutationFn: () => createConversationGraphReference(corpusId),
    onSuccess: async (created) => {
      setSelectedSetId(created.id)
      await refresh()
    },
  })
  const annotate = useMutation({
    mutationFn: async () => {
      if (!selectedUnit) throw new Error('Выберите единицу разметки')
      const safeEnd = end || selectedUnit.text.length
      if (usesTaskJudgments) {
        const annotations = judgmentStatus === 'PRESENT'
          ? (drafts.items.length
              ? drafts.items.map((draft) => ({
                  kind: draft.kind,
                  value: draft.value,
                  spans: draft.spans,
                }))
              : [buildCurrentAnnotation()])
          : []
        return submitTaskJudgment(selectedUnit.id, kind, effectiveSlot, {
          status: judgmentStatus,
          annotator: effectiveSlot === 'FINAL' ? reviewer : annotator,
          annotations,
        })
      }
      return createManualAnnotation(selectedUnit.id, {
        kind,
        value: annotationValue(kind, label, selectedUnit.text.slice(start, safeEnd)),
        spans: [{ start_codepoint: start, end_codepoint: safeEnd }],
        annotator,
      })
    },
    onSuccess: async () => {
      dispatchDraft({ type: 'clear' })
      await refresh()
    },
  })
  const review = useMutation({
    mutationFn: ({
      annotationId,
      decision,
    }: {
      annotationId: string
      decision: 'confirmed' | 'disputed' | 'rejected'
    }) => reviewManualAnnotation(annotationId, decision, reviewer),
    onSuccess: refresh,
  })
  const freeze = useMutation({
    mutationFn: () => freezeAnnotationSet(activeSetId),
    onSuccess: refresh,
  })

  const statistics = statisticsQuery.data
  if (setsQuery.isLoading) return <div className="annotation-empty">Загружаем наборы…</div>
  if (!setsQuery.data?.length) {
    return (
      <main className="annotation-empty">
        <DatabaseZap aria-hidden="true" />
        <h1 className="method-heading">Русский пилот разметки ещё не создан <MethodTip tip="annotationProtocol" /></h1>
        <p>
          Создайте corpus-specific reference pilot из 80 anchor-сообщений. Эпизоды не
          пересекают train/development/test; 24 единицы получают слепые A/B-суждения.
        </p>
        <button type="button" onClick={() => createSet.mutate()} disabled={createSet.isPending}>
          {createSet.isPending ? 'Создаём…' : 'Создать reference pilot'}
        </button>
        <button
          type="button"
          onClick={() => createGraphSet.mutate()}
          disabled={createGraphSet.isPending}
        >
          {createGraphSet.isPending ? 'Создаём…' : 'Создать reference для графа'}
        </button>
        {createSet.error ? <strong className="annotation-error">{String(createSet.error)}</strong> : null}
      </main>
    )
  }

  return (
    <div className="annotation-workbench-shell">
      <div className="annotation-set-actions">
        <button type="button" onClick={() => createGraphSet.mutate()}>
          Создать reference для графа
        </button>
      </div>
      {singleFinal ? (
        <section className="reference-target-browser" aria-label="Поиск цели во всём разговоре">
          <header>
            <strong>Цель ответа во всём исходном разговоре</strong>
            <input
              aria-label="Поиск цели ответа"
              value={targetQuery}
              onChange={(event) => setTargetQuery(event.target.value)}
              placeholder="Поиск по полному разговору"
            />
          </header>
          <div>
            {(conversationMessagesQuery.data?.items ?? []).map((message) => (
              <button
                className={targetMessageId === message.message_id ? 'selected' : ''}
                key={message.message_id}
                type="button"
                onClick={() => setTargetMessageId(message.message_id)}
              >
                <small>{message.sender_name} · #{message.external_id}</small>
                <span>{message.text || '∅'}</span>
              </button>
            ))}
          </div>
        </section>
      ) : null}
      <AnnotationDesk
      sets={setsQuery.data}
      activeSetId={activeSetId}
      activeSet={activeSet}
      statistics={statistics}
      usesTaskJudgments={usesTaskJudgments}
      singleFinal={singleFinal}
      unitContext={contextQuery.data}
      units={unitsQuery.data ?? []}
      selectedUnit={selectedUnit}
      kind={kind}
      label={label}
      start={start}
      end={end}
      annotator={annotator}
      reviewer={reviewer}
      slot={effectiveSlot}
      judgmentStatus={judgmentStatus}
      draftAnnotations={drafts.items}
      draftError={drafts.error}
      freezePending={freeze.isPending}
      annotatePending={annotate.isPending || (usesTaskJudgments && contextQuery.isLoading)}
      freezeError={freeze.error}
      annotateError={annotate.error}
      reviewError={review.error}
      onSetChange={(value) => {
        setSelectedSetId(value)
        setSlot('A')
        dispatchDraft({ type: 'clear' })
      }}
      onUnitSelect={(unit) => {
        setSelectedUnitId(unit.id)
        setStart(0)
        setEnd(unit.text.length)
        setSlot('A')
        dispatchDraft({ type: 'clear' })
      }}
      onKindChange={(value) => {
        setKind(value)
        dispatchDraft({ type: 'clear' })
      }}
      onLabelChange={setLabel}
      onStartChange={setStart}
      onEndChange={setEnd}
      onAnnotatorChange={setAnnotator}
      onReviewerChange={setReviewer}
      onSlotChange={(value) => {
        setSlot(value)
        dispatchDraft({ type: 'clear' })
      }}
      onJudgmentStatusChange={(value) => {
        setJudgmentStatus(value)
        if (value !== 'PRESENT') dispatchDraft({ type: 'clear' })
      }}
      onAddDraft={() => {
        try {
          dispatchDraft({ type: 'add', annotation: buildCurrentAnnotation() })
        } catch (error) {
          dispatchDraft({ type: 'error', message: String(error) })
        }
      }}
      onRemoveDraft={(draftId) => dispatchDraft({ type: 'remove', draftId })}
      onAnnotate={() => annotate.mutate()}
      onReview={(annotationId, decision) => review.mutate({ annotationId, decision })}
      onFreeze={() => freeze.mutate()}
      />
    </div>
  )
}
