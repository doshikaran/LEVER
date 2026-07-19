import type { ReactNode } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const yAxisDomains = vi.hoisted(() => [] as unknown[])

vi.mock('recharts', () => ({
  CartesianGrid: () => null,
  Legend: () => null,
  Line: () => null,
  LineChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: ({ domain }: { domain: unknown }) => {
    yAxisDomains.push(domain)
    return <div data-testid="y-axis" />
  },
}))

import { HonestChart } from './HonestChart'

describe('HonestChart zoom guardrail', () => {
  beforeEach(() => {
    yAxisDomains.length = 0
  })

  it('keeps the Y-axis lower domain bound at zero after explicit zoom', () => {
    render(
      <HonestChart
        data={[
          { x: 0, base: 100, head: 150 },
          { x: 1, base: 120, head: 180 },
        ]}
        divergence={0.5}
      />,
    )

    expect(yAxisDomains.at(-1)).toEqual([0, 'auto'])

    fireEvent.click(screen.getByRole('button', { name: 'Zoom to the difference' }))

    const zoomedDomain = yAxisDomains.at(-1)
    expect(Array.isArray(zoomedDomain)).toBe(true)
    if (!Array.isArray(zoomedDomain)) {
      throw new Error('YAxis did not receive a domain array after zoom.')
    }
    expect(zoomedDomain[0]).toBe(0)
    expect(zoomedDomain[1]).toBe(189)
  })
})
