import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useMicroworldStore } from './store/useMicroworldStore'
import { renderWithQueryClient as render } from './test/renderWithQueryClient'

vi.mock('./components/KnobPanel', () => ({
  KnobPanel: () => <div data-testid="knob-panel">controls</div>,
}))

import App from './App'

class InertSocket {
  static readonly OPEN = 1
  readyState = InertSocket.OPEN
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null

  constructor(_url: string) {}

  close() {}
  send() {}
}

describe('App hero switcher', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    useMicroworldStore.setState({ position: {}, cache: new Map() })
  })

  it('renders all four hero buttons and re-requests /diffs for the newly selected hero', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ changeId: 'some-change-id' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('WebSocket', InertSocket)

    render(<App />)

    // App also fetches GET /ledger for the Session Ledger sidebar on mount,
    // so diff submissions are identified by URL rather than absolute call
    // index/count.
    const diffSubmissions = () =>
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/diffs')) as [string, RequestInit][]

    await waitFor(() => expect(diffSubmissions()).toHaveLength(1))
    const [firstUrl, firstInit] = diffSubmissions()[0]
    expect(String(firstUrl)).toContain('/diffs')
    const firstBody = JSON.parse(String(firstInit.body)) as { id: string; base_file_path: string }
    expect(firstBody.id).toBe('hero1')

    expect(screen.getByRole('button', { name: /Hero 1/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Hero 2/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Hero 3/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Hero 4/ })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /Hero 3/ }))

    await waitFor(() => expect(diffSubmissions()).toHaveLength(2))
    const [secondUrl, secondInit] = diffSubmissions()[1]
    expect(String(secondUrl)).toContain('/diffs')
    const secondBody = JSON.parse(String(secondInit.body)) as { id: string; base_file_path: string }
    expect(secondBody.id).toBe('hero3')
    expect(secondBody.base_file_path).not.toBe(firstBody.base_file_path)

    expect(screen.getByRole('button', { name: /Hero 3/ }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('button', { name: /Hero 1/ }).getAttribute('aria-pressed')).toBe('false')
  })
})
