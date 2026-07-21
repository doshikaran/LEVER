import { useEffect, useState } from 'react'
import type { ControlDescriptor, KnobPosition, ObservationBundle } from '../types'

type PermissionGridProps = Readonly<{
  controls: readonly ControlDescriptor[]
  observableId: string
  basePosition: KnobPosition
  onCellsNeeded: (positions: readonly KnobPosition[]) => Promise<Record<string, ObservationBundle>>
}>

function isEnumDomain(domain: ControlDescriptor['domain']): domain is { values: readonly string[] } {
  return 'values' in domain
}

/** Renders the permission pack's matrixCell observable as a tappable x/y grid. */
export function PermissionGrid({ controls, observableId, basePosition, onCellsNeeded }: PermissionGridProps) {
  const xControl = controls.find((control) => control.axisRole === 'x')
  const yControl = controls.find((control) => control.axisRole === 'y')
  const [cells, setCells] = useState<Record<string, ObservationBundle>>({})

  useEffect(() => {
    if (!xControl || !yControl || !isEnumDomain(xControl.domain) || !isEnumDomain(yControl.domain)) return
    const positions: KnobPosition[] = []
    for (const xValue of xControl.domain.values) {
      for (const yValue of yControl.domain.values) {
        positions.push({ ...basePosition, [xControl.id]: xValue, [yControl.id]: yValue })
      }
    }
    let cancelled = false
    onCellsNeeded(positions).then((result) => {
      if (!cancelled) setCells(result)
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [xControl?.id, yControl?.id])

  if (!xControl || !yControl || !isEnumDomain(xControl.domain) || !isEnumDomain(yControl.domain)) {
    return <p role="alert">Permission grid requires two enum knobs with axisRole x/y.</p>
  }

  // Capture the narrowed enum values once: TypeScript's control-flow narrowing
  // of `xControl.domain` (a member access, not a plain variable) does not
  // reliably survive into the doubly-nested JSX map callbacks below.
  const xValues = xControl.domain.values
  const yValues = yControl.domain.values
  const xId = xControl.id
  const yId = yControl.id

  return (
    <table role="grid" aria-label="Permission matrix" className="border-collapse">
      <thead>
        <tr>
          <th />
          {xValues.map((xValue) => (
            <th key={xValue} className="px-2 py-1 text-xs">{xValue}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {yValues.map((yValue) => (
          <tr key={yValue}>
            <th className="px-2 py-1 text-xs">{yValue}</th>
            {xValues.map((xValue) => {
              const key = JSON.stringify({ ...basePosition, [xId]: xValue, [yId]: yValue })
              const observation = cells[key]
              const baseAllow = Boolean(observation?.base?.[observableId])
              const headAllow = Boolean(observation?.head?.[observableId])
              const flipped = observation !== undefined && baseAllow !== headAllow
              return (
                <td
                  key={xValue}
                  role="gridcell"
                  aria-label={`${xValue} ${yValue}`}
                  data-flipped={flipped}
                  className={
                    'h-10 w-10 border text-center text-xs ' +
                    (observation === undefined
                      ? 'bg-gray-100'
                      : flipped
                        ? 'bg-yellow-200'
                        : headAllow
                          ? 'bg-green-200'
                          : 'bg-red-200')
                  }
                >
                  {observation === undefined ? '…' : headAllow ? 'allow' : 'deny'}
                </td>
              )
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
