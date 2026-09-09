import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { fetchCorpora, fetchMicroscope, fetchWorkspace, uploadExport } from './api/client'
import type { Microscope } from './api/types'
import { AnalysisMicroscope } from './components/AnalysisMicroscope'
import { AnnotationWorkbench } from './components/AnnotationWorkbench'
import { ConversationGraphWorkbench } from './components/ConversationGraphWorkbench'
import { EvidenceChain } from './components/EvidenceChain'
import { ImportDialog } from './components/ImportDialog'
import { MessageTimeline } from './components/MessageTimeline'
import { TooltipProvider } from './components/MetricTip'
import { LinguisticWorkbench } from './components/LinguisticWorkbench'
import { ReasoningGraphWorkbench } from './components/ReasoningGraphWorkbench'
import { SemanticStateWorkbench } from './components/SemanticStateWorkbench'
import { NetworkSequenceWorkbench } from './components/NetworkSequenceWorkbench'
import { StatisticalSynthesisWorkbench } from './components/StatisticalSynthesisWorkbench'
import { ExperimentalDynamicsWorkbench } from './components/ExperimentalDynamicsWorkbench'
import { InteractionDynamicsWorkbench } from './components/InteractionDynamicsWorkbench'
import { ObservatoryOverview } from './components/ObservatoryOverview'
import { RunStrip } from './components/RunStrip'
import { Sidebar } from './components/Sidebar'
import { Topbar } from './components/Topbar'
import { selectDefaultCorpus } from './corpusSelection'

export default function App() {
  return <TooltipProvider><AppWorkspace /></TooltipProvider>
}

function AppWorkspace() {
  const queryClient = useQueryClient()
  const [activeNav, setActiveNav] = useState('Обзор')
  const [requestedCorpusId, setRequestedCorpusId] = useState('')
  const [selectedMessageId, setSelectedMessageId] = useState('')
  const [query, setQuery] = useState('')
  const [importOpen, setImportOpen] = useState(false)

  const corporaQuery = useQuery({ queryKey: ['corpora'], queryFn: fetchCorpora })
  const defaultCorpus = selectDefaultCorpus(corporaQuery.data)
  const corpusId = requestedCorpusId || defaultCorpus?.id || ''
  const workspaceQuery = useQuery({
    queryKey: ['workspace', corpusId],
    queryFn: () => fetchWorkspace(corpusId),
    enabled: Boolean(corpusId),
  })
  const effectiveMessageId = selectedMessageId || workspaceQuery.data?.selected_message_id || ''
  const microscopeQuery = useQuery({
    queryKey: ['microscope', effectiveMessageId],
    queryFn: () => fetchMicroscope(effectiveMessageId),
    enabled: Boolean(effectiveMessageId),
  })
  const importMutation = useMutation({
    mutationFn: ({
      platform,
      file,
    }: {
      platform: 'telegram' | 'whatsapp'
      file: File
    }) => uploadExport(corpusId, platform, file),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['workspace', corpusId] }),
        queryClient.invalidateQueries({ queryKey: ['corpora'] }),
      ])
    },
  })
  const messages = useMemo(() => {
    const all = workspaceQuery.data?.messages ?? []
    const normalized = query.trim().toLocaleLowerCase('ru-RU')
    return normalized
      ? all.filter((message) =>
          `${message.sender_name} ${message.text}`
            .toLocaleLowerCase('ru-RU')
            .includes(normalized),
        )
      : all
  }, [query, workspaceQuery.data?.messages])

  if (corporaQuery.error || workspaceQuery.error) {
    return (
      <div className="error-screen">
        <h1>Не удалось открыть рабочее пространство</h1>
        <p>{String(corporaQuery.error ?? workspaceQuery.error)}</p>
      </div>
    )
  }
  if (corporaQuery.isLoading || workspaceQuery.isLoading || !workspaceQuery.data) {
    return (
      <div className="loading-screen">
        <div className="loading-mark">P</div>
        <p>Открываем обсерваторию…</p>
      </div>
    )
  }
  const microscope: Microscope = microscopeQuery.data ?? workspaceQuery.data.microscope
  const corpus = workspaceQuery.data.corpus
  return (
    <div className="app-shell">
      <Sidebar active={activeNav} onChange={setActiveNav} />
      <div className="app-main">
        <Topbar
          corpora={corporaQuery.data ?? [corpus]}
          corpusId={corpus.id}
          query={query}
          onCorpusChange={(id) => {
            setRequestedCorpusId(id)
            setSelectedMessageId('')
          }}
          onQueryChange={setQuery}
          onImport={() => setImportOpen(true)}
        />
        {!corpus.is_validated_language ? (
          <div className="english-warning">
            UNVALIDATED ENGLISH DEMO · результаты исключены из научных выводов и
            продвижения моделей
          </div>
        ) : null}
        <div className="snapshot-strip" aria-label="Активный снимок корпуса">
          Снимок {workspaceQuery.data.overview.snapshot_id.slice(0, 8)} · manifest{' '}
          {workspaceQuery.data.overview.snapshot_manifest_hash.slice(0, 12)}…
        </div>
        {activeNav === 'Обзор' ? (
          <ObservatoryOverview
            corpusId={corpus.id}
            onOpenEvidence={(messageId) => {
              setSelectedMessageId(messageId)
              setActiveNav('Корпусы')
            }}
          />
        ) : activeNav === 'Разметка' ? (
          <AnnotationWorkbench
            corpusId={corpus.id}
          />
        ) : activeNav === 'Граф диалога' ? (
          <ConversationGraphWorkbench
            corpusId={corpus.id}
            onOpenEvidence={(messageId) => {
              setSelectedMessageId(messageId)
              setActiveNav('Корпусы')
            }}
          />
        ) : activeNav === 'Лингвистика' ? (
          <LinguisticWorkbench
            corpusId={corpus.id}
            messages={messages}
            initialMessageId={effectiveMessageId}
            onOpenEvidence={(messageId) => {
              setSelectedMessageId(messageId)
              setActiveNav('Корпусы')
            }}
          />
        ) : activeNav === 'Аргументы' ? (
          <ReasoningGraphWorkbench corpusId={corpus.id} />
        ) : activeNav === 'Динамика' ? (
          <InteractionDynamicsWorkbench corpusId={corpus.id} />
        ) : activeNav === 'Состояния' ? (
          <SemanticStateWorkbench corpusId={corpus.id} />
        ) : activeNav === 'Сети' ? (
          <NetworkSequenceWorkbench corpusId={corpus.id} />
        ) : activeNav === 'Статистика' ? (
          <StatisticalSynthesisWorkbench corpusId={corpus.id} />
        ) : activeNav === 'Эксперименты' ? (
          <ExperimentalDynamicsWorkbench corpusId={corpus.id} />
        ) : (
          <main className="workspace-grid">
            <MessageTimeline
              messages={messages}
              selectedId={effectiveMessageId}
              onSelect={setSelectedMessageId}
            />
            <AnalysisMicroscope microscope={microscope} />
            <EvidenceChain microscope={microscope} />
          </main>
        )}
        <RunStrip
          run={workspaceQuery.data.run}
          messageCount={workspaceQuery.data.overview.message_count}
        />
      </div>
      <ImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onSubmit={async (platform, file) => {
          await importMutation.mutateAsync({ platform, file })
        }}
      />
    </div>
  )
}
