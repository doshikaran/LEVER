import type { FormEvent } from 'react'

export type DemoInfo = Readonly<{
  id: string
  label: string
  description: string
}>

type PrIntakeProps = Readonly<{
  prUrl: string
  onPrUrlChange: (value: string) => void
  onSubmitPr: (event: FormEvent<HTMLFormElement>) => void
  demos: readonly DemoInfo[]
  activeDemoId: string | null
  onRunDemo: (demoId: string) => void
  intakePending: boolean
}>

/** PR-first intake shell: thesis, paste box, curated demo chips. */
export function PrIntake({
  prUrl,
  onPrUrlChange,
  onSubmitPr,
  demos,
  activeDemoId,
  onRunDemo,
  intakePending,
}: PrIntakeProps) {
  return (
    <div className="space-y-6" data-testid="pr-intake">
      <div className="animate-rise space-y-3">
        <p className="lever-brand text-5xl font-extrabold tracking-tight text-[var(--lever-primary)] sm:text-6xl">
          Lever
        </p>
        <h1 className="max-w-2xl text-3xl font-bold leading-tight text-[var(--lever-text)] sm:text-4xl">
          Pull on the behavioral difference
        </h1>
        <p className="max-w-2xl text-base leading-relaxed text-[var(--lever-muted)] sm:text-lg">
          Paste a GitHub pull request. Lever checks out both sides, runs the real code when it can
          verify it, and refuses honestly when it cannot.
        </p>
      </div>

      <form
        onSubmit={onSubmitPr}
        className="lever-panel lever-breathe animate-rise-delay-1 max-w-3xl space-y-3 rounded-2xl p-4"
      >
        <label htmlFor="pr-url" className="block text-sm font-semibold tracking-wide text-[var(--lever-text)]">
          GitHub pull request
        </label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            id="pr-url"
            aria-label="GitHub pull request URL"
            value={prUrl}
            onChange={(event) => onPrUrlChange(event.target.value)}
            placeholder="https://github.com/org/repo/pull/123"
            className="lever-input min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-[var(--lever-text)]"
          />
          <button
            type="submit"
            disabled={!prUrl.trim() || intakePending}
            className="lever-btn lever-btn-primary rounded-xl px-5 py-3 text-sm font-semibold disabled:opacity-50"
          >
            Analyze PR
          </button>
        </div>
      </form>

      {demos.length > 0 ? (
        <div className="animate-rise-delay-2 max-w-3xl space-y-3">
          <p className="text-sm font-semibold uppercase tracking-[0.14em] text-[var(--lever-muted)]">
            Or try a demo
          </p>
          <div className="flex flex-wrap gap-2">
            {demos.map((demo) => (
              <button
                key={demo.id}
                type="button"
                title={demo.description}
                disabled={intakePending}
                onClick={() => onRunDemo(demo.id)}
                className={`lever-chip rounded-xl border px-4 py-2.5 text-left text-sm font-medium disabled:opacity-50 ${
                  activeDemoId === demo.id
                    ? 'border-transparent bg-[var(--lever-primary)] text-white shadow-lg shadow-teal-900/15'
                    : 'border-slate-200 bg-white text-[var(--lever-text)] hover:border-[var(--lever-primary)]/40'
                }`}
              >
                {demo.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
