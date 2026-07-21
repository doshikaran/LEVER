import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useMicroworldStore } from './store/useMicroworldStore'
import type { DegradationEvent } from './types'

vi.mock('./components/HonestChart', () => ({
  HonestChart: () => <div data-testid="honest-chart">chart primitive</div>,
}))
vi.mock('./components/KnobPanel', () => ({
  KnobPanel: () => <div data-testid="knob-panel">widget controls</div>,
}))

import App from './App'

const divergenceReport = [
  {
    position: { rps: 7 },
    version: 'head',
    observable: 'admitted',
    harness: 1,
    reference: 7,
  },
] as const

const terminals = [
  {
    fixture: '1-unscopable',
    type: 'unscopable',
    degradeReason: 'The change is inside a Django view requiring a live request object.',
    divergenceReport: [],
  },
  {
    fixture: '2-unharnessable',
    type: 'degraded',
    degradeReason: 'Harness Engineer could not produce an executable pair after 3 attempts: live identity-provider dependency `idp.verify`.',
    divergenceReport: [],
  },
  {
    fixture: '3-agreement-below-0.85',
    type: 'degraded',
    degradeReason: 'Fidelity agreement stayed below 0.85 after all three Harness Engineer attempts.',
    divergenceReport,
  },
  {
    fixture: '4-confidence-below-0.60',
    type: 'degraded',
    degradeReason: 'I can build a model, but it depends too heavily on values I had to guess.',
    divergenceReport,
  },
  {
    fixture: '5-no-executable-reference',
    type: 'degraded',
    degradeReason: 'No executable reference path or test suite was found; Lever cannot independently compare harness output to real behavior.',
    divergenceReport: [],
  },
  {
    fixture: '6-raw-diff-no-repo-context',
    type: 'degraded',
    degradeReason: 'No repository context — cannot verify a raw diff against an executable reference path.',
    divergenceReport: [],
  },
] as const

let activeTerminal: DegradationEvent = {
  type: 'degraded',
  changeId: 'degrade-fixture',
  degradeReason: terminals[0].degradeReason,
  plainExplanation: 'The scoped behavior needs manual testing at the request boundary.',
  divergenceReport: [],
  positionCache: {},
}

class DegradationSocket {
  static readonly OPEN = 1
  readyState = DegradationSocket.OPEN
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null

  constructor(_url: string) {
    queueMicrotask(() => this.onmessage?.({ data: JSON.stringify(activeTerminal) } as MessageEvent<string>))
  }

  close() {}
  send() {}
}

describe('App degradation routing', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    useMicroworldStore.setState({ position: {}, cache: new Map() })
    window.history.replaceState({}, '', '/')
  })

  it.each(terminals)('$fixture: chartCount=0, controlCount=0', async (terminal) => {
    activeTerminal = { ...activeTerminal, ...terminal }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/demos') && !url.includes('/run')) {
        return {
          ok: true,
          json: async () => [{ id: 'hero1', label: 'Hero 1 · Rate limiter', description: 'demo' }],
        }
      }
      if (url.endsWith('/sessions')) {
        return { ok: true, json: async () => [] }
      }
      return {
        ok: true,
        json: async () => ({ changeId: activeTerminal.changeId }),
      }
    }))
    vi.stubGlobal('WebSocket', DegradationSocket)

    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Hero 1 · Rate limiter' }))

    await waitFor(() => expect(screen.getByTestId('degradation-panel')).toBeTruthy())
    expect(screen.getByText(activeTerminal.degradeReason)).toBeTruthy()
    const chartCount = document.querySelectorAll('[data-testid="honest-chart"]').length
    const controlCount = document.querySelectorAll('[data-testid="knob-panel"]').length
    expect(chartCount).toBe(0)
    expect(controlCount).toBe(0)
    expect(screen.queryByText('Admitted requests')).toBeNull()
  })
})
