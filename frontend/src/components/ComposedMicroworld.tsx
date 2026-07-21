import type { ComposedWidgetConfig } from '../types'

type ComposedMicroworldProps = Readonly<{
  config: ComposedWidgetConfig
}>

const CELL_LABELS: Record<ComposedWidgetConfig['cells'][number]['variant'], string> = {
  base: 'Base',
  A: 'Change A',
  B: 'Change B',
  AB: 'A + B',
}

const CELL_HINTS: Record<ComposedWidgetConfig['cells'][number]['variant'], string> = {
  base: 'Neither change',
  A: 'Tenant windows only',
  B: 'Raised limit only',
  AB: 'Both merged',
}

/**
 * A factual 2×2 view: every displayed corner is an executed harness result.
 * It is deliberately separate from the normal A/B widget until Session Ledger
 * selection can provide a real materialized AB checkout.
 */
export function ComposedMicroworld({ config }: ComposedMicroworldProps) {
  const { interaction } = config
  const maxObs = Math.max(...config.cells.map((cell) => Math.abs(cell.observation)), 1)

  return (
    <section
      aria-label="Composed microworld"
      data-testid="composed-microworld"
      className="lever-panel animate-rise space-y-5 rounded-2xl p-5"
    >
      <header className="space-y-1">
        <h2 className="font-display text-xl font-bold text-[var(--lever-text)]">Compose 2×2</h2>
        <p className="text-sm text-[var(--lever-muted)]">
          Four executed versions at one shared input — AB is measured, never inferred.
        </p>
        <p className="font-mono text-xs text-[var(--lever-muted)]">
          Input · {Object.entries(config.position).map(([key, value]) => `${key}=${String(value)}`).join(' · ')}
        </p>
      </header>

      <div className="grid grid-cols-2 gap-3" aria-label="Executed 2 by 2 composition results">
        {config.cells.map((cell) => {
          const hot = cell.variant === 'AB' && interaction.detected
          const pct = Math.max(8, (Math.abs(cell.observation) / maxObs) * 100)
          return (
            <article
              key={cell.variant}
              data-testid={`composition-cell-${cell.variant}`}
              className={`rounded-xl border p-4 transition-colors ${
                hot
                  ? 'border-[var(--lever-warning)] bg-orange-50/80 ring-2 ring-[var(--lever-warning)]/30'
                  : 'border-slate-200 bg-slate-50/70'
              }`}
            >
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {CELL_LABELS[cell.variant]}
              </p>
              <p className="mt-0.5 text-[10px] text-[var(--lever-muted)]">{CELL_HINTS[cell.variant]}</p>
              <p className="mt-2 font-display text-3xl font-bold text-[var(--lever-text)]">
                {cell.observation}
                {config.unit ? (
                  <span className="ml-1 text-sm font-medium text-[var(--lever-muted)]">{config.unit}</span>
                ) : null}
              </p>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${
                    hot ? 'bg-[var(--lever-warning)]' : 'bg-[var(--lever-primary)]'
                  }`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </article>
          )
        })}
      </div>

      {interaction.detected ? (
        <aside
          aria-label="Behavioral merge conflict"
          data-testid="behavioral-merge-conflict"
          className="rounded-xl border-2 border-[var(--lever-warning)] bg-orange-50 px-4 py-3 text-[var(--lever-text)]"
        >
          <h3 className="font-display font-semibold text-[var(--lever-warning)]">
            Behavioral merge conflict
          </h3>
          <p className="mt-1 text-sm">{interaction.caption}</p>
          <p className="mt-2 font-mono text-xs text-[var(--lever-muted)]">
            AB {interaction.observedAB} vs additive {interaction.additiveExpectation} · Δ {interaction.deviation}
          </p>
        </aside>
      ) : (
        <p className="rounded-xl bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-700">
          No interaction — AB matches the additive expectation within tolerance.
        </p>
      )}
    </section>
  )
}
