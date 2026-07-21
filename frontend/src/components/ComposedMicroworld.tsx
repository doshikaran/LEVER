import type { ComposedWidgetConfig } from '../types'

type ComposedMicroworldProps = Readonly<{
  config: ComposedWidgetConfig
}>

const CELL_LABELS: Record<ComposedWidgetConfig['cells'][number]['variant'], string> = {
  base: 'Base',
  A: 'A',
  B: 'B',
  AB: 'AB',
}

/**
 * A factual 2×2 view: every displayed corner is an executed harness result.
 * It is deliberately separate from the normal A/B widget until Session Ledger
 * selection can provide a real materialized AB checkout.
 */
export function ComposedMicroworld({ config }: ComposedMicroworldProps) {
  const { interaction } = config
  return (
    <section
      aria-label="Composed microworld"
      data-testid="composed-microworld"
      className="lever-panel space-y-4 rounded-2xl p-4"
    >
      <header>
        <h2 className="text-base font-semibold text-[var(--lever-text)]">Composed microworld</h2>
        <p className="text-sm text-[var(--lever-text)]">
          Four executed versions at one shared input — AB is measured, never inferred.
        </p>
      </header>

      <div className="grid grid-cols-2 gap-3" aria-label="Executed 2 by 2 composition results">
        {config.cells.map((cell) => (
          <article
            key={cell.variant}
            data-testid={`composition-cell-${cell.variant}`}
            className="rounded-md border border-[var(--lever-text)]/20 bg-[var(--lever-background)] p-3"
          >
            <h3 className="font-medium text-[var(--lever-text)]">{CELL_LABELS[cell.variant]}</h3>
            <p className="mt-1 text-sm text-[var(--lever-text)]">
              {config.observableLabel}: <output>{cell.observation}</output>{config.unit ? ` ${config.unit}` : ''}
            </p>
          </article>
        ))}
      </div>

      {interaction.detected ? (
        <aside
          aria-label="Behavioral merge conflict"
          data-testid="behavioral-merge-conflict"
          className="rounded-md border-2 border-[var(--lever-warning)] bg-[var(--lever-background)] p-4 text-[var(--lever-text)]"
        >
          <h3 className="font-semibold text-[var(--lever-warning)]">⚠️ Behavioral merge conflict.</h3>
          <p className="mt-1">{interaction.caption}</p>
          <p className="mt-2 text-sm">
            AB: {interaction.observedAB}; additive expectation: {interaction.additiveExpectation}; deviation: {interaction.deviation}.
          </p>
        </aside>
      ) : null}
    </section>
  )
}
