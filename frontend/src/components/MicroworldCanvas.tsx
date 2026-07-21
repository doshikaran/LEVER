import { useState } from 'react'
import { ArenaStage } from './ArenaStage'
import { HonestChart } from './HonestChart'
import type { HonestChartDatum } from './HonestChart'
import { PermissionMatrix } from './PermissionMatrix'
import { WorkflowStage } from './WorkflowStage'
import type { WidgetConfig } from '../types'

type CanvasProps = Readonly<{
  widget: WidgetConfig
  title: string
  divergence: number
  data: readonly HonestChartDatum[]
  baseValue: number | string
  headValue: number | string
  onPointClick?: () => void
}>

function EvidenceChart({
  widget,
  title,
  divergence,
  data,
  onPointClick,
}: Omit<CanvasProps, 'baseValue' | 'headValue'>) {
  if (widget.speculative) {
    return (
      <HonestChart
        title={title}
        divergence={divergence}
        data={data}
        onPointClick={onPointClick}
        speculative
        hypothesisCaveat={widget.hypothesisCaveat}
      />
    )
  }
  return (
    <HonestChart
      title={title}
      divergence={divergence}
      data={data}
      onPointClick={onPointClick}
      fidelityBand={widget.fidelityBand}
    />
  )
}

function StageBody({
  widget,
  title,
  divergence,
  data,
  baseValue,
  headValue,
  onPointClick,
  evidenceOnly,
}: CanvasProps & { evidenceOnly: boolean }) {
  if (evidenceOnly) {
    return (
      <EvidenceChart
        widget={widget}
        title={title}
        divergence={divergence}
        data={data}
        onPointClick={onPointClick}
      />
    )
  }
  const genre = widget.worldSpec.genre
  if (genre === 'throughput' || genre === 'retry-storm') {
    return (
      <ArenaStage
        widget={widget}
        counts={{ base: Number(baseValue), head: Number(headValue), divergence }}
        unit={widget.charts[0]?.unit ?? null}
        onSurpriseClick={onPointClick}
      />
    )
  }
  if (genre === 'access-matrix') {
    return (
      <PermissionMatrix
        widget={widget}
        baseValue={Number(baseValue)}
        headValue={Number(headValue)}
        divergence={divergence}
        onCellActivate={onPointClick}
      />
    )
  }
  if (genre === 'state-workflow') {
    return (
      <WorkflowStage
        widget={widget}
        baseState={String(baseValue)}
        headState={String(headValue)}
        divergence={divergence}
      />
    )
  }
  return (
    <EvidenceChart
      widget={widget}
      title={title}
      divergence={divergence}
      data={data}
      onPointClick={onPointClick}
    />
  )
}

function VerifiedMicroworld(props: CanvasProps) {
  const canToggleEvidence = props.widget.worldSpec.affordances.includes('evidence-chart')
    && (props.widget.worldSpec.genre === 'throughput'
      || props.widget.worldSpec.genre === 'retry-storm'
      || props.widget.worldSpec.genre === 'access-matrix')
  const [evidenceOnly, setEvidenceOnly] = useState(false)

  return (
    <section data-testid="verified-microworld" className="space-y-3">
      {canToggleEvidence ? (
        <div className="flex gap-2 text-xs">
          <button
            type="button"
            aria-pressed={!evidenceOnly}
            className={`lever-chip rounded-lg border px-2.5 py-1 font-semibold ${!evidenceOnly ? 'border-transparent bg-[var(--lever-primary)] text-white' : 'border-slate-200 bg-white'}`}
            onClick={() => setEvidenceOnly(false)}
          >
            Stage
          </button>
          <button
            type="button"
            aria-pressed={evidenceOnly}
            data-testid="evidence-view-toggle"
            className={`lever-chip rounded-lg border px-2.5 py-1 font-semibold ${evidenceOnly ? 'border-transparent bg-[var(--lever-primary)] text-white' : 'border-slate-200 bg-white'}`}
            onClick={() => setEvidenceOnly(true)}
          >
            Evidence chart
          </button>
        </div>
      ) : null}
      <StageBody {...props} evidenceOnly={evidenceOnly} />
    </section>
  )
}

function ProspectiveMicroworld(props: CanvasProps) {
  return (
    <section data-testid="prospective-microworld" className="rounded-2xl border border-sky-300/60 bg-sky-50/80 p-1">
      <EvidenceChart {...props} />
    </section>
  )
}

export function MicroworldCanvas(props: CanvasProps) {
  return props.widget.speculative
    ? <ProspectiveMicroworld {...props} />
    : <VerifiedMicroworld {...props} />
}
