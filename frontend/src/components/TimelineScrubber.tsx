/** Game-style transport bar: scrub through measured inputs like frames in a replay. */

type Step = Readonly<{ divergence: number }>

type TimelineScrubberProps = Readonly<{
  steps: readonly Step[]
  currentIndex: number
  surpriseIndex?: number
  isPlaying: boolean
  canPlay: boolean
  onSeek: (index: number) => void
  onPrev: () => void
  onNext: () => void
  onReset: () => void
  onPlayToggle: () => void
  onJumpToSurprise?: () => void
}>

/** Map a normalized divergence (0..1) to a tick color — calm green to hot amber. */
function tickTone(divergence: number, active: boolean, isSurprise: boolean): string {
  if (isSurprise && !active) {
    return 'bg-[var(--lever-warning)] ring-2 ring-orange-300 hover:bg-orange-500'
  }
  if (active) return 'bg-[var(--lever-primary)] ring-2 ring-[var(--lever-primary)]/40'
  if (divergence <= 0) return 'bg-emerald-300/70 hover:bg-emerald-400'
  if (divergence < 0.25) return 'bg-amber-300/80 hover:bg-amber-400'
  return 'bg-[var(--lever-warning)] hover:bg-orange-500'
}

export function TimelineScrubber({
  steps,
  currentIndex,
  surpriseIndex = -1,
  isPlaying,
  canPlay,
  onSeek,
  onPrev,
  onNext,
  onReset,
  onPlayToggle,
  onJumpToSurprise,
}: TimelineScrubberProps) {
  const total = steps.length
  const human = currentIndex >= 0 ? currentIndex + 1 : 0

  return (
    <section
      data-testid="timeline-scrubber"
      className="lever-panel rounded-2xl p-4"
      aria-label="Simulation timeline"
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="font-display text-xs font-semibold uppercase tracking-wide text-[var(--lever-muted)]">
          Timeline
        </p>
        <p className="font-mono text-xs text-[var(--lever-muted)]" data-testid="step-counter">
          Step <span className="font-semibold text-[var(--lever-text)]">{human}</span> of {total}
        </p>
      </div>

      <div
        className="flex min-h-10 flex-wrap items-center gap-1.5 rounded-xl bg-slate-100/70 p-2"
        role="group"
        aria-label="Measured inputs"
      >
        {total === 0 ? (
          <span className="px-2 text-xs text-[var(--lever-muted)]">No measured frames yet.</span>
        ) : (
          steps.map((step, index) => {
            const isSurprise = index === surpriseIndex
            return (
              <button
                key={index}
                type="button"
                title={`Frame ${index + 1}${step.divergence > 0 ? ' · diverges' : ''}${isSurprise ? ' · surprise' : ''}`}
                aria-label={`Go to frame ${index + 1}${isSurprise ? ' (surprise)' : ''}`}
                aria-current={index === currentIndex}
                onClick={() => onSeek(index)}
                className={`h-6 w-2.5 rounded-full transition-all duration-200 ${tickTone(
                  step.divergence,
                  index === currentIndex,
                  isSurprise,
                )} ${index === currentIndex ? 'scale-y-125' : 'hover:scale-y-110'}`}
              />
            )
          })
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onReset}
          disabled={total === 0}
          className="lever-btn rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-40"
        >
          ⟲ Reset
        </button>
        <button
          type="button"
          data-testid="step-prev"
          onClick={onPrev}
          disabled={total === 0 || currentIndex <= 0}
          className="lever-btn rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-40"
        >
          ‹ Prev
        </button>
        <button
          type="button"
          data-testid="sim-play"
          onClick={onPlayToggle}
          disabled={!canPlay}
          className="lever-btn rounded-lg border border-[var(--lever-primary)] bg-[var(--lever-primary)] px-4 py-1.5 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isPlaying ? '⏸ Pause' : '▶ Play'}
        </button>
        <button
          type="button"
          data-testid="step-next"
          onClick={onNext}
          disabled={total === 0 || currentIndex >= total - 1}
          className="lever-btn rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-40"
        >
          Next ›
        </button>
        {onJumpToSurprise ? (
          <button
            type="button"
            data-testid="jump-surprise"
            onClick={onJumpToSurprise}
            className="lever-btn rounded-lg border border-[var(--lever-warning)] bg-orange-50 px-3 py-1.5 text-xs font-semibold text-[var(--lever-warning)]"
          >
            ⚡ Surprise
          </button>
        ) : null}
        <span className="ml-auto flex items-center gap-3 text-[10px] uppercase tracking-wide text-[var(--lever-muted)]">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-emerald-300" /> agree
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-[var(--lever-warning)]" /> diverge
          </span>
        </span>
      </div>
    </section>
  )
}
