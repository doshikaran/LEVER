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
  const hasReport = event.divergenceReport.length > 0

  return (
    <section
      aria-labelledby="degradation-heading"
      className="max-w-3xl space-y-5 rounded-xl border-2 border-[var(--lever-warning)] bg-[var(--lever-surface)] p-6 text-[var(--lever-text)]"
      data-testid="degradation-panel"
    >
      <h2 id="degradation-heading" className="text-xl font-semibold">
        I couldn't build a faithful model of this change.
      </h2>
      <p>{event.degradeReason}</p>

      {hasReport ? (
        <div className="space-y-3">
          <button
            type="button"
            className="font-medium text-[var(--lever-warning)] underline"
            onClick={() => setShowReport((visible) => !visible)}
            aria-expanded={showReport}
          >
            {showReport ? 'Hide divergence report' : '[Show me →]'}
          </button>
          {showReport ? (
            <div aria-label="Divergence report" className="overflow-x-auto rounded border border-[var(--lever-warning)]/50 bg-[var(--lever-background)] p-3">
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
                      <td><code>{JSON.stringify(entry.position)}</code></td>
                      <td>{entry.version}</td>
                      <td>{entry.observable}</td>
                      <td><code>{JSON.stringify(entry.harness)}</code></td>
                      <td><code>{JSON.stringify(entry.reference)}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="space-y-1">
        <p className="font-medium">
          Here's a plain explanation instead — and here's the one input I'd manually test.
        </p>
        <p>{event.plainExplanation}</p>
      </div>
    </section>
  )
}
