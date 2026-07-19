import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SourceViewer } from './SourceViewer'

describe('SourceViewer', () => {
  it('highlights the exact empirically attributed line in the selected source version', () => {
    render(
      <SourceViewer
        sourceFile={{
          path: '/repo/head.py',
          source: ['class Limiter:', '    def admit(self):', '        w = self.windows[tenant_id]', '        return True'].join('\n'),
        }}
        responsibleLine={{
          version: 'head',
          file: '/repo/head.py',
          line: 3,
          code: 'w = self.windows[tenant_id]',
        }}
        onClose={vi.fn()}
      />,
    )

    expect(screen.getByLabelText('Source attribution')).toBeTruthy()
    expect(screen.getByTestId('responsible-line').textContent).toContain(
      '3          w = self.windows[tenant_id]',
    )
  })
})
