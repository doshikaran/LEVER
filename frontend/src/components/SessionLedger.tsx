type SessionRow = Readonly<{
  changeId: string
  outcome: string
  title: string
  savedAt: string | null
  fidelityBand: string | null
  speculative: boolean
}>

type SessionLedgerProps = Readonly<{
  sessions: readonly SessionRow[]
  activeChangeId: string | null
  onOpen: (changeId: string) => void
}>

/** Durable session list for permalink browsing — never invents results. */
export function SessionLedger({ sessions, activeChangeId, onOpen }: SessionLedgerProps) {
  if (sessions.length === 0) {
    return (
      <section
        aria-label="Session ledger"
        className="lever-panel rounded-2xl border-dashed p-4 text-sm text-[var(--lever-muted)]"
      >
        No saved microworlds yet. Analyze a PR or demo to start the ledger.
      </section>
    )
  }

  return (
    <section aria-label="Session ledger" className="lever-panel space-y-3 rounded-2xl p-4">
      <h2 className="font-display text-sm font-bold uppercase tracking-[0.14em] text-[var(--lever-muted)]">
        Session ledger
      </h2>
      <ul className="max-h-72 space-y-2 overflow-y-auto">
        {sessions.map((session) => {
          const active = session.changeId === activeChangeId
          return (
            <li key={session.changeId}>
              <button
                type="button"
                data-testid="session-ledger-row"
                onClick={() => onOpen(session.changeId)}
                className={`lever-chip w-full rounded-xl border px-3 py-2.5 text-left text-sm ${
                  active
                    ? 'border-transparent bg-[var(--lever-primary)] text-white shadow-md shadow-teal-900/10'
                    : 'border-slate-200 bg-white text-[var(--lever-text)] hover:border-[var(--lever-primary)]/35'
                }`}
              >
                <span className="block font-semibold">{session.title}</span>
                <span className={`mt-0.5 block text-xs ${active ? 'text-white/80' : 'text-[var(--lever-muted)]'}`}>
                  {session.outcome}
                  {session.fidelityBand ? ` · ${session.fidelityBand}` : ''}
                  {session.speculative ? ' · prospective' : ''}
                  {session.savedAt ? ` · ${new Date(session.savedAt).toLocaleString()}` : ''}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export type { SessionRow }
