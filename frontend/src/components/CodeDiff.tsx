/** Left-side unified old-vs-new source diff with per-frame execution highlight. */

import { useMemo } from 'react'
import type { ResponsibleLine, SourceFile } from '../types'

type CodeDiffProps = Readonly<{
  base?: SourceFile
  head?: SourceFile
  /** Base line numbers the current frame actually executed (Time-travel review). */
  baseExecutedLines?: ReadonlySet<number>
  /** Head line numbers the current frame actually executed (Time-travel review). */
  headExecutedLines?: ReadonlySet<number>
  /** The version-exclusive responsible line for the current frame, if any. */
  responsibleLine?: ResponsibleLine | null
  /** When set, rows become clickable to jump to the first frame that ran them. */
  onLineClick?: (version: 'base' | 'head', line: number) => void
}>

type Row = Readonly<{
  kind: 'same' | 'add' | 'del'
  text: string
  baseNo: number | null
  headNo: number | null
}>

const CONTEXT = 3

/** Classic LCS line diff — small files only (a single changed module pair). */
function diffLines(baseText: string, headText: string): Row[] {
  const a = baseText.replace(/\n$/, '').split('\n')
  const b = headText.replace(/\n$/, '').split('\n')
  const n = a.length
  const m = b.length
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }
  const rows: Row[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      rows.push({ kind: 'same', text: a[i], baseNo: i + 1, headNo: j + 1 })
      i += 1
      j += 1
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      rows.push({ kind: 'del', text: a[i], baseNo: i + 1, headNo: null })
      i += 1
    } else {
      rows.push({ kind: 'add', text: b[j], baseNo: null, headNo: j + 1 })
      j += 1
    }
  }
  while (i < n) {
    rows.push({ kind: 'del', text: a[i], baseNo: i + 1, headNo: null })
    i += 1
  }
  while (j < m) {
    rows.push({ kind: 'add', text: b[j], baseNo: null, headNo: j + 1 })
    j += 1
  }
  return rows
}

/** Collapse long unchanged runs into a single spacer, keeping CONTEXT lines. */
function collapse(rows: Row[]): (Row | { kind: 'gap'; count: number })[] {
  const changed = new Set<number>()
  rows.forEach((row, index) => {
    if (row.kind !== 'same') {
      for (let k = index - CONTEXT; k <= index + CONTEXT; k += 1) changed.add(k)
    }
  })
  const out: (Row | { kind: 'gap'; count: number })[] = []
  let run = 0
  rows.forEach((row, index) => {
    if (changed.has(index)) {
      if (run > 0) {
        out.push({ kind: 'gap', count: run })
        run = 0
      }
      out.push(row)
    } else {
      run += 1
    }
  })
  if (run > 0) out.push({ kind: 'gap', count: run })
  return out
}

