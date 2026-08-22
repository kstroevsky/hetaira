import { X } from 'lucide-react'
import { useState } from 'react'

type ImportDialogProps = {
  open: boolean
  onClose: () => void
  onSubmit: (platform: 'telegram' | 'whatsapp', file: File) => Promise<void>
}

export function ImportDialog({ open, onClose, onSubmit }: ImportDialogProps) {
  const [platform, setPlatform] = useState<'telegram' | 'whatsapp'>('telegram')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (!open) return null
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <dialog
        open
        className="import-dialog"
        aria-labelledby="import-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dialog-title">
          <h2 id="import-title">Импорт корпуса</h2>
          <button type="button" onClick={onClose} aria-label="Закрыть">
            <X />
          </button>
        </div>
        <p>Исходный файл будет сохранён неизменным и связан с SHA-256 снимком корпуса.</p>
        <label>
          Формат
          <select
            value={platform}
            onChange={(event) => setPlatform(event.target.value as 'telegram' | 'whatsapp')}
          >
            <option value="telegram">Telegram JSON</option>
            <option value="whatsapp">WhatsApp TXT</option>
          </select>
        </label>
        <label className="file-input">
          Файл
          <input
            type="file"
            accept={
              platform === 'telegram' ? '.json,application/json' : '.txt,text/plain'
            }
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <div className="privacy-explanation">
          <strong>LOCAL ONLY</strong>
          <span>Файл не покинет компьютер. Внешний API для нового корпуса отключён.</span>
        </div>
        {error ? <p className="dialog-error">{error}</p> : null}
        <div className="dialog-actions">
          <button type="button" onClick={onClose}>
            Отмена
          </button>
          <button
            type="button"
            disabled={!file || busy}
            onClick={async () => {
              if (!file) return
              setBusy(true)
              setError('')
              try {
                await onSubmit(platform, file)
                onClose()
              } catch (cause) {
                setError(cause instanceof Error ? cause.message : 'Ошибка импорта')
              } finally {
                setBusy(false)
              }
            }}
          >
            {busy ? 'Импорт…' : 'Импортировать'}
          </button>
        </div>
      </dialog>
    </div>
  )
}
