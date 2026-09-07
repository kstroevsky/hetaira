import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { DatabaseZap } from 'lucide-react'
import { useState } from 'react'

import {
  createGoldV1,
  createManualAnnotation,
  fetchAnnotationSets,
  fetchAnnotationSetStatistics,
  fetchAnnotationUnits,
  freezeAnnotationSet,
  reviewManualAnnotation,
} from '../api/client'
import { AnnotationDesk } from './AnnotationDesk'
type AnnotationWorkbenchProps = {
  corpusId: string
  snapshotId: string
}

function annotationValue(kind: string, label: string, selectedText: string) {
  if (kind === 'proposition') return { type: label || 'claim', text: selectedText }
  if (kind === 'stance') return { position: label || 'support', target_resolution: 'manual' }
  return { label: (label || 'ASSERT').toUpperCase() }
}

export function AnnotationWorkbench({ corpusId, snapshotId }: AnnotationWorkbenchProps) {
  const queryClient = useQueryClient()
  const [selectedSetId, setSelectedSetId] = useState('')
  const [selectedUnitId, setSelectedUnitId] = useState('')
  const [kind, setKind] = useState('dialogue_act')
  const [label, setLabel] = useState('ASSERT')
  const [start, setStart] = useState(0)
  const [end, setEnd] = useState(0)
  const [annotator, setAnnotator] = useState('local-annotator')
  const [reviewer, setReviewer] = useState('local-reviewer')

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

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['annotation-sets', corpusId] }),
      queryClient.invalidateQueries({ queryKey: ['annotation-units', activeSetId] }),
      queryClient.invalidateQueries({ queryKey: ['annotation-set-statistics', activeSetId] }),
    ])
  }
  const createSet = useMutation({
    mutationFn: () => createGoldV1(corpusId, snapshotId),
    onSuccess: async (created) => {
      setSelectedSetId(created.id)
      await refresh()
    },
  })
  const annotate = useMutation({
    mutationFn: async () => {
      if (!selectedUnit) throw new Error('Выберите единицу разметки')
      const safeEnd = end || selectedUnit.text.length
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
          Создайте gold-ru-v1 из 1 200 стратифицированных единиц. Эпизоды не
          пересекают train/development/test, а 30% выборки требуют двух независимых аннотаторов.
        </p>
        <button type="button" onClick={() => createSet.mutate()} disabled={createSet.isPending}>
          {createSet.isPending ? 'Создаём…' : 'Создать gold-ru-v1'}
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
      units={unitsQuery.data ?? []}
      selectedUnit={selectedUnit}
      kind={kind}
      label={label}
      start={start}
      end={end}
      annotator={annotator}
      reviewer={reviewer}
      freezePending={freeze.isPending}
      annotatePending={annotate.isPending}
      freezeError={freeze.error}
      annotateError={annotate.error}
      reviewError={review.error}
      onSetChange={setSelectedSetId}
      onUnitSelect={(unit) => {
        setSelectedUnitId(unit.id)
        setStart(0)
        setEnd(unit.text.length)
      }}
      onKindChange={setKind}
      onLabelChange={setLabel}
      onStartChange={setStart}
      onEndChange={setEnd}
      onAnnotatorChange={setAnnotator}
      onReviewerChange={setReviewer}
      onAnnotate={() => annotate.mutate()}
      onReview={(annotationId, decision) => review.mutate({ annotationId, decision })}
      onFreeze={() => freeze.mutate()}
    />
  )
}
