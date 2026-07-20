import { useEffect, useMemo, useState } from 'react'
import type { ControlDescriptor, SearchObjective, UnsafePredicate } from '../types'

type Props = Readonly<{
  controls: readonly ControlDescriptor[]
  observableId: string
  disabled?: boolean
  onRun: (objective: SearchObjective, predicate?: UnsafePredicate) => void
}>

/**
 * Keeps the user-visible objective choice explicit.  Reaching an unsafe state
 * needs a predicate; ordinary output divergence does not.
 */
export function ObjectiveSelector({ controls, observableId, disabled = false, onRun }: Props) {
  const [objective, setObjective] = useState<SearchObjective>('max_divergence')
  const [operator, setOperator] = useState<UnsafePredicate['operator']>('gt')
  const thresholdControl = useMemo(
    () => controls.find((control) => control.id === 'limit_per_sec')
      ?? controls.find((control) => control.type === 'integer' || control.type === 'scalar')
      ?? null,
    [controls],
  )
  const [targetMode, setTargetMode] = useState<'knob' | 'literal'>(thresholdControl ? 'knob' : 'literal')
  const [targetKnob, setTargetKnob] = useState(thresholdControl?.id ?? '')
  const [literal, setLiteral] = useState('true')

  useEffect(() => {
    if (thresholdControl !== null) {
      setTargetKnob(thresholdControl.id)
      setTargetMode('knob')
    }
  }, [thresholdControl])

  const run = () => {
    if (objective !== 'reach_unsafe_state') {
      onRun(objective)
      return
    }
    const numericLiteral = Number(literal)
    const literalValue = literal === 'true'
      ? true
      : literal === 'false'
        ? false
        : literal === 'null'
          ? null
          : Number.isFinite(numericLiteral)
            ? numericLiteral
            : literal
    const predicate: UnsafePredicate = {
      observableId,
      operator,
      target: targetMode === 'knob'
        ? { kind: 'knob', id: targetKnob }
        : { kind: 'literal', value: literalValue },
      versions: 'either',
    }
    onRun(objective, predicate)
  }

  return (
    <section aria-label="Search objective" className="rounded-md border border-[var(--lever-primary)] bg-[var(--lever-surface)] p-3 text-sm">
      <label className="flex flex-col gap-1 font-medium">
        Search objective
        <select
          aria-label="Search objective"
          value={objective}
          disabled={disabled}
          onChange={(event) => setObjective(event.target.value as SearchObjective)}
          className="rounded border border-[var(--lever-primary)] bg-[var(--lever-background)] px-2 py-1"
        >
          <option value="max_divergence">Maximize divergence</option>
          <option value="reach_unsafe_state">Reach unsafe state</option>
        </select>
      </label>
      {objective === 'reach_unsafe_state' ? (
        <div className="mt-3 grid gap-2">
          <p className="text-xs">Searches malformed and boundary inputs for a condition in either version.</p>
          <label className="flex flex-col gap-1">Condition
            <select value={operator} onChange={(event) => setOperator(event.target.value as UnsafePredicate['operator'])} className="rounded border border-[var(--lever-primary)] bg-[var(--lever-background)] px-2 py-1">
              <option value="gt">is greater than</option>
              <option value="gte">is at least</option>
              <option value="eq">equals</option>
              <option value="neq">does not equal</option>
              <option value="lt">is less than</option>
              <option value="lte">is at most</option>
            </select>
          </label>
          <label className="flex items-center gap-2"><input type="radio" checked={targetMode === 'knob'} disabled={thresholdControl === null} onChange={() => setTargetMode('knob')} /> control value</label>
          {targetMode === 'knob' ? (
            <select aria-label="Unsafe threshold control" value={targetKnob} onChange={(event) => setTargetKnob(event.target.value)} className="rounded border border-[var(--lever-primary)] bg-[var(--lever-background)] px-2 py-1">
              {controls.filter((control) => control.type === 'integer' || control.type === 'scalar').map((control) => <option key={control.id} value={control.id}>{control.label}</option>)}
            </select>
          ) : null}
          <label className="flex items-center gap-2"><input type="radio" checked={targetMode === 'literal'} onChange={() => setTargetMode('literal')} /> literal value</label>
          {targetMode === 'literal' ? <input aria-label="Unsafe literal value" value={literal} onChange={(event) => setLiteral(event.target.value)} className="rounded border border-[var(--lever-primary)] bg-[var(--lever-background)] px-2 py-1" /> : null}
        </div>
      ) : null}
      <button type="button" onClick={run} disabled={disabled || (objective === 'reach_unsafe_state' && targetMode === 'knob' && targetKnob === '')} className="mt-3 rounded bg-[var(--lever-primary)] px-3 py-2 font-medium text-[var(--lever-surface)] disabled:opacity-50">
        {objective === 'reach_unsafe_state' ? 'Run security search' : 'Run divergence search'}
      </button>
    </section>
  )
}
