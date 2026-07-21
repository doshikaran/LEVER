/** Side-by-side active-state stage for the state-workflow genre. */

import type { WidgetConfig } from '../types'

type WorkflowStageProps = Readonly<{
  widget: WidgetConfig
  baseState: string
  headState: string
  divergence: number
}>

function nodeClass(active: boolean, diverge: boolean) {
  if (active && diverge) {
    return 'border-[var(--lever-warning)] bg-orange-50 ring-2 ring-[var(--lever-warning)]/40'
  }
  if (active) {
    return 'border-[var(--lever-primary)] bg-teal-50 ring-2 ring-[var(--lever-primary)]/30'
  }
  return 'border-slate-200 bg-white opacity-55'
}

/**
 * Measured node-state comparison — active nodes only, never invented transitions.
 */
export function WorkflowStage({ widget, baseState, headState, divergence }: WorkflowStageProps) {
  const states = Array.from(new Set([baseState, headState].filter(Boolean)))
  const diverge = baseState !== headState

  return (
    <section
      data-testid="workflow-stage"
      aria-label="State workflow"
      className="lever-panel space-y-4 rounded-2xl p-4"
    >
      <header className="space-y-1">
        <h2 className="font-display text-lg font-bold">Workflow</h2>
        <p className="text-sm text-[var(--lever-muted)]">
          Active node only · Δ {(divergence * 100).toFixed(0)}%
        </p>
      </header>
      <div className="grid gap-4 sm:grid-cols-2">
        {(['base', 'head'] as const).map((lane) => {
          const active = lane === 'base' ? baseState : headState
          return (
            <div key={lane} className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--lever-muted)]">
                {lane}
              </p>
              <ul className="space-y-2">
                {(states.length > 0 ? states : [active || 'unknown']).map((state) => (
                  <li
                    key={`${lane}-${state}`}
                    data-active={state === active ? 'true' : 'false'}
                    className={`rounded-xl border px-3 py-3 text-sm font-semibold transition ${nodeClass(state === active, diverge && state === active)}`}
                  >
                    {state}
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>
      {widget.surpriseMarker ? (
        <p className="text-sm text-[var(--lever-warning)]">{widget.surpriseMarker.caption}</p>
      ) : null}
    </section>
  )
}
