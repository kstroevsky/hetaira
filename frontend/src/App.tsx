import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { fetchCorpora, fetchMicroscope, fetchWorkspace, uploadExport } from './api/client'
import type { Microscope } from './api/types'
import { AnalysisMicroscope } from './components/AnalysisMicroscope'
import { EvidenceChain } from './components/EvidenceChain'
import { ImportDialog } from './components/ImportDialog'
import { MessageTimeline } from './components/MessageTimeline'
import { RunStrip } from './components/RunStrip'
import { Sidebar } from './components/Sidebar'
import { Topbar } from './components/Topbar'

export default function App() {
  const queryClient = useQueryClient()
  const [activeNav, setActiveNav] = useState('Корпусы')
  const [requestedCorpusId, setRequestedCorpusId] = useState('')
  const [selectedMessageId, setSelectedMessageId] = useState('')
  const [query, setQuery] = useState('')
  const [importOpen, setImportOpen] = useState(false)

  const corporaQuery = useQuery({ queryKey: ['corpora'], queryFn: fetchCorpora })
  const defaultCorpus =
    corporaQuery.data?.find((corpus) => corpus.language === 'ru') ?? corporaQuery.data?.[0]
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

  if (corporaQuery.isLoading || workspaceQuery.isLoading || !workspaceQuery.data) {
    return (
      <div className="loading-screen">
        <div className="loading-mark">P</div>
        <p>Открываем обсерваторию…</p>
      </div>
    )
  }
  if (corporaQuery.error || workspaceQuery.error) {
    return (
      <div className="error-screen">
        <h1>Не удалось открыть рабочее пространство</h1>
        <p>{String(corporaQuery.error ?? workspaceQuery.error)}</p>
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
        <main className="workspace-grid">
          <MessageTimeline
            messages={messages}
            selectedId={effectiveMessageId}
            onSelect={setSelectedMessageId}
          />
          <AnalysisMicroscope microscope={microscope} />
          <EvidenceChain microscope={microscope} />
        </main>
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
