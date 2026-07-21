/** "Break the PR" — race the Adversary to find a diverging input first. */

type ChallengePanelProps = Readonly<{
  active: boolean
  userBest: number
  leverBest: number
  hasSurprise: boolean
  onToggle: () => void
  onReveal: () => void
}>

function pct(value: number): string {
  return `${Math.round(value * 100)}%`
}

export function ChallengePanel({
  active,
  userBest,
  leverBest,
  hasSurprise,
  onToggle,
  onReveal,
}: ChallengePanelProps) {
  const won = active && userBest > 0 && userBest >= leverBest - 1e-9
  const close = active && !won && userBest >= leverBest * 0.5

  if (!active) {
    return (
      <section
        data-testid="challenge-panel"
        className="lever-panel flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-dashed border-[var(--lever-warning)]/50 p-4"
      >
        <div>
          <p className="font-display text-sm font-semibold text-[var(--lever-text)]">
            🎮 Break the PR
          </p>
          <p className="text-xs text-[var(--lever-muted)]">
            Hide Lever's answer and hunt for a diverging input yourself. Can you beat the Adversary?
          </p>
        </div>
        <button
          type="button"
          data-testid="challenge-start"
          onClick={onToggle}
          disabled={!hasSurprise}
          className="lever-btn rounded-xl border border-[var(--lever-warning)] bg-orange-50 px-4 py-2 text-sm font-semibold text-[var(--lever-warning)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          Start challenge
        </button>
      </section>
    )
  }

  return (
    <section
      data-testid="challenge-panel"
      className={`lever-panel space-y-3 rounded-2xl border-2 p-4 transition-colors ${
        won ? 'border-emerald-400 bg-emerald-50/60' : 'border-[var(--lever-warning)] bg-orange-50/40'
      }`}
      aria-live="polite"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-display text-sm font-semibold text-[var(--lever-text)]">
          🎮 Break the PR — {won ? 'you win!' : 'find a bigger divergence'}
        </p>
        <div className="flex gap-2">
          <button
            type="button"
            data-testid="challenge-reveal"
            onClick={onReveal}
            className="lever-btn rounded-lg border border-[var(--lever-warning)] bg-white px-3 py-1.5 text-xs font-semibold text-[var(--lever-warning)]"
          >
            Reveal answer
          </button>
          <button
            type="button"
            onClick={onToggle}
            className="lever-btn rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-[var(--lever-muted)]"
          >
            Exit
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-xl border border-slate-200 bg-white p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">You found</p>
          <p className="font-display text-2xl font-bold text-[var(--lever-text)]" data-testid="challenge-user-score">
            {pct(userBest)}
          </p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Lever found</p>
          <p className="font-display text-2xl font-bold text-[var(--lever-primary)]">
            {won ? pct(leverBest) : '???'}
          </p>
        </div>
      </div>

      <p className="text-xs text-[var(--lever-text)]">
        {won
          ? 'You matched the Adversary — that input really does diverge. Pin it as a regression test.'
          : close
            ? 'Warm — you are on a diverging input, but Lever measured a bigger split. Keep turning knobs.'
            : userBest > 0
              ? 'That input diverges a little. Search for where old and new disagree the most.'
              : 'No divergence yet — turn the knobs or scrub to find where old and new disagree.'}
      </p>
    </section>
  )
}
