import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { NodeGraph } from './NodeGraph'

afterEach(() => cleanup())

describe('NodeGraph', () => {
  it('highlights the current state and dims unreached states', () => {
    render(
      <NodeGraph
        states={['red', 'green', 'yellow']}
        baseCurrentState="green"
        headCurrentState="yellow"
      />,
    )
    const base = screen.getByTestId('node-base-green')
    const head = screen.getByTestId('node-head-yellow')
    expect(base.getAttribute('data-active')).toBe('true')
    expect(head.getAttribute('data-active')).toBe('true')
    expect(screen.getByTestId('node-base-red').getAttribute('data-active')).toBe('false')
  })

  it('highlights only the current state per version, not the previous one', () => {
    render(
      <NodeGraph
        states={['red', 'green', 'yellow']}
        baseCurrentState="green"
        headCurrentState="green"
      />,
    )
    // Both versions start at green; head's *current* state must be green, not
    // some earlier/initial state, and base must not falsely light up yellow.
    expect(screen.getByTestId('node-base-green').getAttribute('data-active')).toBe('true')
    expect(screen.getByTestId('node-head-green').getAttribute('data-active')).toBe('true')
    expect(screen.getByTestId('node-base-yellow').getAttribute('data-active')).toBe('false')
    expect(screen.getByTestId('node-head-yellow').getAttribute('data-active')).toBe('false')
  })
})
