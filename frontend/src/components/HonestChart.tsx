import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

/** A single paired observation at one point on the chart's x-axis. */
export type HonestChartDatum = Readonly<{
  x: string | number
  base: number
  head: number
}>

/**
 * The only public chart contract.  `divergence` is deliberately required so a
 * caller cannot render a comparative chart without showing the measured gap.
 * There is intentionally no y-domain, zoom, or chart-component escape hatch.
 */
export type HonestChartProps = Readonly<{
  data: readonly HonestChartDatum[]
  divergence: number
  title?: string
  /** A click always refers to the single, current KnobPosition shown here. */
  onPointClick?: () => void
}>

const ZOOM_DURATION_MS = 3_000

/**
 * The frontend's sole Recharts primitive: comparative, zero-anchored, and
 * explicit about the measured divergence.
 */
export function HonestChart({
  data,
  divergence,
  title = 'Behavior comparison',
  onPointClick,
}: HonestChartProps) {
  const [isZoomed, setIsZoomed] = useState(false)
  const zoomTimer = useRef<number | undefined>(undefined)

  const zoomUpperBound = useMemo(() => {
    const observedMaximum = Math.max(
      1,
      ...data.flatMap((point) => [point.base, point.head]),
    )
    return Math.ceil(observedMaximum * 1.05)
  }, [data])

  useEffect(
    () => () => {
      if (zoomTimer.current !== undefined) {
        window.clearTimeout(zoomTimer.current)
      }
    },
    [],
  )

  function zoomToDifference() {
    if (zoomTimer.current !== undefined) {
      window.clearTimeout(zoomTimer.current)
    }
    setIsZoomed(true)
    zoomTimer.current = window.setTimeout(() => {
      setIsZoomed(false)
      zoomTimer.current = undefined
    }, ZOOM_DURATION_MS)
  }

  return (
    <section aria-label={title} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <header className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-slate-950">{title}</h2>
        <p className="text-sm text-slate-700" aria-live="polite">
          <span className="font-medium">Divergence: </span>
          <output>{divergence.toFixed(3)}</output>
        </p>
      </header>

      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data}
            margin={{ top: 8, right: 20, bottom: 8, left: 0 }}
            onClick={onPointClick}
          >
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="x" />
            {isZoomed ? (
              <YAxis domain={[0, zoomUpperBound]} />
            ) : (
              <YAxis domain={[0, 'auto']} />
            )}
            <Tooltip />
            <Legend />
            <Line type="monotone" dataKey="base" name="Base" stroke="#64748b" dot={false} />
            <Line type="monotone" dataKey="head" name="Head" stroke="#2563eb" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <button
        type="button"
        onClick={zoomToDifference}
        className="mt-3 rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-900 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
      >
        Zoom to the difference
      </button>
    </section>
  )
}
