import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useMicroworldStore } from './store/useMicroworldStore'
import { renderWithQueryClient as render } from './test/renderWithQueryClient'
import type { CompleteEvent } from './types'

const chartClicks = vi.hoisted(() => vi.fn())

vi.mock('./components/HonestChart', () => ({
  HonestChart: ({ onPointClick }: { onPointClick?: () => void }) => (
    <button type="button" data-testid="chart-canvas" onClick={() => {
      chartClicks()
      onPointClick?.()
    }}>Chart canvas</button>
  ),
}))
vi.mock('./components/KnobPanel', () => ({
  KnobPanel: () => <div data-testid="knob-panel">controls</div>,
}))

import App from './App'

const positionKey = 'd7daba113d562e69cfea8947090e4f86746b2466833f63b99d6334b9fe3be499'

const complete: CompleteEvent = {
  type: 'complete',
  changeId: 'trace-test',
  widgetConfig: {
    domainPack: 'rate-limiter',
    thesis: 'Measured difference.',
    controls: [{
      id: 'rps', label: 'Requests', binding: { kind: 'driver', param: 'rps' },
      type: 'integer', domain: { min: 1, max: 100, step: 1 }, default: 3,
      scale: 'linear', unit: 'requests/s', axisRole: null,
    }],
    charts: [{ observableId: 'admitted', label: 'Admitted', render: 'timeseries', compareMode: 'overlay', unit: 'requests', yAxisZeroAnchored: true }],
    initialPosition: { rps: 3 },
    surpriseMarker: null,
    presets: [],
    fidelityBand: 'high',
    fidelityConfidence: 0.9,
    speculative: false,
    hypothesisCaveat: null,
  },
  positionCache: {
    [positionKey]: {
      base: { admitted: 50 },
      head: { admitted: 1010 },
      trace: {
        base: { file: '/repo/base.py', executedLines: [11, 14], entryLines: [11, 14] },
        head: { file: '/repo/head.py', executedLines: [16, 17], entryLines: [16, 17] },
        responsibleLine: {
          version: 'head', file: '/repo/head.py', line: 3, code: 'w = self.windows[tenant_id]',
        },
      },
    },
  },
  sourceFiles: {
    base: { path: '/repo/base.py', source: 'def admit():\n    return True\n' },
    head: { path: '/repo/head.py', source: 'class Limiter:\n    def admit(self):\n        w = self.windows[tenant_id]\n        return True\n' },
  },
}

class TraceSocket {
  static readonly OPEN = 1
  readyState = TraceSocket.OPEN
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null

  constructor(_url: string) {
    queueMicrotask(() => this.onmessage?.({ data: JSON.stringify(complete) } as MessageEvent<string>))
  }

  close() {}
  send() {}
}

describe('App escape hatch', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    useMicroworldStore.setState({ position: {}, cache: new Map() })
    chartClicks.mockReset()
  })

  it('uses the current cached position trace to open and highlight the real head source line', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ changeId: complete.changeId }),
    }))
    vi.stubGlobal('WebSocket', TraceSocket)

    render(<App />)

    await waitFor(() => expect(screen.getByText('Cache hit — no network call')).toBeTruthy())
    fireEvent.click(screen.getByTestId('chart-canvas'))
    expect(chartClicks).toHaveBeenCalledOnce()

    expect(await screen.findByLabelText('Source attribution')).toBeTruthy()
    expect(screen.getByTestId('responsible-line').textContent).toContain('w = self.windows[tenant_id]')
    expect(screen.getByText('/repo/head.py')).toBeTruthy()
  })

  it('pins the exact already-cached position instead of sending observations from the browser', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ changeId: complete.changeId }),
      })
      // App also fetches GET /ledger for the Session Ledger sidebar on mount.
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ entries: [] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ testPath: '/repo/pinned_tests/test_lever_trace.py' }),
      })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('WebSocket', TraceSocket)

    render(<App />)

    await waitFor(() => expect(screen.getByText('Cache hit — no network call')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: 'Pin this' }))

    expect(await screen.findByText('Pinned regression test: /repo/pinned_tests/test_lever_trace.py')).toBeTruthy()
    const pinCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/pin'))
    expect(pinCall?.[0]).toContain('/diffs/trace-test/pin')
    expect(JSON.parse(String(pinCall?.[1]?.body))).toEqual({ position: { rps: 3 } })
  })
})
