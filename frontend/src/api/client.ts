import type { Corpus, Microscope, Workspace } from './types'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function fetchCorpora(): Promise<Corpus[]> {
  return request('/api/corpora')
}

export function fetchWorkspace(corpusId?: string): Promise<Workspace> {
  const suffix = corpusId ? `?corpus_id=${encodeURIComponent(corpusId)}` : ''
  return request(`/api/workspace${suffix}`)
}

export function fetchMicroscope(messageId: string): Promise<Microscope> {
  return request(`/api/messages/${messageId}/microscope`)
}

export function uploadExport(
  corpusId: string,
  platform: 'telegram' | 'whatsapp',
  file: File,
): Promise<{ imported_messages: number; warnings: string[] }> {
  const data = new FormData()
  data.append('file', file)
  return request(`/api/corpora/${corpusId}/imports/${platform}`, {
    method: 'POST',
    body: data,
  })
}
