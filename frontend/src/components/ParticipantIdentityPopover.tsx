import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ExternalLink, Fingerprint } from 'lucide-react'
import { useState } from 'react'

import { fetchParticipantIdentity } from '../api/client'

type ParticipantIdentityPopoverProps = {
  participantId: string
  name: string
  onOpenEvidence?: (messageId: string) => void
}

const number = new Intl.NumberFormat('ru-RU')
const basisLabels: Record<string, string> = {
  telegram_user_id: 'прямой Telegram ID',
  telegram_username: 'Telegram login',
  source_directory_mapping: 'ID из source roster',
}

export function ParticipantIdentityPopover({
  participantId,
  name,
  onOpenEvidence,
}: ParticipantIdentityPopoverProps) {
  const [opened, setOpened] = useState(false)
  const identityQuery = useQuery({
    queryKey: ['participant-identity', participantId],
    queryFn: () => fetchParticipantIdentity(participantId),
    enabled: opened,
    staleTime: Number.POSITIVE_INFINITY,
  })
  const profile = identityQuery.data
  return (
    <details
      className="participant-identity"
      onToggle={(event) => setOpened(event.currentTarget.open)}
    >
      <summary aria-label={`Идентичность участника: ${name}`}>
        {name}<Fingerprint aria-hidden="true" />
      </summary>
      <div className="identity-popover" role="note">
        <header>
          <div><span>Source-backed identity</span><strong>{name}</strong></div>
          <small>{profile ? number.format(profile.message_count) : '…'} сообщений</small>
        </header>
        {identityQuery.isLoading ? <p>Загружаем provenance…</p> : null}
        {identityQuery.error ? <p>Не удалось загрузить identity provenance.</p> : null}
        {profile ? (
          <>
            <section>
              <h5>ID / login</h5>
              {profile.identities.map((identity) => (
                <code key={`${identity.platform}-${identity.external_id}`}>
                  {identity.external_id}
                </code>
              ))}
            </section>
            <section>
              <h5>Основание</h5>
              {profile.identity_basis.map((basis) => (
                <span key={basis.basis}>
                  {basisLabels[basis.basis] ?? basis.basis} · {number.format(basis.messages)}
                </span>
              ))}
            </section>
            <section>
              <h5>Наблюдаемые имена</h5>
              <div className="identity-aliases">
                {profile.observed_names.map((alias) => (
                  <span key={alias.name}>{alias.name} · {number.format(alias.messages)}</span>
                ))}
              </div>
            </section>
            {profile.roster_aliases.length ? (
              <section className="roster-aliases">
                <h5>Имена из source roster</h5>
                {profile.roster_aliases.map((alias) => (
                  <div key={`${alias.external_id}-${alias.alias}`}>
                    <strong>{alias.alias}</strong>
                    <code>{alias.external_id}</code>
                    {alias.evidence_message_ids[0] && onOpenEvidence ? (
                      <button
                        type="button"
                        onClick={() => onOpenEvidence(alias.evidence_message_ids[0])}
                      >
                        Источник<ExternalLink />
                      </button>
                    ) : null}
                  </div>
                ))}
              </section>
            ) : null}
            <p className="identity-guardrail"><AlertTriangle /> {profile.guardrail}</p>
          </>
        ) : null}
      </div>
    </details>
  )
}
