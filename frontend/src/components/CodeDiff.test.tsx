import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CodeDiff } from './CodeDiff'
import type { SourceFile } from '../types'

const base: SourceFile = {
  path: 'svc/limiter.py',
  source: 'def limit(n):\n    total = 0\n    for i in range(n):\n        total += 1\n    return total\n',
}

const head: SourceFile = {
  path: 'svc/limiter.py',
  source: 'def limit(n):\n    total = 0\n    for i in range(n):\n        total += 2\n    return total\n',
}

describe('CodeDiff', () => {
  afterEach(() => cleanup())

  it('dims rows that did not execute and highlights executed ones (time-travel)', () => {
    render(
      <CodeDiff
        base={base}
        head={head}
        baseExecutedLines={new Set([1])}
        headExecutedLines={new Set([1])}
      />,
    )
    const executed = screen.getAllByTestId('diff-line').filter((el) => el.getAttribute('data-executed') === 'true')
    const dimmed = screen.getAllByTestId('diff-line').filter((el) => el.getAttribute('data-executed') === 'false')
    expect(executed.length).toBeGreaterThan(0)
    expect(dimmed.length).toBeGreaterThan(0)
  })

  it('emits the version and line number when a row is clicked (diff-as-controller)', () => {
    const onLineClick = vi.fn()
    render(<CodeDiff base={base} head={head} onLineClick={onLineClick} />)
    const rows = screen.getAllByTestId('diff-line')
    fireEvent.click(rows[0])
    expect(onLineClick).toHaveBeenCalledTimes(1)
    const [version, line] = onLineClick.mock.calls[0]
    expect(['base', 'head']).toContain(version)
    expect(typeof line).toBe('number')
  })
})
