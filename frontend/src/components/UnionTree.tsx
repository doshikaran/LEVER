import { useEffect, useState } from 'react'
import type { WidgetConfig } from '../types'

type UnionTreeProps = Readonly<{
  tree: NonNullable<WidgetConfig['unionTree']>
}>

function outcomes(values: readonly boolean[]) {
  if (values.length === 0) return 'unreached'
  return values.map((value) => (value ? 'true' : 'false')).join(' / ')
}

/**
 * The decision-tree pack's sole view: one empirical union of source-tagged
 * predicates, never a pair of independently aligned static control-flow trees.
 */
export function UnionTree({ tree }: UnionTreeProps) {
  const [walkIndex, setWalkIndex] = useState(-1)

  useEffect(() => {
    setWalkIndex(-1)
    if (tree.nodes.length === 0) return
    let step = 0
    const timer = window.setInterval(() => {
      setWalkIndex(step)
      step += 1
      if (step >= tree.nodes.length) {
        window.clearInterval(timer)
      }
    }, 180)
    return () => window.clearInterval(timer)
  }, [tree.forkTag, tree.nodes])

  return (
    <section
      aria-label="Empirical union tree"
      data-testid="union-tree"
      className="rounded-lg border border-[var(--lever-text)]/20 bg-[var(--lever-surface)] p-4 shadow-sm"
    >
      <header className="mb-3 space-y-1">
        <h2 className="text-base font-semibold text-[var(--lever-text)]">{tree.label}</h2>
        <p className="text-sm text-[var(--lever-text)]">
          One shared input; paths reconstructed only from cached executions.
        </p>
      </header>
      <ol className="space-y-2" aria-label="Observed predicate nodes">
        {tree.nodes.map((node, index) => {
          const fork = node.tag === tree.forkTag
          const unreached = !node.baseTouched || !node.headTouched
          const walking = index <= walkIndex
          return (
            <li
              key={node.tag}
              data-fork={fork ? 'true' : 'false'}
              data-unreached={unreached ? 'true' : 'false'}
              data-walk={walking ? 'true' : 'false'}
              className={`rounded-md border p-3 text-sm transition-all duration-300 ${
                fork
                  ? 'border-[var(--lever-warning)] ring-2 ring-[var(--lever-warning)]/40'
                  : 'border-[var(--lever-text)]/20'
              } ${unreached ? 'opacity-55' : ''} ${
                walking ? 'translate-x-0 opacity-100' : 'translate-x-2 opacity-40'
              }`}
            >
              <p className="font-medium text-[var(--lever-text)]">Predicate {node.tag}</p>
              <dl className="mt-1 grid gap-1 text-[var(--lever-text)] sm:grid-cols-2">
                <div>
                  <dt className="inline font-medium">Base path: </dt>
                  <dd className="inline">{outcomes(node.baseOutcomes)}</dd>
                </div>
                <div>
                  <dt className="inline font-medium">Head path: </dt>
                  <dd className="inline">{outcomes(node.headOutcomes)}</dd>
                </div>
              </dl>
              {fork ? (
                <p className="mt-1 font-medium text-[var(--lever-warning)]" data-testid="fork-ring">
                  Fork point
                </p>
              ) : null}
              {unreached ? <p className="mt-1 text-[var(--lever-text)]">Unreached by one version</p> : null}
            </li>
          )
        })}
      </ol>
    </section>
  )
}
