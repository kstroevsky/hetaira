import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowRight,
  ExternalLink,
  GitFork,
  MessageSquareText,
  SearchCheck,
  X,
} from 'lucide-react'

import { fetchEpisodeMicroscope } from '../api/client'

type EpisodeMicroscopeProps = {
  corpusId: string
  messageId: string
  onClose: () => void
  onOpenEvidence: (messageId: string) => void
}

const number = new Intl.NumberFormat('ru-RU')
const actLabels: Record<string, string> = {
  ASSERT: 'утверждение',
  QUESTION: 'вопрос',
  PROPOSE: 'предложение',
  AGREE: 'согласие',
  DISAGREE: 'несогласие',
  COMMIT: 'обязательство',
  ACKNOWLEDGE: 'подтверждение',
}
const groundingLabels: Record<string, string> = {
  CLARIFICATION_REQUESTED: 'запрос уточнения',
  REPAIRED: 'исправление',
  ACKNOWLEDGED: 'подтверждение понимания',
}

export function EpisodeMicroscope({
  corpusId,
  messageId,
  onClose,
  onOpenEvidence,
}: EpisodeMicroscopeProps) {
  const microscopeQuery = useQuery({
    queryKey: ['episode-microscope', corpusId, messageId],
    queryFn: () => fetchEpisodeMicroscope(corpusId, messageId),
  })
  const microscope = microscopeQuery.data
  return (
    <section className="episode-microscope" aria-label="Микроскоп эпизода">
      <header>
        <div>
          <span>DEEP SLICE · PROVISIONAL RULES</span>
          <h3>Пропозиции, позиции и grounding в контекстном окне</h3>
        </div>
        <button type="button" onClick={onClose} aria-label="Закрыть микроскоп эпизода"><X /></button>
      </header>
      {microscopeQuery.isLoading ? <div className="episode-loading">Разбираем контекст…</div> : null}
      {microscopeQuery.error ? (
        <div className="episode-loading error">Не удалось построить разбор эпизода.</div>
      ) : null}
      {microscope ? (
        <>
          <div className="episode-summary">
            <Metric icon={MessageSquareText} label="Сообщения" value={microscope.window.message_count} />
            <Metric icon={SearchCheck} label="Пропозиции" value={microscope.propositions.length} />
            <Metric icon={GitFork} label="Поддержка" value={microscope.agreement_structure.support} />
            <Metric icon={GitFork} label="Возражения" value={microscope.agreement_structure.oppose} />
            <Metric icon={AlertTriangle} label="Цель не разрешена" value={microscope.agreement_structure.abstain} />
          </div>
          <div className="episode-columns">
            <section className="episode-timeline">
              <h4>Контекст · {microscope.window.episode_title}</h4>
              <div>
                {microscope.messages.map((message) => (
                  <article
                    key={message.message_id}
                    className={message.selected ? 'selected' : ''}
                  >
                    <header><strong>{message.sender}</strong><time>{new Date(message.sent_at).toLocaleString('ru-RU')}</time></header>
                    <p>{message.text || '∅'}</p>
                    <footer>
                      <span>{message.dialogue_acts.map((act) => actLabels[act] ?? act).join(' · ')}</span>
                      <button type="button" onClick={() => onOpenEvidence(message.message_id)}>
                        Источник<ExternalLink />
                      </button>
                    </footer>
                  </article>
                ))}
              </div>
            </section>

            <section className="episode-propositions">
              <h4>Извлечённые пропозиции</h4>
              <div>
                {microscope.propositions.map((proposition) => (
                  <article key={proposition.proposition_id}>
                    <header><span>{proposition.type}</span><strong>{proposition.holder}</strong></header>
                    <p>{proposition.text}</p>
                    <small>символы {proposition.evidence.start_codepoint}–{proposition.evidence.end_codepoint}</small>
                  </article>
                ))}
                {!microscope.propositions.length ? <p>Пропозиции не обнаружены.</p> : null}
              </div>
            </section>

            <section className="episode-relations">
              <h4>Структура согласия</h4>
              <div className="stance-list">
                {microscope.stance_edges.map((edge, index) => (
                  <article className={edge.position.toLocaleLowerCase()} key={`${edge.source_message_id}-${index}`}>
                    <header><strong>{edge.holder}</strong><span>{edge.position}</span></header>
                    <div><ArrowRight /><p>{edge.target_text ?? 'Цель неоднозначна'}</p></div>
                    {edge.alternatives.length > 1 ? <small>{edge.alternatives.length} возможных целей</small> : null}
                  </article>
                ))}
                {!microscope.stance_edges.length ? <p>Явные stance-переходы не обнаружены.</p> : null}
              </div>
              <h4>Grounding / repair</h4>
              <div className="grounding-list">
                {microscope.grounding_events.map((event, index) => (
                  <button
                    type="button"
                    key={`${event.message_id}-${index}`}
                    onClick={() => onOpenEvidence(event.message_id)}
                  >
                    {groundingLabels[event.label] ?? event.label}
                  </button>
                ))}
                {!microscope.grounding_events.length ? <p>Сигналы grounding не обнаружены.</p> : null}
              </div>
            </section>
          </div>
          <p className="episode-guardrail"><AlertTriangle /> {microscope.guardrail}</p>
        </>
      ) : null}
    </section>
  )
}

function Metric({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof SearchCheck
  label: string
  value: number
}) {
  return <div><Icon /><span>{label}</span><strong>{number.format(value)}</strong></div>
}
