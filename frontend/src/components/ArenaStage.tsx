/** Deterministic particle arena for throughput / retry-storm genres. */

import { useMemo } from 'react'
import type { WidgetConfig } from '../types'

export type ArenaCounts = Readonly<{
  base: number
  head: number
  divergence: number
}>

type ArenaStageProps = Readonly<{
  widget: WidgetConfig
  counts: ArenaCounts
  unit: string | null
  onSurpriseClick?: () => void
}>

type Particle = Readonly<{
  id: number
  lane: 'base' | 'head'
  admitted: boolean
  delayMs: number
  x: number
}>

function sharedSeed(positionKey: string) {
  let hash = 0
  for (let index = 0; index < positionKey.length; index += 1) {
    hash = (hash * 31 + positionKey.charCodeAt(index)) >>> 0
  }
  return hash || 1
}

function buildParticles(base: number, head: number, seed: number): Particle[] {
  const requestCount = Math.min(48, Math.max(base, head, 1))
  const particles: Particle[] = []
  for (let index = 0; index < requestCount; index += 1) {
    const jitter = ((seed * (index + 3)) % 97) / 97
    const x = 8 + ((seed + index * 17) % 84)
    particles.push({
      id: index,
      lane: 'base',
      admitted: index < base,
      delayMs: Math.round(jitter * 900),
      x,
    })
    particles.push({
      id: index + 1000,
      lane: 'head',
      admitted: index < head,
      delayMs: Math.round(jitter * 900),
      x,
    })
  }
  return particles
}

/**
 * Dual-gate request theater bound to real observation counts.
 * Shared arrival seed keeps old/new visually comparable (Rendering Fidelity).
 */
export function ArenaStage({ widget, counts, unit, onSurpriseClick }: ArenaStageProps) {
  const seed = useMemo(
    () => sharedSeed(JSON.stringify(widget.initialPosition)),
    [widget.initialPosition],
  )
  const particles = useMemo(
    () => buildParticles(Math.max(0, Math.round(counts.base)), Math.max(0, Math.round(counts.head)), seed),
    [counts.base, counts.head, seed],
  )
  const surprise = widget.surpriseMarker
  const hot = counts.divergence >= 0.15

  return (
    <section
      data-testid="arena-stage"
      aria-label="Throughput arena"
      className="relative overflow-hidden rounded-xl border border-[var(--lever-text)]/20 bg-[radial-gradient(circle_at_20%_20%,#1a2430,transparent_55%),radial-gradient(circle_at_80%_0%,#2a1a1a,transparent_50%),#0f1419] p-4 text-[#f4efe6] shadow-sm"
    >
      <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold tracking-wide">Arena</h2>
          <p className="text-sm text-[#f4efe6]/80">
            Same arrival seed · {unit ?? 'admitted'} measured at this position
          </p>
        </div>
        <p className="font-mono text-sm" aria-live="polite">
          base {Math.round(counts.base)} · head {Math.round(counts.head)} · Δ {(counts.divergence * 100).toFixed(0)}%
        </p>
      </header>

      <div className="grid gap-4 md:grid-cols-2">
        {(['base', 'head'] as const).map((lane) => {
          const admitted = lane === 'base' ? counts.base : counts.head
          return (
            <div key={lane} className="relative h-56 overflow-hidden rounded-lg border border-white/15 bg-black/25">
              <div className="absolute inset-x-0 top-2 flex items-center justify-between px-3 text-xs uppercase tracking-[0.18em] text-white/70">
                <span>{lane}</span>
                <span className="font-mono normal-case tracking-normal">{Math.round(admitted)} in</span>
              </div>
              <div
                aria-hidden
                className="absolute bottom-10 left-1/2 h-16 w-20 -translate-x-1/2 rounded-md border-2 border-emerald-400/70 bg-emerald-500/10"
                data-testid={`arena-gate-${lane}`}
              />
              <div aria-hidden className="absolute inset-x-6 bottom-6 h-px bg-white/25" />
              {particles
                .filter((particle) => particle.lane === lane)
                .map((particle) => (
                  <span
                    key={particle.id}
                    data-testid="arena-particle"
                    className={`arena-particle absolute bottom-8 h-2.5 w-2.5 rounded-full ${
                      particle.admitted ? 'bg-emerald-300' : 'bg-rose-400/80'
                    }`}
                    style={{
                      left: `${particle.x}%`,
                      animationDelay: `${particle.delayMs}ms`,
                      opacity: particle.admitted ? 0.95 : 0.55,
                    }}
                  />
                ))}
            </div>
          )
        })}
      </div>

      {surprise !== null ? (
        <button
          type="button"
          data-testid="arena-surprise-marker"
          onClick={onSurpriseClick}
          className={`mt-4 w-full rounded-lg border px-3 py-2 text-left text-sm transition ${
            hot
              ? 'arena-surprise-pulse border-amber-300/80 bg-amber-400/15 text-amber-100'
              : 'border-white/20 bg-white/5 text-white/90'
          }`}
        >
          <span className="font-semibold">Surprise · Δ {(surprise.divergence * 100).toFixed(0)}%</span>
          <span className="mt-1 block text-white/80">{surprise.caption}</span>
        </button>
      ) : null}

      {widget.worldSpec.playHints.length > 0 ? (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-white/65">
          {widget.worldSpec.playHints.map((hint) => (
            <li key={hint}>{hint}</li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
