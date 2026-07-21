/** Shareable "trading card" for a verified microworld — PNG export, no deps. */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { WidgetConfig } from '../types'

type TradingCardProps = Readonly<{
  open: boolean
  onClose: () => void
  widget: WidgetConfig
  changeId: string | null
  permalink: string
  surpriseCaption: string | null
}>

const WIDTH = 640
const HEIGHT = 400

const BAND_COLOR: Record<string, string> = {
  high: '#0f9d78',
  medium: '#d9822b',
  low: '#c0392b',
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

function wrap(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const words = text.split(/\s+/)
  const lines: string[] = []
  let current = ''
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word
    if (ctx.measureText(candidate).width > maxWidth && current) {
      lines.push(current)
      current = word
    } else {
      current = candidate
    }
  }
  if (current) lines.push(current)
  return lines
}

export function TradingCard({
  open,
  onClose,
  widget,
  changeId,
  permalink,
  surpriseCaption,
}: TradingCardProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [copied, setCopied] = useState(false)

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (canvas === null) return
    const ctx = canvas.getContext('2d')
    if (ctx === null) return
    const band = widget.fidelityBand
    const accent = BAND_COLOR[band] ?? '#0f9d78'

    const gradient = ctx.createLinearGradient(0, 0, WIDTH, HEIGHT)
    gradient.addColorStop(0, '#ffffff')
    gradient.addColorStop(1, '#eef4f1')
    ctx.fillStyle = gradient
    ctx.fillRect(0, 0, WIDTH, HEIGHT)

    ctx.fillStyle = accent
    ctx.fillRect(0, 0, WIDTH, 8)

    ctx.fillStyle = '#0f1419'
    ctx.font = '700 20px Georgia, serif'
    ctx.fillText('LEVER · verified microworld', 32, 52)

    ctx.fillStyle = '#5b6670'
    ctx.font = '600 13px monospace'
    ctx.fillText(widget.domainPack.toUpperCase(), 32, 76)

    ctx.fillStyle = '#0f1419'
    ctx.font = '700 24px Georgia, serif'
    const titleLines = wrap(ctx, widget.thesis, WIDTH - 64).slice(0, 3)
    titleLines.forEach((line, index) => ctx.fillText(line, 32, 120 + index * 32))

    let cursorY = 120 + titleLines.length * 32 + 24

    // Confidence pill
    roundRect(ctx, 32, cursorY, 220, 40, 20)
    ctx.fillStyle = accent
    ctx.fill()
    ctx.fillStyle = '#ffffff'
    ctx.font = '700 15px monospace'
    ctx.fillText(
      `confidence ${band} ${Math.round((widget.fidelityConfidence ?? 0) * 100)}%`,
      48,
      cursorY + 26,
    )
    cursorY += 64

    const surprise = surpriseCaption ?? widget.surpriseMarker?.caption ?? null
    if (surprise) {
      ctx.fillStyle = '#5b6670'
      ctx.font = '600 12px monospace'
      ctx.fillText('SURPRISE', 32, cursorY)
      ctx.fillStyle = '#0f1419'
      ctx.font = '400 15px Georgia, serif'
      wrap(ctx, surprise, WIDTH - 64)
        .slice(0, 2)
        .forEach((line, index) => ctx.fillText(line, 32, cursorY + 22 + index * 22))
    }

    ctx.fillStyle = '#9aa4ad'
    ctx.font = '400 12px monospace'
    ctx.fillText(permalink, 32, HEIGHT - 24)
  }, [widget, permalink, surpriseCaption])

  useEffect(() => {
    if (open) draw()
  }, [open, draw])

  const download = useCallback(() => {
    const canvas = canvasRef.current
    if (canvas === null) return
    canvas.toBlob((blob) => {
      if (blob === null) return
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `lever-${changeId ?? 'microworld'}.png`
      link.click()
      URL.revokeObjectURL(url)
    }, 'image/png')
  }, [changeId])

  const copyLink = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(permalink)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }, [permalink])

  if (!open) return null

  return (
    <div
      data-testid="trading-card"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Microworld trading card"
      onClick={onClose}
    >
      <div
        className="lever-panel max-w-2xl space-y-4 rounded-2xl p-5"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <p className="font-display text-lg font-bold text-[var(--lever-text)]">Trading card</p>
          <button
            type="button"
            onClick={onClose}
            className="lever-btn rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-semibold text-[var(--lever-muted)]"
          >
            Close
          </button>
        </div>
        <canvas
          ref={canvasRef}
          width={WIDTH}
          height={HEIGHT}
          className="w-full rounded-xl border border-slate-200 shadow-sm"
        />
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            data-testid="card-download"
            onClick={download}
            className="lever-btn rounded-xl border border-[var(--lever-primary)] bg-[var(--lever-primary)] px-4 py-2 text-sm font-semibold text-white"
          >
            Download PNG
          </button>
          <button
            type="button"
            data-testid="card-copy"
            onClick={() => void copyLink()}
            className="lever-btn rounded-xl border border-[var(--lever-secondary)] px-4 py-2 text-sm font-semibold text-[var(--lever-secondary)]"
          >
            {copied ? 'Link copied!' : 'Copy permalink'}
          </button>
        </div>
      </div>
    </div>
  )
}
