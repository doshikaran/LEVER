import { useState } from 'react'
import type { DegradationEvent } from '../types'

type DegradationPanelProps = Readonly<{ event: DegradationEvent }>

/**
 * The only terminal presentation for an unverified microworld.  It deliberately
 * has no widget or chart dependency: a degraded result is an honest refusal,
 * never a smaller version of the interactive product.
 */
export function DegradationPanel({ event }: DegradationPanelProps) {
  const [showReport, setShowReport] = useState(false)
  const [showScopes, setShowScopes] = useState(false)
  const hasReport = event.divergenceReport.length > 0
  const recipe = event.manualTestRecipe ?? []
  const notes = event.staticNotes ?? []
  const scopes = event.proposedSpecs ?? []

  return (
    <section
      aria-labelledby="degradation-heading"
      className="lever-panel animate-rise max-w-3xl space-y-5 rounded-2xl border-2 border-[var(--lever-warning)]/70 p-6 text-[var(--lever-text)]"
      data-testid="degradation-panel"
    >
      <h2 id="degradation-heading" className="font-display text-2xl font-bold tracking-tight">
        I couldn't build a faithful model of this change.
      </h2>
      <p className="leading-relaxed text-[var(--lever-muted)]">{event.degradeReason}</p>

      {hasReport ? (
        <div className="space-y-3">
          <button
            type="button"
            className="font-semibold text-[var(--lever-warning)] underline decoration-2 underline-offset-4"
            onClick={() => setShowReport((visible) => !visible)}
            aria-expanded={showReport}
          >
            {showReport ? 'Hide divergence report' : '[Show me →]'}
          </button>
          {showReport ? (
            <div aria-label="Divergence report" className="overflow-x-auto rounded-xl border border-[var(--lever-warning)]/40 bg-orange-50/60 p-3">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr>
                    <th>Sampled input</th>
                    <th>Version</th>
                    <th>Observable</th>
                    <th>Harness</th>
                    <th>Real code</th>
                  </tr>
                </thead>
                <tbody>
                  {event.divergenceReport.map((entry, index) => (
                    <tr key={`${entry.version}-${entry.observable}-${index}`}>
                      <td><code className="font-mono text-xs">{JSON.stringify(entry.position)}</code></td>
                      <td>{entry.version}</td>
                      <td>{entry.observable}</td>
                      <td><code className="font-mono text-xs">{JSON.stringify(entry.harness)}</code></td>
                      <td><code className="font-mono text-xs">{JSON.stringify(entry.reference)}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="space-y-2 rounded-xl bg-slate-50 p-4">
        <p className="font-display text-base font-semibold">
          Plain explanation — and what to test by hand
        </p>
        <p className="text-[var(--lever-muted)]">{event.plainExplanation}</p>
        {recipe.length > 0 ? (
          <ol
            data-testid="manual-test-recipe"
            className="mt-3 list-decimal space-y-2 pl-5 text-sm text-[var(--lever-text)]"
          >
            {recipe.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        ) : null}
      </div>

      {notes.length > 0 ? (
        <aside
          data-testid="static-notes"
          className="space-y-2 rounded-xl border border-dashed border-slate-300 bg-white p-4 text-sm text-[var(--lever-muted)]"
        >
          <p className="font-semibold uppercase tracking-[0.12em] text-slate-500">
            Unverified static notes
          </p>
          <ul className="list-disc space-y-1 pl-5">
            {notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </aside>
      ) : null}

      {scopes.length > 0 ? (
        <div className="space-y-2">
          <button
            type="button"
            className="text-sm font-semibold text-[var(--lever-secondary)] underline underline-offset-4"
            onClick={() => setShowScopes((open) => !open)}
            aria-expanded={showScopes}
          >
            {showScopes ? 'Hide drafted scopes' : `Show ${scopes.length} drafted scope card${scopes.length === 1 ? '' : 's'}`}
          </button>
          {showScopes ? (
            <ul data-testid="scope-cards" className="grid gap-2 sm:grid-cols-2">
              {scopes.map((spec, index) => (
                <li
                  key={`${String(spec.thesis ?? index)}-${index}`}
                  className="lever-panel rounded-xl p-3 text-sm"
                >
                  <p className="font-display font-semibold">{String(spec.thesis ?? `Draft ${index + 1}`)}</p>
                  <p className="mt-1 text-xs text-[var(--lever-muted)]">
                    Pack: {String(spec.domainPack ?? 'unknown')} · draft only
                  </p>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
