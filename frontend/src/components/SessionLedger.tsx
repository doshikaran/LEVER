type LedgerEntry = Readonly<{ changeId: string; thesis: string }>

type SessionLedgerProps = Readonly<{
  entries: readonly LedgerEntry[]
  onOpen: (changeId: string) => void
}>

/** Part 1.9's sidebar list of every microworld generated this session. */
export function SessionLedger({ entries, onOpen }: SessionLedgerProps) {
  if (entries.length === 0) {
    return <p className="text-sm opacity-60">No microworlds generated yet.</p>
  }
  return (
    <ul aria-label="Session ledger" className="space-y-1 text-sm">
      {entries.map((entry) => (
        <li key={entry.changeId}>
          <button type="button" onClick={() => onOpen(entry.changeId)} className="text-left hover:underline">
            {entry.thesis}
          </button>
        </li>
      ))}
    </ul>
  )
}
