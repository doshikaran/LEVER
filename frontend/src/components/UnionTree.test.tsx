import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { UnionTree } from './UnionTree'


describe('UnionTree', () => {
  it('renders one empirical tree with a visible fork and unreached node', () => {
    render(
      <UnionTree
        tree={{
          observableId: 'path',
          label: 'executed pricing path',
          render: 'unionTree',
          forkTag: '31:4',
          nodes: [
            {
              tag: '31:4',
              baseOutcomes: [true],
              headOutcomes: [false],
              positions: [{ cohort: 'beta', flagState: 'canary', cartValue: 200 }],
              baseTouched: true,
              headTouched: true,
            },
            {
              tag: '34:4',
              baseOutcomes: [true],
              headOutcomes: [],
              positions: [{ cohort: 'beta', flagState: 'canary', cartValue: 200 }],
              baseTouched: true,
              headTouched: false,
            },
          ],
        }}
      />,
    )

    expect(screen.getByRole('region', { name: 'Empirical union tree' })).toBeTruthy()
    expect(screen.getByText('Fork point')).toBeTruthy()
    expect(screen.getByText('Unreached by one version')).toBeTruthy()
    expect(screen.getByText('Predicate 31:4').parentElement?.dataset.fork).toBe('true')
  })
})
