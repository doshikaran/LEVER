import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useMicroworldStore } from './store/useMicroworldStore'
import { renderWithQueryClient as render } from './test/renderWithQueryClient'
import type { CompleteEvent, KnobPosition, ObservationBundle } from './types'

vi.mock('./components/KnobPanel', () => ({
  KnobPanel: () => <div data-testid="knob-panel">controls</div>,
}))

// Stand in for the real PermissionGrid so this test can capture the
// `onCellsNeeded` callback App.tsx wires up (evaluateManyPositions) and drive
// it directly, instead of depending on PermissionGrid's own effect timing.
let capturedOnCellsNeeded:
  | ((positions: readonly KnobPosition[]) => Promise<Record<string, ObservationBundle>>)
  | null = null

vi.mock('./components/PermissionGrid', () => ({
  PermissionGrid: (props: {
    onCellsNeeded: (positions: readonly KnobPosition[]) => Promise<Record<string, ObservationBundle>>
  }) => {
    capturedOnCellsNeeded = props.onCellsNeeded
    return <div data-testid="permission-grid-stub" />
  },
}))

import App from './App'

const complete: CompleteEvent = {
  type: 'complete',
  changeId: 'grid-hero-switch-test',
  widgetConfig: {
    domainPack: 'permission-check',
    thesis: 'Measured permission grid.',
    controls: [
      { id: 'role', label: 'Role', binding: {}, type: 'enum', domain: { values: ['viewer', 'contractor'] }, default: 'viewer', scale: 'linear', unit: null, axisRole: 'x' },
      { id: 'resource', label: 'Resource', binding: {}, type: 'enum', domain: { values: ['doc', 'audit-log'] }, default: 'doc', scale: 'linear', unit: null, axisRole: 'y' },
    ],
    charts: [{ observableId: 'allow', label: 'Access', render: 'matrixCell', compareMode: 'overlay', unit: null, yAxisZeroAnchored: true }],
    initialPosition: { role: 'viewer', resource: 'doc' },
    surpriseMarker: null,
    presets: [],
    fidelityBand: 'high',
    fidelityConfidence: 0.9,
    speculative: false,
    hypothesisCaveat: null,
  },
  positionCache: {},
  sourceFiles: {},
}

class HangingGridSocket {
  static readonly OPEN = 1
  static sent: string[] = []
  readyState = HangingGridSocket.OPEN
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null

  constructor(_url: string) {
    queueMicrotask(() => this.onmessage?.({ data: JSON.stringify(complete) } as MessageEvent<string>))
  }

  close() {}
  // Deliberately never replies — simulates a grid cell fetch still in flight
  // when the user switches heroes mid-fetch.
  send(payload: string) {
    HangingGridSocket.sent.push(payload)
  }
}

describe('Grid cleanup on hero switch (regression for permanently-hanging grid fetch)', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    HangingGridSocket.sent = []
    capturedOnCellsNeeded = null
    useMicroworldStore.setState({ position: {}, cache: new Map() })
  })

  it('rejects an outstanding grid request instead of hanging forever when the hero changes before it resolves', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ changeId: complete.changeId }),
    }))
    vi.stubGlobal('WebSocket', HangingGridSocket)

    render(<App />)

    await waitFor(() => expect(capturedOnCellsNeeded).not.toBeNull())

    // Kick off a grid-cell fetch the same way PermissionGrid would, and hold
    // onto the returned promise without awaiting it yet — the fake socket
    // above never answers, so without a fix this would hang forever.
    const pending = capturedOnCellsNeeded!([{ role: 'viewer', resource: 'doc' }])
    const rejection = expect(pending).rejects.toThrow('Hero changed before this position could be evaluated')

    await waitFor(() => expect(HangingGridSocket.sent.length).toBeGreaterThan(0))

    // Switch heroes while that request is still outstanding.
    fireEvent.click(screen.getByRole('button', { name: /Hero 2/ }))

    // The pending grid resolver must be rejected by the cleanup this task
    // added, not left dangling.
    await rejection
  })
})
