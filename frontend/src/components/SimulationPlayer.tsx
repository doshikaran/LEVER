/** Right-side unified "run old vs new on the same input" simulation player. */

import type { ControlDescriptor, KnobPosition } from '../types'

type SimulationPlayerProps = Readonly<{
  observableLabel: string
  unit: string | null
  baseValue: number
  headValue: number
  baseLabel: string
  headLabel: string
  divergence: number
  position: KnobPosition
  controls: readonly ControlDescriptor[]
  caption: string | null
  measuredCount: number
  isPlaying: boolean
  canPlay: boolean
  onPlayToggle: () => void
  hidePlay?: boolean
}>

function formatKnob(control: ControlDescriptor, value: unknown): string {
  if (value === undefined || value === null) return '—'
  if (typeof value === 'number') {
    const rounded = Number.isInteger(value) ? value : Number(value.toFixed(2))
    return control.unit ? `${rounded} ${control.unit}` : String(rounded)
  }
  return String(value)
}

function isNumeric(value: number, label: string): boolean {
  return Number.isFinite(value) && label.trim() !== '' && !Number.isNaN(Number(label))
}

export function SimulationPlayer({
  observableLabel,
  unit,
  baseValue,
  headValue,
  baseLabel,
  headLabel,
  divergence,
  position,
  controls,
  caption,
  measuredCount,
  isPlaying,
  canPlay,
  onPlayToggle,
  hidePlay = false,
}: SimulationPlayerProps) {
  const diverges = divergence > 0
  const numeric = isNumeric(baseValue, baseLabel) && isNumeric(headValue, headLabel)
  const scale = numeric ? Math.max(Math.abs(baseValue), Math.abs(headValue), 1) : 1
  const basePct = numeric ? Math.max(4, (Math.abs(baseValue) / scale) * 100) : 100
  const headPct = numeric ? Math.max(4, (Math.abs(headValue) / scale) * 100) : 100

  const unitSuffix = unit ? ` ${unit}` : ''

  return (
    <section
      data-testid="simulation-player"
      className="lever-panel flex h-full flex-col gap-4 rounded-2xl p-5"
      aria-label="Simulation"
    >
      <header className="flex items-start justify-between gap-3">
        <div>
          <p className="font-display text-base font-semibold text-[var(--lever-text)]">Simulation</p>
          <p className="text-xs text-[var(--lever-muted)]">
            Same input fed to both versions · {observableLabel}
          </p>
        </div>
        {hidePlay ? null : (
          <button
            type="button"
            data-testid="sim-play-inline"
            onClick={onPlayToggle}
            disabled={!canPlay}
            className="lever-btn rounded-xl border border-[var(--lever-primary)] bg-[var(--lever-primary)] px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            {isPlaying ? '⏸ Pause' : '▶ Play'}
          </button>
        )}
      </header>

      <div className="flex flex-wrap gap-2" aria-label="Current input">
        {controls.map((control) => (
          <span
            key={control.id}
            className="lever-chip rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs"
          >
            <span className="text-[var(--lever-muted)]">{control.label}:</span>{' '}
            <span className="font-semibold text-[var(--lever-text)]">
              {formatKnob(control, position[control.id])}
            </span>
          </span>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Old code</p>
          <p className="mt-1 font-display text-3xl font-bold text-slate-700">
            {baseLabel}
            {numeric ? <span className="text-base font-medium text-slate-400">{unitSuffix}</span> : null}
          </p>
          <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-slate-200">
            <div
              className="h-full rounded-full bg-slate-400 transition-all duration-700 ease-out"
              style={{ width: `${basePct}%` }}
            />
          </div>
        </div>
        <div
          className={`rounded-xl border p-4 transition-colors ${
            diverges
              ? 'border-[var(--lever-warning)] bg-orange-50/70'
              : 'border-[var(--lever-primary)]/40 bg-[var(--lever-primary)]/5'
          }`}
        >
          <p className="text-xs font-semibold uppercase tracking-wide text-[var(--lever-primary)]">
            New code
          </p>
          <p
            className={`mt-1 font-display text-3xl font-bold ${
              diverges ? 'text-[var(--lever-warning)]' : 'text-[var(--lever-primary)]'
            }`}
          >
            {headLabel}
            {numeric ? <span className="text-base font-medium opacity-60">{unitSuffix}</span> : null}
          </p>
          <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-slate-200">
            <div
              className={`h-full rounded-full transition-all duration-700 ease-out ${
                diverges ? 'bg-[var(--lever-warning)]' : 'bg-[var(--lever-primary)]'
              }`}
              style={{ width: `${headPct}%` }}
            />
          </div>
        </div>
      </div>

      <div
        data-testid="sim-verdict"
        className={`rounded-xl px-4 py-3 text-sm font-semibold ${
          diverges
            ? 'bg-orange-50 text-[var(--lever-warning)]'
            : 'bg-emerald-50 text-emerald-700'
        }`}
        aria-live="polite"
      >
        {diverges ? 'The versions diverge on this input.' : 'Both versions behave identically here.'}
        {caption ? <span className="ml-1 font-normal text-[var(--lever-text)]">{caption}</span> : null}
      </div>

      <p className="mt-auto text-xs text-[var(--lever-muted)]">
        {measuredCount > 0
          ? `Replaying ${measuredCount} measured position${measuredCount === 1 ? '' : 's'} — no guesses, real executions only.`
          : 'Adjust the input on the left to compare measured outputs.'}
      </p>
    </section>
  )
}
