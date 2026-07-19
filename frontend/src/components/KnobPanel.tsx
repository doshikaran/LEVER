import { useMicroworldStore } from '../store/useMicroworldStore'
import type { ControlDescriptor, NumericDomain } from '../types'

type KnobPanelProps = Readonly<{
  controls: readonly ControlDescriptor[]
}>

function isNumericDomain(
  domain: ControlDescriptor['domain'],
): domain is NumericDomain {
  return 'min' in domain
}

/** Mechanical knob control selection from the InteractionSpec's control descriptors. */
export function KnobPanel({ controls }: KnobPanelProps) {
  const position = useMicroworldStore((state) => state.position)
  const setKnob = useMicroworldStore((state) => state.setKnob)

  return (
    <section aria-label="Simulation controls" className="space-y-5">
      <h2 className="text-lg font-semibold text-slate-950">Controls</h2>
      {controls.map((control) => {
        const value = position[control.id] ?? control.default
        const inputId = `knob-${control.id}`

        if (control.type === 'boolean') {
          return (
            <label key={control.id} className="flex items-center justify-between gap-3 text-sm text-slate-900" htmlFor={inputId}>
              <span>{control.label}</span>
              <input
                id={inputId}
                type="checkbox"
                role="switch"
                checked={Boolean(value)}
                onChange={(event) => setKnob(control.id, event.target.checked)}
              />
            </label>
          )
        }

        if (control.type === 'enum' && !isNumericDomain(control.domain)) {
          return (
            <fieldset key={control.id} className="space-y-2">
              <legend className="text-sm font-medium text-slate-900">{control.label}</legend>
              <div className="flex flex-wrap gap-2">
                {control.domain.values.map((option) => (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={value === option}
                    onClick={() => setKnob(control.id, option)}
                    className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900 aria-pressed:border-blue-600 aria-pressed:bg-blue-600 aria-pressed:text-white"
                  >
                    {option}
                  </button>
                ))}
              </div>
            </fieldset>
          )
        }

        if (!isNumericDomain(control.domain)) return null
        const numericValue = typeof value === 'number' ? value : Number(value)
        return (
          <div key={control.id} className="space-y-2">
            <label htmlFor={inputId} className="flex justify-between gap-3 text-sm font-medium text-slate-900">
              <span>{control.label}</span>
              <span className="font-normal text-slate-600">{control.unit ?? ''}</span>
            </label>
            <div className="flex items-center gap-3">
              <input
                id={inputId}
                className="min-w-0 flex-1"
                type="range"
                min={control.domain.min}
                max={control.domain.max}
                step={control.domain.step}
                value={numericValue}
                onChange={(event) => setKnob(control.id, Number(event.target.value))}
              />
              <input
                aria-label={`${control.label} numeric value`}
                className="w-24 rounded border border-slate-300 px-2 py-1 text-right text-sm"
                type="number"
                min={control.domain.min}
                max={control.domain.max}
                step={control.domain.step}
                value={numericValue}
                onChange={(event) => {
                  const next = event.target.valueAsNumber
                  if (Number.isFinite(next)) setKnob(control.id, next)
                }}
              />
            </div>
          </div>
        )
      })}
    </section>
  )
}
