import type { KnobPosition, WidgetConfig } from '../types'

type UnionTreeProps = Readonly<{
  tree: NonNullable<WidgetConfig['unionTree']>
  /** A forward lookup: select an already-evaluated position, never solve for one. */
  onSelectPosition?: (position: KnobPosition) => void
}>

function outcomes(values: readonly boolean[]) {
  if (values.length === 0) return 'unreached'
  return values.map((value) => (value ? 'true' : 'false')).join(' / ')
}

/**
 * The decision-tree pack's sole view: one empirical union of source-tagged
 * predicates, never a pair of independently aligned static control-flow trees.
 */
export function UnionTree({ tree, onSelectPosition }: UnionTreeProps) {
  return (
    <section
      aria-label="Empirical union tree"
      className="rounded-lg border border-[var(--lever-text)]/20 bg-[var(--lever-surface)] p-4 shadow-sm"
    >
      <header className="mb-3 space-y-1">
        <h2 className="text-base font-semibold text-[var(--lever-text)]">{tree.label}</h2>
        <p className="text-sm text-[var(--lever-text)]">
          One shared input; paths reconstructed only from cached executions.
        </p>
      </header>
      <ol className="space-y-2" aria-label="Observed predicate nodes">
        {tree.nodes.map((node) => {
          const fork = node.tag === tree.forkTag
          const unreached = !node.baseTouched || !node.headTouched
          return (
            <li
              key={node.tag}
              data-testid={`union-tree-node-${node.tag}`}
              data-fork={fork ? 'true' : 'false'}
              data-unreached={unreached ? 'true' : 'false'}
              onClick={() => node.positions[0] && onSelectPosition?.(node.positions[0])}
              className={`rounded-md border p-3 text-sm ${
                fork
                  ? 'border-[var(--lever-warning)] ring-2 ring-[var(--lever-warning)]/40'
                  : 'border-[var(--lever-text)]/20'
              } ${unreached ? 'opacity-55' : ''}`}
              style={{ cursor: onSelectPosition ? 'pointer' : undefined }}
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
              {fork ? <p className="mt-1 font-medium text-[var(--lever-warning)]">Fork point</p> : null}
              {unreached ? <p className="mt-1 text-[var(--lever-text)]">Unreached by one version</p> : null}
            </li>
          )
        })}
      </ol>
    </section>
  )
}
