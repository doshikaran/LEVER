type NodeGraphProps = Readonly<{
  states: readonly string[]
  baseCurrentState: string
  headCurrentState: string
}>

/** Minimal node-graph rendering for the state-machine pack: two labeled node rings. */
export function NodeGraph({ states, baseCurrentState, headCurrentState }: NodeGraphProps) {
  return (
    <div className="flex gap-6">
      {(['base', 'head'] as const).map((version) => {
        const current = version === 'base' ? baseCurrentState : headCurrentState
        return (
          <div key={version} className="space-y-2">
            <h3 className="text-sm font-medium capitalize">{version}</h3>
            <div className="flex gap-2">
              {states.map((state) => (
                <span
                  key={state}
                  data-testid={`node-${version}-${state}`}
                  data-active={state === current}
                  className={
                    'rounded-full border px-3 py-1 text-xs ' +
                    (state === current ? 'border-[var(--lever-primary)] bg-[var(--lever-primary)] text-[var(--lever-surface)]' : 'opacity-40')
                  }
                >
                  {state}
                </span>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
