import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SessionLedger } from './SessionLedger'

describe('SessionLedger', () => {
  it('renders one entry per ledger item and calls onOpen with its changeId', () => {
    const onOpen = vi.fn()
    render(
      <SessionLedger
        entries={[{ changeId: 'abc123', thesis: 'Old: fixed window. New: sliding window.' }]}
        onOpen={onOpen}
      />,
    )
    fireEvent.click(screen.getByText(/fixed window/i))
    expect(onOpen).toHaveBeenCalledWith('abc123')
  })

  it('renders a placeholder message when no microworlds have been generated yet', () => {
    render(<SessionLedger entries={[]} onOpen={vi.fn()} />)
    expect(screen.getByText(/no microworlds generated yet/i)).toBeTruthy()
  })
})
