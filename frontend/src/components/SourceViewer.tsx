import type { ResponsibleLine, SourceFile } from '../types'

type SourceViewerProps = Readonly<{
  sourceFile: SourceFile
  responsibleLine: ResponsibleLine
  onClose: () => void
}>

/** A compact read-only escape hatch from a measured point back to its source line. */
export function SourceViewer({ sourceFile, responsibleLine, onClose }: SourceViewerProps) {
  const sourceLines = sourceFile.source.split(/\r?\n/)
  const firstLine = Math.max(1, responsibleLine.line - 3)
  const lastLine = Math.min(sourceLines.length, responsibleLine.line + 3)

  return (
    <aside
      aria-label="Source attribution"
      className="rounded-lg border border-blue-200 bg-slate-950 p-4 text-sm text-slate-100"
    >
      <header className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">Executed responsible line</h2>
          <p className="break-all font-mono text-xs text-slate-300">{sourceFile.path}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded border border-slate-500 px-2 py-1 text-xs hover:bg-slate-800"
        >
          Close code
        </button>
      </header>
      <pre className="overflow-x-auto" aria-label="Source excerpt">
        {sourceLines.slice(firstLine - 1, lastLine).map((code, index) => {
          const line = firstLine + index
          const content = `${String(line).padStart(4, ' ')}  ${code}`
          return line === responsibleLine.line ? (
            <mark
              key={line}
              data-testid="responsible-line"
              className="block bg-amber-300 px-1 text-slate-950"
            >
              {content}
            </mark>
          ) : (
            <span key={line} className="block">{content}</span>
          )
        })}
      </pre>
    </aside>
  )
}
