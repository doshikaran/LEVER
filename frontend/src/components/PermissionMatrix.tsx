/** Full-bleed permission / access-matrix stage bound to measured cell values. */

import { useMicroworldStore } from '../store/useMicroworldStore'
import type { ControlDescriptor, KnobPosition, WidgetConfig } from '../types'

type PermissionMatrixProps = Readonly<{
  widget: WidgetConfig
  baseValue: number
  headValue: number
  divergence: number
  onCellActivate?: () => void
}>

function enumValues(control: ControlDescriptor): readonly string[] {
  const domain = control.domain as { values?: readonly string[] }
  return domain.values ?? []
}

function cellLabel(value: number) {
  if (value === 1) return 'allow'
  if (value === 0) return 'deny'
  return String(value)
}

/**
 * Keyboard-accessible matrix for the access-matrix genre.
 * Axes come from controls with axisRole x/y; fallback is the first two enums.
 */
export function PermissionMatrix({
  widget,
  baseValue,
  headValue,
  divergence,
  onCellActivate,
}: PermissionMatrixProps) {
  const position = useMicroworldStore((state) => state.position)
  const replacePosition = useMicroworldStore((state) => state.replacePosition)
  const xControl = widget.controls.find((control) => control.axisRole === 'x')
    ?? widget.controls.find((control) => control.type === 'enum')
    ?? null
  const yControl = widget.controls.find((control) => control.axisRole === 'y')
    ?? widget.controls.filter((control) => control.type === 'enum').at(1)
    ?? null
  const xValues = xControl ? enumValues(xControl) : []
  const yValues = yControl ? enumValues(yControl) : []

  const setCell = (next: KnobPosition) => {
    replacePosition({ ...position, ...next })
    onCellActivate?.()
  }

  const split = baseValue !== headValue

  return (
    <section
      data-testid="permission-matrix"
      aria-label="Permission matrix"
      className="space-y-3 rounded-xl border border-[var(--lever-text)]/20 bg-[var(--lever-surface)] p-4"
    >
      <header className="space-y-1">
        <h2 className="text-base font-semibold">Access matrix</h2>
        <p className="text-sm text-[var(--lever-text)]">
          Measured allow/deny at the selected cell · Δ {(divergence * 100).toFixed(0)}%
        </p>
      </header>

      {xControl && yControl && xValues.length > 0 && yValues.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[28rem] border-collapse text-sm">
            <thead>
              <tr>
                <th className="p-2 text-left font-medium">{yControl.label} \\ {xControl.label}</th>
                {xValues.map((xValue) => (
                  <th key={xValue} className="p-2 font-medium">{xValue}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {yValues.map((yValue) => (
                <tr key={yValue}>
                  <th scope="row" className="p-2 text-left font-medium">{yValue}</th>
                  {xValues.map((xValue) => {
                    const selected = position[xControl.id] === xValue && position[yControl.id] === yValue
                    return (
                      <td key={`${xValue}-${yValue}`} className="p-1">
                        <button
                          type="button"
                          aria-pressed={selected}
                          aria-label={`${yControl.label} ${yValue}, ${xControl.label} ${xValue}`}
                          onClick={() => setCell({ [xControl.id]: xValue, [yControl.id]: yValue })}
                          className={`flex h-14 w-full flex-col items-center justify-center rounded-md border text-xs transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--lever-primary)] ${
                            selected
                              ? split
                                ? 'border-[var(--lever-warning)] bg-[var(--lever-warning)]/15 ring-2 ring-[var(--lever-warning)]/40'
                                : 'border-[var(--lever-primary)] bg-[var(--lever-primary)]/10 ring-2 ring-[var(--lever-primary)]/30'
                              : 'border-[var(--lever-text)]/15 bg-[var(--lever-background)] hover:border-[var(--lever-primary)]/50'
                          }`}
                        >
                          {selected ? (
                            <>
                              <span>B {cellLabel(baseValue)}</span>
                              <span>H {cellLabel(headValue)}</span>
                            </>
                          ) : (
                            <span className="text-[var(--lever-text)]/50">select</span>
                          )}
                        </button>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div
          data-testid="permission-matrix-current"
          className={`grid gap-3 rounded-lg border p-4 sm:grid-cols-2 ${
            split ? 'border-[var(--lever-warning)]' : 'border-[var(--lever-text)]/20'
          }`}
        >
          <div>
            <p className="text-xs uppercase tracking-wide text-[var(--lever-text)]/70">Base</p>
            <p className="text-2xl font-semibold">{cellLabel(baseValue)}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-[var(--lever-text)]/70">Head</p>
            <p className="text-2xl font-semibold">{cellLabel(headValue)}</p>
          </div>
        </div>
      )}

      {widget.surpriseMarker ? (
        <p className="text-sm text-[var(--lever-warning)]" data-testid="matrix-surprise">
          {widget.surpriseMarker.caption}
        </p>
      ) : null}
    </section>
  )
}
