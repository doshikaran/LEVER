import type { WidgetConfig } from '../types'

type ReceiptPanelProps = Readonly<{
  changeId: string
  widget: WidgetConfig
  open: boolean
  onClose: () => void
}>

/**
 * Trust receipt: band, confidence, thesis, genre — never invents harness numbers.
 * Harness source URI lives on InteractionSpec provenance server-side; widget carries band.
 */
export function ReceiptPanel({ changeId, widget, open, onClose }: ReceiptPanelProps) {
  if (!open) return null

  return (
    <section
      data-testid="receipt-panel"
      aria-labelledby="receipt-heading"
      className="space-y-3 rounded-xl border border-[var(--lever-secondary)]/40 bg-[var(--lever-surface)] p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="receipt-heading" className="text-base font-semibold">Verification receipt</h2>
          <p className="text-sm text-[var(--lever-text)]/80">
            Empirical differential agreement · Symmetrist-gated harness pair
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded border border-[var(--lever-text)]/20 px-2 py-1 text-xs"
        >
          Close
        </button>
      </div>
      <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div>
          <dt className="font-medium">Change id</dt>
          <dd className="break-all font-mono text-xs">{changeId}</dd>
        </div>
        <div>
          <dt className="font-medium">Fidelity</dt>
          <dd>
            {widget.speculative
              ? 'Prospective (not the verified badge)'
              : `${widget.fidelityBand} · ${Math.round(widget.fidelityConfidence * 100)}%`}
          </dd>
        </div>
        <div>
          <dt className="font-medium">Genre</dt>
          <dd>{widget.worldSpec.genre} · {widget.worldSpec.stage.kind}</dd>
        </div>
        <div>
          <dt className="font-medium">Domain pack</dt>
          <dd>{widget.domainPack}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="font-medium">Thesis</dt>
          <dd>{widget.thesis}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="font-medium">Narration (measured)</dt>
          <dd>{widget.worldSpec.narrationLine}</dd>
        </div>
      </dl>
    </section>
  )
}
