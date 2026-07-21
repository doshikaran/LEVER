/** Receipt duel — two analyzed changes on one synced timeline, head to head. */

import { useMemo, useState } from 'react'
import { CodeDiff } from './CodeDiff'
import type { SourceFile } from '../types'

export type DuelFrame = Readonly<{
  baseLabel: string
  headLabel: string
  divergence: number
  diverges: boolean
  caption: string | null
}>

export type DuelSide = Readonly<{
  changeId: string
  thesis: string
  domainPack: string
  fidelityBand: 'high' | 'medium' | 'low'
  fidelityConfidence: number
  observableLabel: string
  unit: string | null
  base?: SourceFile
  head?: SourceFile
  frames: readonly DuelFrame[]
  maxDivergence: number
}>

type ReceiptDuelProps = Readonly<{
  left: DuelSide
  right: DuelSide
  onClose: () => void
}>

const BAND_TONE: Record<string, string> = {
  high: 'bg-emerald-50 text-emerald-700',
  medium: 'bg-orange-50 text-[var(--lever-warning)]',
  low: 'bg-rose-50 text-rose-700',
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`
}

function SidePanel({ side, index }: { side: DuelSide; index: number }) {
  const frame = side.frames[Math.min(index, side.frames.length - 1)] as DuelFrame | undefined
  return (
    <div className="flex flex-col gap-4">
      <header className="lever-panel rounded-2xl p-4">
        <div className="flex items-center justify-between gap-2">
          <p className="font-mono text-xs text-[var(--lever-muted)]">{side.domainPack}</p>
          <span
            className={`rounded-md px-2 py-0.5 text-xs font-semibold ${BAND_TONE[side.fidelityBand] ?? ''}`}
          >
            {side.fidelityBand} · {pct(side.fidelityConfidence)}
          </span>
        </div>
        <p className="mt-1 font-display text-sm font-semibold text-[var(--lever-text)]">{side.thesis}</p>
      </header>

      <CodeDiff base={side.base} head={side.head} />

      <div
        className={`rounded-2xl border p-4 ${
          frame?.diverges
            ? 'border-[var(--lever-warning)]/50 bg-orange-50/50'
            : 'border-slate-200 bg-white'
        }`}
      >
        <p className="font-display text-xs font-semibold uppercase tracking-wide text-[var(--lever-muted)]">
          {side.observableLabel} at this step
        </p>
        <div className="mt-2 flex items-center gap-4">
          <div className="flex-1">
            <p className="text-[10px] uppercase tracking-wide text-slate-400">old</p>
            <p className="font-display text-lg font-bold text-slate-600">{frame?.baseLabel ?? '—'}</p>
          </div>
          <div className="text-slate-300">→</div>
          <div className="flex-1">
            <p className="text-[10px] uppercase tracking-wide text-slate-400">new</p>
            <p
              className={`font-display text-lg font-bold ${
                frame?.diverges ? 'text-[var(--lever-warning)]' : 'text-emerald-600'
              }`}
            >
              {frame?.headLabel ?? '—'}
            </p>
          </div>
          <div className="w-16 text-right">
            <p className="text-[10px] uppercase tracking-wide text-slate-400">Δ</p>
            <p className="font-display text-lg font-bold text-[var(--lever-text)]">
              {pct(frame?.divergence ?? 0)}
            </p>
          </div>
        </div>
        {frame?.caption ? (
          <p className="mt-2 text-xs text-[var(--lever-muted)]">{frame.caption}</p>
        ) : null}
      </div>
    </div>
  )
}

export function ReceiptDuel({ left, right, onClose }: ReceiptDuelProps) {
  const maxIndex = Math.max(0, Math.min(left.frames.length, right.frames.length) - 1)
  const [index, setIndex] = useState(0)
  const clamped = Math.min(index, maxIndex)

  const verdict = useMemo(() => {
    const l = left.maxDivergence
    const r = right.maxDivergence
    if (l === 0 && r === 0) return 'Neither change diverges under the shared inputs — both look behavior-preserving.'
    if (Math.abs(l - r) < 1e-9) return 'Both changes diverge to the same degree under the shared inputs.'
    const riskier = l > r ? 'Left' : 'Right'
    const ratio = Math.max(l, r) / Math.max(Math.min(l, r), 1e-6)
    const ratioText = Number.isFinite(ratio) && ratio < 100 ? ` (${ratio.toFixed(1)}×)` : ''
    return `${riskier} change is riskier: it diverges ${pct(Math.max(l, r))} vs ${pct(Math.min(l, r))}${ratioText} under the same subsystem load.`
  }, [left.maxDivergence, right.maxDivergence])

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-4" data-testid="receipt-duel">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="font-display text-xl font-bold text-[var(--lever-text)]">Receipt duel</p>
          <p className="text-sm text-[var(--lever-muted)]">
            Two changes, one synced timeline. Every corner is a real measured execution.
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="lever-btn rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-[var(--lever-muted)]"
        >
          Close duel
        </button>
      </div>

      <div
        className="lever-panel rounded-2xl border-l-4 border-[var(--lever-primary)] p-4"
        data-testid="duel-verdict"
      >
        <p className="text-sm font-semibold text-[var(--lever-text)]">{verdict}</p>
      </div>

      <div className="grid gap-5 md:grid-cols-2">
        <SidePanel side={left} index={clamped} />
        <SidePanel side={right} index={clamped} />
      </div>

      {maxIndex > 0 ? (
        <div className="lever-panel rounded-2xl p-4">
          <div className="flex items-center justify-between text-xs text-[var(--lever-muted)]">
            <span>Synced step</span>
            <span>
              {clamped + 1} / {maxIndex + 1}
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={maxIndex}
            value={clamped}
            onChange={(event) => setIndex(Number(event.target.value))}
            className="mt-2 w-full cursor-pointer"
            aria-label="Synced duel step"
            data-testid="duel-scrubber"
          />
        </div>
      ) : null}
    </div>
  )
}