export function CodeDiff({
  base,
  head,
  baseExecutedLines,
  headExecutedLines,
  responsibleLine,
  onLineClick,
}: CodeDiffProps) {
  const rows = useMemo(() => {
    if (!base || !head) return []
    return collapse(diffLines(base.source, head.source))
  }, [base, head])

  const added = rows.filter((r) => 'kind' in r && r.kind === 'add').length
  const removed = rows.filter((r) => 'kind' in r && r.kind === 'del').length
  const fileName = (head?.path ?? base?.path ?? '').split('/').pop() ?? 'source'
  const hasTrace = (baseExecutedLines?.size ?? 0) > 0 || (headExecutedLines?.size ?? 0) > 0

  if (!base || !head) {
    return (
      <section className="lever-panel rounded-2xl p-4">
        <p className="text-sm text-[var(--lever-muted)]">Source diff unavailable for this session.</p>
      </section>
    )
  }

  const rowExecuted = (row: Row): boolean => {
    const baseHit = row.baseNo !== null && (baseExecutedLines?.has(row.baseNo) ?? false)
    const headHit = row.headNo !== null && (headExecutedLines?.has(row.headNo) ?? false)
    return baseHit || headHit
  }

  const rowResponsible = (row: Row): boolean => {
    if (!responsibleLine) return false
    if (responsibleLine.version === 'base') return row.baseNo === responsibleLine.line
    return row.headNo === responsibleLine.line
  }

  const rowClick = (row: Row) => {
    if (!onLineClick) return
    if (row.kind === 'del' && row.baseNo !== null) onLineClick('base', row.baseNo)
    else if (row.kind === 'add' && row.headNo !== null) onLineClick('head', row.headNo)
    else if (row.headNo !== null) onLineClick('head', row.headNo)
    else if (row.baseNo !== null) onLineClick('base', row.baseNo)
  }

  return (
    <section
      data-testid="code-diff"
      className="lever-panel flex h-full flex-col overflow-hidden rounded-2xl"
      aria-label="Old versus new code"
    >
      <header className="flex items-center justify-between gap-2 border-b border-slate-200/70 px-4 py-3">
        <div className="min-w-0">
          <p className="font-display text-sm font-semibold text-[var(--lever-text)]">What changed</p>
          <p className="truncate font-mono text-xs text-[var(--lever-muted)]">
            {fileName}
            {onLineClick ? <span className="ml-2 text-[var(--lever-primary)]">· click a line to jump</span> : null}
          </p>
        </div>
        <div className="flex shrink-0 gap-2 text-xs font-semibold">
          <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-emerald-700">+{added}</span>
          <span className="rounded-md bg-rose-50 px-2 py-0.5 text-rose-700">−{removed}</span>
        </div>
      </header>
      <div className="max-h-[26rem] overflow-auto font-mono text-[12px] leading-relaxed">
        {rows.map((row, index) => {
          if (row.kind === 'gap') {
            return (
              <div
                key={`gap-${index}`}
                className="select-none bg-slate-50 px-4 py-1 text-center text-[10px] uppercase tracking-wide text-slate-400"
              >
                {row.count} unchanged line{row.count === 1 ? '' : 's'}
              </div>
            )
          }
          const executed = rowExecuted(row)
          const responsible = rowResponsible(row)
          const tone =
            row.kind === 'add'
              ? 'bg-emerald-50/80 text-emerald-900'
              : row.kind === 'del'
                ? 'bg-rose-50/80 text-rose-900'
                : 'text-slate-600'
          // Time-travel: when trace data exists, dim rows that did not run this frame.
          const traceTone = hasTrace
            ? executed
              ? 'opacity-100'
              : 'opacity-40'
            : 'opacity-100'
          const rail = responsible
            ? 'border-l-[3px] border-[var(--lever-warning)] bg-orange-100/60'
            : executed && hasTrace
              ? 'border-l-[3px] border-[var(--lever-primary)]'
              : 'border-l-[3px] border-transparent'
          return (
            <div
              key={`${row.kind}-${index}`}
              data-testid="diff-line"
              data-executed={executed ? 'true' : 'false'}
              onClick={onLineClick ? () => rowClick(row) : undefined}
              role={onLineClick ? 'button' : undefined}
              tabIndex={onLineClick ? 0 : undefined}
              onKeyDown={
                onLineClick
                  ? (event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        rowClick(row)
                      }
                    }
                  : undefined
              }
              className={`flex transition-all duration-300 ${tone} ${traceTone} ${rail} ${
                onLineClick ? 'cursor-pointer hover:brightness-95' : ''
              }`}
              title={responsible ? 'Version-exclusive responsible line for this frame' : undefined}
            >
              <span className="w-10 shrink-0 select-none px-2 text-right text-slate-400">
                {row.baseNo ?? ''}
              </span>
              <span className="w-10 shrink-0 select-none px-2 text-right text-slate-400">
                {row.headNo ?? ''}
              </span>
              <span className="w-4 shrink-0 select-none text-center">
                {row.kind === 'add' ? '+' : row.kind === 'del' ? '−' : ' '}
              </span>
              <span className="whitespace-pre-wrap break-all pr-4">{row.text || ' '}</span>
            </div>
          )
        })}
      </div>
      {hasTrace ? (
        <footer className="flex items-center gap-3 border-t border-slate-200/70 px-4 py-2 text-[10px] uppercase tracking-wide text-[var(--lever-muted)]">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-[var(--lever-primary)]" /> executed this frame
          </span>
          {responsibleLine ? (
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-[var(--lever-warning)]" /> responsible line
            </span>
          ) : null}
        </footer>
      ) : null}
    </section>
  )
}
