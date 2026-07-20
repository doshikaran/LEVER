import { HonestChart } from './HonestChart'
import type { HonestChartDatum } from './HonestChart'
import type { WidgetConfig } from '../types'

type CanvasProps = Readonly<{
  widget: WidgetConfig
  title: string
  divergence: number
  data: readonly HonestChartDatum[]
  onPointClick?: () => void
}>

function VerifiedMicroworld({ widget, title, divergence, data, onPointClick }: CanvasProps) {
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
