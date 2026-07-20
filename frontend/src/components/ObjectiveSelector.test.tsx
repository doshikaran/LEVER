import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ObjectiveSelector } from './ObjectiveSelector'

const controls = [{
  id: 'limit_per_sec', label: 'Limit per second', binding: { kind: 'config', path: 'limit_per_sec' },
  type: 'integer' as const, domain: { min: 1, max: 100, step: 1 }, default: 50,
  scale: 'linear' as const, unit: 'requests/s', axisRole: null,
}]

describe('ObjectiveSelector', () => {
  it('defaults to max divergence and exposes a predicate-backed unsafe search', () => {
    const onRun = vi.fn()
    render(<ObjectiveSelector controls={controls} observableId="admitted" onRun={onRun} />)

    const selector = screen.getByRole('combobox', { name: 'Search objective' })
    expect((selector as HTMLSelectElement).value).toBe('max_divergence')
    expect(screen.getByRole('option', { name: 'Reach unsafe state' })).toBeTruthy()

    fireEvent.change(selector, { target: { value: 'reach_unsafe_state' } })
    fireEvent.click(screen.getByRole('button', { name: 'Run security search' }))

    expect(onRun).toHaveBeenCalledWith('reach_unsafe_state', {
      observableId: 'admitted',
      operator: 'gt',
      target: { kind: 'knob', id: 'limit_per_sec' },
      versions: 'either',
    })
  })
})
