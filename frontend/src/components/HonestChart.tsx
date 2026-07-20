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
type SharedHonestChartProps = Readonly<{
  data: readonly HonestChartDatum[]
  divergence: number
  title?: string
  /** A click always refers to the single, current KnobPosition shown here. */
  onPointClick?: () => void
}>

/** A verified result can carry Lever's standard confidence claim. */
type VerifiedChartProps = Readonly<{
  speculative?: false
  fidelityBand?: 'high' | 'medium' | 'low'
}>

/** A generated candidate can never carry the standard verified confidence claim. */
type ProspectiveChartProps = Readonly<{
  speculative: true
  fidelityBand?: never
  hypothesisCaveat?: string | null
}>

/**
 * The rendering mode is a discriminated union, rather than a color choice.
 * In particular, a speculative chart cannot receive a ``fidelityBand`` and
 * therefore cannot render the standard Verified badge.
 */
export type HonestChartProps = SharedHonestChartProps & (
  | VerifiedChartProps
  | ProspectiveChartProps
)

const ZOOM_DURATION_MS = 3_000

/**
 * The frontend's sole Recharts primitive: comparative, zero-anchored, and
 * explicit about the measured divergence.
 */
function VerifiedFidelityBadge({ band }: Readonly<{ band: NonNullable<VerifiedChartProps['fidelityBand']> }>) {
  return <span data-testid="verified-fidelity-badge" className="rounded-full bg-emerald-700 px-2 py-1 text-xs font-semibold text-white">Verified · {band}</span>
}

function ProspectiveBadge() {
  return <span data-testid="prospective-badge" className="rounded-full bg-blue-700 px-2 py-1 text-xs font-semibold text-white">Prospective</span>
}

export function HonestChart(props: HonestChartProps) {
  const {
    data,
    divergence,
    title = 'Behavior comparison',
    onPointClick,
  } = props
  const prospective = props.speculative === true
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
    <section aria-label={title} className="rounded-lg border border-[var(--lever-text)]/20 bg-[var(--lever-surface)] p-4 shadow-sm">
      <header className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-[var(--lever-text)]">{title}</h2>
          {prospective ? (
            <>
              <p className="text-sm text-[var(--lever-text)]">Unwritten code — verified against this generated candidate only.</p>
              {props.hypothesisCaveat ? (
                <p role="note" data-testid="hypothesis-caveat" className="mt-1 text-sm text-[var(--lever-warning)]">{props.hypothesisCaveat}</p>
              ) : null}
            </>
          ) : null}
        </div>
        <div className="flex items-end gap-3">
          <p className="text-sm text-[var(--lever-text)]" aria-live="polite">
            <span className="font-medium">Divergence: </span>
            <output>{divergence.toFixed(3)}</output>
          </p>
          {prospective ? <ProspectiveBadge /> : props.fidelityBand ? <VerifiedFidelityBadge band={props.fidelityBand} /> : null}
        </div>
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
            <Line
              type="monotone"
              dataKey="base"
              name="Base"
              stroke="var(--lever-secondary)"
              strokeDasharray="6 4"
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="head"
              name={prospective ? 'Candidate' : 'Head'}
              stroke={prospective ? '#2563eb' : 'var(--lever-primary)'}
              strokeDasharray={prospective ? '1 4' : undefined}
              strokeLinecap={prospective ? 'round' : undefined}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <button
        type="button"
        onClick={zoomToDifference}
        className="mt-3 rounded-md border border-[var(--lever-text)]/30 px-3 py-2 text-sm font-medium text-[var(--lever-text)] hover:bg-[var(--lever-background)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--lever-primary)]"
      >
        Zoom to the difference
      </button>
    </section>
  )
}
