import { ArrowDown, MoreVertical, Reply } from 'lucide-react'

import type { MessageItem } from '../api/types'

type MessageTimelineProps = {
  messages: MessageItem[]
  selectedId: string
  onSelect: (id: string) => void
}

const avatarColors = ['blue', 'teal', 'violet', 'amber']
const dayFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
})
const timeFormatter = new Intl.DateTimeFormat('ru-RU', {
  hour: '2-digit',
  minute: '2-digit',
})

export function MessageTimeline({ messages, selectedId, onSelect }: MessageTimelineProps) {
  let previousDay = ''
  return (
    <section className="timeline-pane" aria-label="Лента переписки">
      <div className="pane-heading">
        <h2>Лента переписки</h2>
        <div>
          <button className="plain-icon" type="button" aria-label="Порядок сообщений">
            <ArrowDown aria-hidden="true" />
          </button>
          <button className="plain-icon" type="button" aria-label="Меню ленты">
            <MoreVertical aria-hidden="true" />
          </button>
        </div>
      </div>
      <div className="timeline-meta">
        <span>Telegram · Команда разработчиков</span>
        <span>{messages.length} сообщений</span>
      </div>
      <div className="message-scroll">
        {messages.map((message, index) => {
          const date = new Date(message.sent_at)
          const day = dayFormatter.format(date)
          const showDay = day !== previousDay
          previousDay = day
          return (
            <div key={message.id}>
              {showDay ? (
                <div className="date-divider">
                  <span>{day}</span>
                </div>
              ) : null}
              <button
                type="button"
                className={message.id === selectedId ? 'message-row selected' : 'message-row'}
                onClick={() => onSelect(message.id)}
              >
                <time>{timeFormatter.format(date)}</time>
                <div className={`avatar ${avatarColors[index % avatarColors.length]}`}>
                  {message.sender_initials}
                </div>
                <div className="message-body">
                  <div className="message-author">
                    <strong>{message.sender_name}</strong>
                    {message.reply_count > 0 ? (
                      <span className="reply-count">
                        <Reply aria-hidden="true" />
                        {message.reply_count}
                      </span>
                    ) : null}
                  </div>
                  <p>{message.text}</p>
                </div>
              </button>
            </div>
          )
        })}
      </div>
      <button className="load-more" type="button">
        Загрузить ещё сообщения <ArrowDown />
      </button>
    </section>
  )
}
