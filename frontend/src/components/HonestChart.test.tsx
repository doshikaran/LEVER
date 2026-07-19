import type { ReactNode } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const yAxisDomains = vi.hoisted(() => [] as unknown[])
const lineProps = vi.hoisted(() => [] as Array<Record<string, unknown>>)

vi.mock('recharts', () => ({
  CartesianGrid: () => null,
  Legend: () => null,
  Line: (props: Record<string, unknown>) => {
    lineProps.push(props)
    return null
  },
  LineChart: ({ children, onClick }: { children: ReactNode; onClick?: () => void }) => (
    <button type="button" data-testid="chart-canvas" onClick={onClick}>{children}</button>
  ),
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
    lineProps.length = 0
  })

  afterEach(() => cleanup())

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

  it('forwards a canvas click only through the explicit point-attribution callback', () => {
    const onPointClick = vi.fn()
    render(
      <HonestChart
        data={[{ x: 0, base: 1, head: 2 }]}
        divergence={1}
        onPointClick={onPointClick}
      />,
    )

    fireEvent.click(screen.getByTestId('chart-canvas'))

    expect(onPointClick).toHaveBeenCalledOnce()
  })

  it('uses themed colors while retaining solid head and dashed base encodings', () => {
    render(
      <HonestChart
        data={[{ x: 0, base: 1, head: 2 }]}
        divergence={1}
      />,
    )

    const base = lineProps.find((line) => line.dataKey === 'base')
    const head = lineProps.find((line) => line.dataKey === 'head')
    expect(base).toMatchObject({ stroke: 'var(--lever-secondary)', strokeDasharray: '6 4' })
    expect(head).toMatchObject({ stroke: 'var(--lever-primary)' })
    expect(head?.strokeDasharray).toBeUndefined()
  })
})
