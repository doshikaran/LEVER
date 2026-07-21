import { HonestChart } from './HonestChart'
import type { HonestChartDatum } from './HonestChart'
import { NodeGraph } from './NodeGraph'
import { PermissionGrid } from './PermissionGrid'
import type { ControlDescriptor, KnobPosition, ObservationBundle, WidgetConfig } from '../types'

type CanvasProps = Readonly<{
  widget: WidgetConfig
  title: string
  divergence: number
  data: readonly HonestChartDatum[]
  onPointClick?: () => void
  controls?: readonly ControlDescriptor[]
  basePosition?: KnobPosition
  onCellsNeeded?: (positions: readonly KnobPosition[]) => Promise<Record<string, ObservationBundle>>
  currentObservation?: ObservationBundle | null
}>

/**
 * Node names come only from what has actually been observed at the current
 * position — the nodeState observable carries no declared value domain, so
 * this mechanically derives the visible node set from real base/head output
 * rather than inventing or hardcoding a hero-specific state list.
 */
function statesFromObservation(
  currentObservation: ObservationBundle | null | undefined,
  observableId: string,
): string[] {
  if (!currentObservation) return []
  const seen = new Set<string>()
  for (const value of [currentObservation.base[observableId], currentObservation.head[observableId]]) {
    if (typeof value === 'string') seen.add(value)
  }
  return Array.from(seen).sort()
}

function VerifiedMicroworld({ widget, title, divergence, data, onPointClick, controls, basePosition, onCellsNeeded, currentObservation }: CanvasProps) {
  if (widget.charts[0]?.render === 'matrixCell' && controls && basePosition && onCellsNeeded) {
    return (
      <section data-testid="verified-microworld" className="space-y-3">
        <PermissionGrid
          controls={controls}
          observableId={widget.charts[0].observableId}
          basePosition={basePosition}
          onCellsNeeded={onCellsNeeded}
        />
      </section>
    )
  }
  if (widget.charts[0]?.render === 'nodeState' && currentObservation) {
    const observableId = widget.charts[0].observableId
    return (
      <section data-testid="verified-microworld" className="space-y-3">
        <NodeGraph
          states={statesFromObservation(currentObservation, observableId)}
          baseCurrentState={String(currentObservation.base[observableId])}
          headCurrentState={String(currentObservation.head[observableId])}
        />
      </section>
    )
  }
  return (
    <section data-testid="verified-microworld" className="space-y-3">
      <HonestChart title={title} divergence={divergence} data={data} onPointClick={onPointClick} fidelityBand={widget.fidelityBand} />
    </section>
  )
}

/** A separate domain branch that selects HonestChart's prospective union arm. */
function ProspectiveMicroworld({ widget, title, divergence, data, onPointClick }: CanvasProps) {
  return (
    <section data-testid="prospective-microworld" className="rounded-lg border border-blue-700/40 bg-blue-50 p-1">
      <HonestChart title={title} divergence={divergence} data={data} onPointClick={onPointClick} speculative hypothesisCaveat={widget.hypothesisCaveat} />
    </section>
  )
}

/** Discriminated rendering boundary for current code versus generated code. */
export function MicroworldCanvas(props: CanvasProps) {
  return props.widget.speculative
    ? <ProspectiveMicroworld {...props} />
    : <VerifiedMicroworld {...props} />
}

/** One independently-generated prospective candidate's display inputs. */
export type ProspectiveCandidateView = Readonly<{
  key: string
  title: string
  divergence: number
  data: readonly HonestChartDatum[]
  widget: WidgetConfig
}>

/**
 * Render spec §6.2's 3 LLM-generated candidates side by side against the
 * current baseline. Reuses ProspectiveMicroworld once per candidate — the
 * same speculative-only rendering boundary MicroworldCanvas enforces for one
 * candidate applies independently to each of the N candidates here; there is
 * no shared or aggregate state that could let any of them slip through the
 * verified branch.
 */
export function ProspectiveCandidateRow({ candidates }: { candidates: readonly ProspectiveCandidateView[] }) {
  if (candidates.length === 0) return null
  return (
    <div className="flex flex-wrap gap-4" data-testid="prospective-candidate-row">
      {candidates.map((candidate) => (
        <div key={candidate.key} className="min-w-0 flex-1 basis-64">
          <ProspectiveMicroworld
            widget={candidate.widget}
            title={candidate.title}
            divergence={candidate.divergence}
            data={candidate.data}
          />
        </div>
      ))}
    </div>
  )
}
