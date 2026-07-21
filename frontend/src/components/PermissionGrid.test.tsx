import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { PermissionGrid } from './PermissionGrid'
import type { ControlDescriptor, KnobPosition, ObservationBundle } from '../types'

const controls: ControlDescriptor[] = [
  { id: 'role', label: 'Role', binding: {}, type: 'enum', domain: { values: ['viewer', 'contractor'] }, default: 'viewer', scale: 'linear', unit: null, axisRole: 'x' },
  { id: 'resource', label: 'Resource', binding: {}, type: 'enum', domain: { values: ['doc', 'audit-log'] }, default: 'doc', scale: 'linear', unit: null, axisRole: 'y' },
]

function bundle(base: boolean, head: boolean): ObservationBundle {
  return { base: { allow: base }, head: { allow: head } }
}

describe('PermissionGrid', () => {
  it('requests every axis combination once and renders one cell per pair', async () => {
    const onCellsNeeded = vi.fn(async (positions: readonly KnobPosition[]) => {
      const result: Record<string, ObservationBundle> = {}
      for (const position of positions) {
        // Base correctly denies contractors access to the audit log; head's bug
        // grants it — that combination should be the one flagged as "flipped".
        const isEscalatedCombo = position.role === 'contractor' && position.resource === 'audit-log'
        result[JSON.stringify(position)] = bundle(!isEscalatedCombo, true)
      }
      return result
    })

    render(
      <PermissionGrid
        controls={controls}
        observableId="allow"
        basePosition={{ role: 'viewer', resource: 'doc' }}
        onCellsNeeded={onCellsNeeded}
      />,
    )

    await waitFor(() => expect(onCellsNeeded).toHaveBeenCalledTimes(1))
    expect(onCellsNeeded.mock.calls[0][0]).toHaveLength(4) // 2 roles x 2 resources
    expect(await screen.findAllByRole('gridcell')).toHaveLength(4)
    const flipped = screen.getByRole('gridcell', { name: /contractor.*audit-log/i })
    expect(flipped.getAttribute('data-flipped')).toBe('true')
  })
})
