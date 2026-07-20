import { useMemo } from 'react'
import type { ControlDescriptor, KnobPosition, SearchTracePoint } from '../types'

type SearchTraceProps = Readonly<{
  /** Real points as the Adversary emits them; this component never invents samples. */
  points: readonly SearchTracePoint[]
  controls: readonly ControlDescriptor[]
  /** A forward lookup: select an already-evaluated position, never solve for one. */
  onSelectPosition: (position: KnobPosition) => void
}>

type Axis = Readonly<{
  id: string
  label: string
  values: readonly (number | string | boolean)[]
}>

function axisFor(
  points: readonly SearchTracePoint[],
  controls: readonly ControlDescriptor[],
  index: number,
): Axis | null {
  const ids = controls.map((control) => control.id)
  if (ids[index] === undefined) {
    const discovered = Array.from(
      new Set(points.flatMap((point) => Object.keys(point.position))),
    ).sort()
    ids.push(...discovered.filter((id) => !ids.includes(id)))
  }
  const id = ids[index]
  if (id === undefined) return null
  const control = controls.find((candidate) => candidate.id === id)
  const values = Array.from(
    new Set(points.map((point) => point.position[id]).filter((value) => value !== undefined)),
  ) as (number | string | boolean)[]
  return { id, label: control?.label ?? id, values }
}

function normalizedAxisValue(value: unknown, axis: Axis | null) {
  if (axis === null || value === undefined) return 0.5
  const values = axis.values
  if (typeof value === 'number') {
    const numericValues = values.filter((candidate): candidate is number => typeof candidate === 'number')
    const min = Math.min(...numericValues)
    const max = Math.max(...numericValues)
    return max === min ? 0.5 : (value - min) / (max - min)
  }
  const index = values.findIndex((candidate) => candidate === value)
  return values.length <= 1 ? 0.5 : Math.max(0, index) / (values.length - 1)
}

function markerColor(objective: number) {
  const hotness = Math.max(0, Math.min(1, objective))
  return `color-mix(in srgb, var(--lever-secondary) ${(1 - hotness) * 100}%, var(--lever-primary))`
}

/**
 * A live view of Adversary's actual Sobol exploration and coordinate-ascent
 * probes. It projects the first two declared knobs while retaining each full
 * position for the cache-backed click action.
 */
export function SearchTrace({ points, controls, onSelectPosition }: SearchTraceProps) {
  const [xAxis, yAxis] = useMemo(
    () => [axisFor(points, controls, 0), axisFor(points, controls, 1)],
    [controls, points],
  )
  const exploreCount = points.filter((point) => point.phase === 'explore').length
  const exploitCount = points.length - exploreCount

  return (
    <section
      aria-label="Live adversary search trace"
      className="rounded-lg border border-[var(--lever-text)]/20 bg-[var(--lever-surface)] p-4 shadow-sm"
    >
      <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-[var(--lever-text)]">Search trace</h2>
          <p className="text-sm text-[var(--lever-text)]">
            {points.length} sampled positions · {exploreCount} Sobol · {exploitCount} ascent
          </p>
        </div>
        <p className="text-sm text-[var(--lever-text)]">Color: lower → higher objective</p>
      </header>

      <div
        role="img"
        aria-label={`Point cloud over ${xAxis?.label ?? 'the first knob'} and ${yAxis?.label ?? 'the second knob'} with ${points.length} sampled KnobPositions from the real search.`}
        className="relative h-64 overflow-hidden rounded-md border border-[var(--lever-text)]/20 bg-[var(--lever-background)]"
      >
        <div className="pointer-events-none absolute inset-x-3 bottom-7 top-3 border-b border-l border-[var(--lever-text)]/35" />
        {points.map((point, index) => {
          const x = 8 + normalizedAxisValue(point.position[xAxis?.id ?? ''], xAxis) * 84
          const y = yAxis === null
            ? 50
            : 88 - normalizedAxisValue(point.position[yAxis.id], yAxis) * 76
          const label = Object.entries(point.position)
            .map(([id, value]) => `${id}=${String(value)}`)
            .join(', ')
          return (
            <button
              key={`${point.phase}-${index}-${label}`}
              type="button"
              data-testid="search-trace-point"
              aria-label={`${point.phase === 'explore' ? 'Sobol' : 'Coordinate-ascent'} point: ${label}; objective ${point.divergence.toFixed(3)}. Select this cached position.`}
              onClick={() => onSelectPosition(point.position)}
              className="absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 border border-[var(--lever-surface)] shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--lever-primary)]"
              style={{
                left: `${x}%`,
                top: `${y}%`,
                backgroundColor: markerColor(point.divergence),
                borderRadius: point.phase === 'explore' ? '9999px' : '1px',
                transform: point.phase === 'explore'
                  ? 'translate(-50%, -50%)'
                  : 'translate(-50%, -50%) rotate(45deg)',
                opacity: 0.4 + Math.max(0, Math.min(1, point.divergence)) * 0.6,
              }}
            >
              <span className="sr-only">{label}</span>
            </button>
          )
        })}
        <span className="absolute bottom-2 left-4 text-xs text-[var(--lever-text)]">
          {xAxis?.label ?? 'First knob'}
        </span>
        <span className="absolute left-1 top-3 -rotate-90 origin-top-left text-xs text-[var(--lever-text)]">
          {yAxis?.label ?? 'Second knob'}
        </span>
      </div>

      <p className="mt-3 text-sm text-[var(--lever-text)]">
        Click a point to inspect its already-cached forward evaluation.
      </p>
    </section>
  )
}
