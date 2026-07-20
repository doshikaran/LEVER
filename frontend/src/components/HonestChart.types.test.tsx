import { describe, expect, it } from 'vitest'
import { HonestChart } from './HonestChart'

const data = [{ x: 0, base: 2, head: 4 }] as const

describe('HonestChart prop contract', () => {
  it('requires a measured divergence at the type level', () => {
    // @ts-expect-error HonestChart must never be instantiated without divergence.
    const chartWithoutDivergence = <HonestChart data={data} />

    expect(chartWithoutDivergence).toBeDefined()
  })

  it('forbids a prospective chart from receiving the verified confidence claim', () => {
    // @ts-expect-error The speculative union arm has no fidelityBand field.
    const speculativeWithVerifiedBadge = <HonestChart data={data} divergence={0.5} speculative fidelityBand="high" />

    expect(speculativeWithVerifiedBadge).toBeDefined()
  })
})
