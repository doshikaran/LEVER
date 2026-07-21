/** Dual-lane path walk for the decision-path genre — no raw JSON dumps. */

import { useEffect, useState } from 'react'
import type { BranchDecision } from '../types'

type PathWalkStageProps = Readonly<{
  label: string
  basePath: readonly BranchDecision[]
  headPath: readonly BranchDecision[]
  divergence: number
  forkTag: string | null
}>

function summarize(path: readonly BranchDecision[]): string {
  if (path.length === 0) return 'No branches hit'
  const passed = path.filter((step) => step.outcome).length
  const failed = path.length - passed
  if (passed > 0 && failed === 0) return `${path.length} check${path.length === 1 ? '' : 's'} · all true`
  if (failed > 0 && passed === 0) return `${path.length} check${path.length === 1 ? '' : 's'} · all false`
  return `${passed} true · ${failed} false`
}

function PathLane({
  title,
  path,
  diverge,
  walkIndex,
  forkTag,
}: Readonly<{
  title: string
  path: readonly BranchDecision[]
  diverge: boolean
  walkIndex: number
  forkTag: string | null
}>) {
  return (
    <div
      className={`flex flex-col rounded-xl border p-4 ${
        diverge
          ? 'border-[var(--lever-warning)]/50 bg-orange-50/40'
          : 'border-slate-200 bg-slate-50/70'
      }`}
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</p>
      <p className="mt-1 font-display text-lg font-bold text-[var(--lever-text)]">{summarize(path)}</p>
      <ol className="mt-3 flex flex-1 flex-col gap-2" aria-label={`${title} path steps`}>
        {path.length === 0 ? (
          <li className="rounded-lg border border-dashed border-slate-200 px-3 py-2 text-xs text-[var(--lever-muted)]">
            Idle — no predicates executed
          </li>
        ) : (
          path.map((step, index) => {
            const lit = index <= walkIndex
            const fork = forkTag !== null && step.tag === forkTag
            return (
              <li
                key={`${step.tag}-${index}`}
                data-testid="path-step"
                className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-all duration-300 ${
                  lit ? 'translate-x-0 opacity-100' : 'translate-x-1 opacity-35'
                } ${
                  fork
                    ? 'border-[var(--lever-warning)] bg-orange-100/80 ring-2 ring-[var(--lever-warning)]/30'
                    : step.outcome
                      ? 'border-emerald-200 bg-emerald-50'
                      : 'border-rose-200 bg-rose-50'
                }`}
              >
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                    step.outcome ? 'bg-emerald-500 text-white' : 'bg-rose-500 text-white'
                  }`}
                >
                  {step.outcome ? 'T' : 'F'}
                </span>
                <span className="min-w-0 flex-1 font-mono text-xs text-[var(--lever-text)]">
                  {step.tag}
                </span>
                {fork ? (
                  <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide text-[var(--lever-warning)]">
                    fork
                  </span>
                ) : null}
              </li>
            )
          })
        )}
      </ol>
    </div>
  )
}

/**
 * Game-style dual walk of measured branch decisions for one shared input.
 * Paths come only from cached executions — never invented control flow.
 */
export function PathWalkStage({
  label,
  basePath,
  headPath,
  divergence,
  forkTag,
}: PathWalkStageProps) {
  const diverge = divergence > 0
  const maxLen = Math.max(basePath.length, headPath.length, 1)
  const [walkIndex, setWalkIndex] = useState(-1)

  useEffect(() => {
    setWalkIndex(-1)
    let step = 0
    const timer = window.setInterval(() => {
      setWalkIndex(step)
      step += 1
      if (step >= maxLen) window.clearInterval(timer)
    }, 220)
    return () => window.clearInterval(timer)
  }, [basePath, headPath, maxLen])

  return (
    <section
      data-testid="path-walk-stage"
      aria-label="Decision path walk"
      className="lever-panel flex h-full flex-col gap-4 rounded-2xl p-5"
    >
      <header>
        <p className="font-display text-base font-semibold text-[var(--lever-text)]">Path walk</p>
        <p className="text-xs text-[var(--lever-muted)]">
          Same input · {label} · steps light up as the real code branches
        </p>
      </header>

      <div className="grid flex-1 gap-3 sm:grid-cols-2">
        <PathLane title="Old code" path={basePath} diverge={diverge} walkIndex={walkIndex} forkTag={forkTag} />
        <PathLane title="New code" path={headPath} diverge={diverge} walkIndex={walkIndex} forkTag={forkTag} />
      </div>

      <div
        data-testid="path-verdict"
        className={`rounded-xl px-4 py-3 text-sm font-semibold ${
          diverge ? 'bg-orange-50 text-[var(--lever-warning)]' : 'bg-emerald-50 text-emerald-700'
        }`}
        aria-live="polite"
      >
        {diverge
          ? forkTag
            ? `Paths fork at ${forkTag} — old and new take different branches.`
            : 'Paths diverge on this input — different branch outcomes measured.'
          : 'Both versions walk the same decision path here.'}
      </div>
    </section>
  )
}
