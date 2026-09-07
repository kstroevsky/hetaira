import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { DatabaseZap } from 'lucide-react'
import { useState } from 'react'

import {
  createReferencePilot,
  createManualAnnotation,
  fetchAnnotationSets,
  fetchAnnotationSetStatistics,
  fetchAnnotationUnitContext,
  fetchAnnotationUnits,
  freezeAnnotationSet,
  reviewManualAnnotation,
  submitTaskJudgment,
} from '../api/client'
import { AnnotationDesk } from './AnnotationDesk'
type AnnotationWorkbenchProps = {
  corpusId: string
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
    target_type: 'message',
    target_id: targetMessageId,
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
    source_type: 'message',
    source_id: sourceMessageId,
    target_type: 'message',
    target_id: targetMessageId,
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
  const usesTaskJudgments =
    activeSet?.sampling_spec.judgment_protocol === 'blind_ab_final_v1'
  const contextQuery = useQuery({
    queryKey: ['annotation-unit-context', selectedUnit?.id, slot],
    queryFn: () => fetchAnnotationUnitContext(selectedUnit!.id, slot),
    enabled: Boolean(selectedUnit && usesTaskJudgments),
  })

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
  const annotate = useMutation({
    mutationFn: async () => {
      if (!selectedUnit) throw new Error('Выберите единицу разметки')
      const safeEnd = end || selectedUnit.text.length
      if (usesTaskJudgments) {
        const anchor = contextQuery.data?.messages.find((message) => message.labelable)
        const replyTarget = contextQuery.data?.messages.find(
          (message) => message.context_role === 'reply_target',
        )
        if (
          judgmentStatus === 'PRESENT'
          && ['stance', 'grounding', 'argumentation'].includes(kind)
          && !replyTarget
        ) {
          throw new Error(
            'Для PRESENT этой relation-задачи нужна явная reply-цель; выберите ABSTAIN, если цель не разрешена.',
          )
        }
        const annotations = judgmentStatus === 'PRESENT'
          ? [{
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
                replyTarget?.message_id,
              ),
              spans: [{ start_codepoint: start, end_codepoint: safeEnd }],
            }]
          : []
        return submitTaskJudgment(selectedUnit.id, kind, slot, {
          status: judgmentStatus,
          annotator: slot === 'FINAL' ? reviewer : annotator,
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
    onSuccess: refresh,
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
        <h1>Русский пилот разметки ещё не создан</h1>
        <p>
          Создайте corpus-specific reference pilot из 80 anchor-сообщений. Эпизоды не
          пересекают train/development/test; 24 единицы получают слепые A/B-суждения.
        </p>
        <button type="button" onClick={() => createSet.mutate()} disabled={createSet.isPending}>
          {createSet.isPending ? 'Создаём…' : 'Создать reference pilot'}
        </button>
        {createSet.error ? <strong className="annotation-error">{String(createSet.error)}</strong> : null}
      </main>
    )
  }

  return (
    <AnnotationDesk
      sets={setsQuery.data}
      activeSetId={activeSetId}
      activeSet={activeSet}
      statistics={statistics}
      usesTaskJudgments={usesTaskJudgments}
      unitContext={contextQuery.data}
      units={unitsQuery.data ?? []}
      selectedUnit={selectedUnit}
      kind={kind}
      label={label}
      start={start}
      end={end}
      annotator={annotator}
      reviewer={reviewer}
      slot={slot}
      judgmentStatus={judgmentStatus}
      freezePending={freeze.isPending}
      annotatePending={annotate.isPending || (usesTaskJudgments && contextQuery.isLoading)}
      freezeError={freeze.error}
      annotateError={annotate.error}
      reviewError={review.error}
      onSetChange={(value) => {
        setSelectedSetId(value)
        setSlot('A')
      }}
      onUnitSelect={(unit) => {
        setSelectedUnitId(unit.id)
        setStart(0)
        setEnd(unit.text.length)
        setSlot('A')
      }}
      onKindChange={setKind}
      onLabelChange={setLabel}
      onStartChange={setStart}
      onEndChange={setEnd}
      onAnnotatorChange={setAnnotator}
      onReviewerChange={setReviewer}
      onSlotChange={setSlot}
      onJudgmentStatusChange={setJudgmentStatus}
      onAnnotate={() => annotate.mutate()}
      onReview={(annotationId, decision) => review.mutate({ annotationId, decision })}
      onFreeze={() => freeze.mutate()}
    />
  )
}
