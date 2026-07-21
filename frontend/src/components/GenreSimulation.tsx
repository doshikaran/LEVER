/** Genre-aware primary simulation — arena, matrix, path walk, workflow, or numeric bars. */

import { ArenaStage } from './ArenaStage'
import { PathWalkStage } from './PathWalkStage'
import { PermissionMatrix } from './PermissionMatrix'
import { SimulationPlayer } from './SimulationPlayer'
import { WorkflowStage } from './WorkflowStage'
import type {
  BranchDecision,
  ControlDescriptor,
  KnobPosition,
  ObservationBundle,
  WidgetConfig,
} from '../types'

export type SimValues = Readonly<{
  base: number
  head: number
  divergence: number
  baseLabel: string
  headLabel: string
}>

type GenreSimulationProps = Readonly<{
  widget: WidgetConfig
  observations: ObservationBundle | null
  simValues: SimValues
  observableLabel: string
  unit: string | null
  position: KnobPosition
  controls: readonly ControlDescriptor[]
  caption: string | null
  measuredCount: number
  isPlaying: boolean
  canPlay: boolean
  onPlayToggle: () => void
}>

function asBranchPath(value: unknown): BranchDecision[] {
  if (!Array.isArray(value)) return []
  const out: BranchDecision[] = []
  for (const entry of value) {
    if (
      entry !== null
      && typeof entry === 'object'
      && typeof (entry as { tag?: unknown }).tag === 'string'
      && typeof (entry as { outcome?: unknown }).outcome === 'boolean'
    ) {
      out.push({
        tag: (entry as { tag: string }).tag,
        outcome: (entry as { outcome: boolean }).outcome,
      })
    }
  }
  return out
}

/**
 * Pick the stage that matches the microworld genre so every hero gets a
 * playable surface in the primary viewport — not buried behind "detailed".
 */
export function GenreSimulation({
  widget,
  observations,
  simValues,
  observableLabel,
  unit,
  position,
  controls,
  caption,
  measuredCount,
  isPlaying,
  canPlay,
  onPlayToggle,
}: GenreSimulationProps) {
  const genre = widget.worldSpec?.genre

  if (genre === 'decision-path') {
    const observableId = widget.unionTree?.observableId ?? 'path'
    const basePath = asBranchPath(observations?.base[observableId])
    const headPath = asBranchPath(observations?.head[observableId])
    return (
      <PathWalkStage
        label={widget.unionTree?.label ?? observableLabel}
        basePath={basePath}
        headPath={headPath}
        divergence={simValues.divergence}
        forkTag={widget.unionTree?.forkTag ?? null}
      />
    )
  }

  if (genre === 'throughput' || genre === 'retry-storm') {
    return (
      <div className="flex h-full flex-col gap-3" data-testid="genre-arena">
        <ArenaStage
          widget={widget}
          counts={{
            base: Number.isFinite(simValues.base) ? simValues.base : 0,
            head: Number.isFinite(simValues.head) ? simValues.head : 0,
            divergence: simValues.divergence,
          }}
          unit={unit}
        />
        <p className="text-xs text-[var(--lever-muted)]" aria-live="polite">
          {caption
            ?? (simValues.divergence > 0
              ? 'The gates diverge on this input — measured admit counts differ.'
              : 'Both gates admit the same measured count here.')}
        </p>
      </div>
    )
  }

  if (genre === 'access-matrix') {
    return (
      <div className="flex h-full flex-col gap-3" data-testid="genre-matrix">
        <PermissionMatrix
          widget={widget}
          baseValue={Number.isFinite(simValues.base) ? simValues.base : 0}
          headValue={Number.isFinite(simValues.head) ? simValues.head : 0}
          divergence={simValues.divergence}
        />
        <p className="text-xs text-[var(--lever-muted)]" aria-live="polite">
          {caption
            ?? (simValues.divergence > 0
              ? `Cell split: old ${simValues.baseLabel} · new ${simValues.headLabel}.`
              : `Both versions ${simValues.baseLabel} this cell.`)}
        </p>
      </div>
    )
  }

  if (genre === 'state-workflow') {
    return (
      <WorkflowStage
        widget={widget}
        baseState={simValues.baseLabel}
        headState={simValues.headLabel}
        divergence={simValues.divergence}
      />
    )
  }

  return (
    <SimulationPlayer
      observableLabel={observableLabel}
      unit={unit}
      baseValue={simValues.base}
      headValue={simValues.head}
      baseLabel={simValues.baseLabel}
      headLabel={simValues.headLabel}
      divergence={simValues.divergence}
      position={position}
      controls={controls}
      caption={caption}
      measuredCount={measuredCount}
      isPlaying={isPlaying}
      canPlay={canPlay}
      onPlayToggle={onPlayToggle}
      hidePlay
    />
  )
}
