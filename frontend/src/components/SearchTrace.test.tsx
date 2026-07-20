import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { SearchTrace } from './SearchTrace'

describe('SearchTrace', () => {
  it('renders streamed Sobol and ascent probes, then selects the exact cached point', () => {
    const onSelectPosition = vi.fn()
    render(
      <SearchTrace
        controls={[]}
        points={[
          {
            position: { rps: 1, tenants: 1 },
            divergence: 0.05,
            phase: 'explore',
          },
          {
            position: { rps: 81, tenants: 20 },
            divergence: 0.95,
            phase: 'exploit',
          },
        ]}
        onSelectPosition={onSelectPosition}
      />,
    )

    expect(screen.getByRole('region', { name: 'Live adversary search trace' })).toBeTruthy()
    expect(screen.getByText('2 sampled positions · 1 Sobol · 1 ascent')).toBeTruthy()

    fireEvent.click(screen.getAllByTestId('search-trace-point')[1])

    expect(onSelectPosition).toHaveBeenCalledWith({ rps: 81, tenants: 20 })
  })
})
