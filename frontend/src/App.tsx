import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { HonestChart } from './components/HonestChart'
import { KnobPanel } from './components/KnobPanel'
import { DegradationPanel } from './components/DegradationPanel'
import { SourceViewer } from './components/SourceViewer'
import { useMicroworldStore } from './store/useMicroworldStore'
import type {
  CompleteEvent,
  DegradationEvent,
  EvaluationEvent,
  KnobPosition,
  ObservationBundle,
  ProgressEvent,
  ResponsibleLine,
  SourceFiles,
  WidgetConfig,
} from './types'

const API_BASE = import.meta.env.VITE_LEVER_API_BASE ?? 'http://127.0.0.1:8765'
const HERO_1 = {
  base_file_path:
    import.meta.env.VITE_HERO1_BASE_FILE_PATH ??
    '/Users/karandoshi/Desktop/Karan Doshi/Projects/OpenAI Hackathon/lever/fixtures/hero1/base.py',
  head_file_path:
    import.meta.env.VITE_HERO1_HEAD_FILE_PATH ??
    '/Users/karandoshi/Desktop/Karan Doshi/Projects/OpenAI Hackathon/lever/fixtures/hero1/head.py',
}
const DRAG_SETTLE_MS = 120

type PendingRequest = Readonly<{ key: string; version: number }>

function socketBase(apiBase: string) {
  const url = new URL(apiBase)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString().replace(/\/$/, '')
}

function canonicalNumber(value: number) {
  if (!Number.isFinite(value)) throw new Error('Knob positions must contain finite numbers.')
  if (Object.is(value, -0)) return '-0'
  if (value === 0) return '0'
  const exponent = Math.floor(Math.log10(Math.abs(value)))
  if (exponent >= -4 && exponent < 15) {
    return Number.parseFloat(value.toPrecision(15)).toString()
  }
  const [mantissa, rawExponent] = value.toExponential(14).split('e')
  const normalizedMantissa = mantissa.replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1')
  const exponentSign = rawExponent.startsWith('-') ? '-' : '+'
  const exponentValue = rawExponent.replace(/[+-]/, '').padStart(2, '0')
  return `${normalizedMantissa}e${exponentSign}${exponentValue}`
}

function canonicalPosition(position: KnobPosition) {
  return `{${Object.keys(position)
    .sort()
    .map((key) => {
      const value = position[key]
      const encoded =
        typeof value === 'number'
          ? canonicalNumber(value)
          : typeof value === 'boolean'
            ? String(value)
            : JSON.stringify(value)
      return `${JSON.stringify(key)}:${encoded}`
    })
    .join(',')}}`
}

async function hashPosition(position: KnobPosition) {
  const bytes = new TextEncoder().encode(canonicalPosition(position))
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function chartValues(observations: ObservationBundle | null, observableId: string) {
  const base = Number(observations?.base[observableId] ?? 0)
  const head = Number(observations?.head[observableId] ?? 0)
  return {
    base,
    head,
    divergence: head === base ? 0 : Math.abs(head - base) / Math.max(Math.abs(head), Math.abs(base), 1),
  }
}

function observationCaption(observations: ObservationBundle | null, observableId: string) {
  if (observations === null) return null
  const { base, head } = chartValues(observations, observableId)
  if (base <= 0 || head < 0) return `Base: ${base}; Head: ${head}.`
  return `Head admits ${(head / base).toFixed(1)}× as many requests (${head} vs ${base}).`
}

function isDegradationEvent(event: { type?: unknown }): event is DegradationEvent {
  return ['skipped', 'unscopable', 'inert', 'degraded'].includes(String(event.type))
}

function App() {
  const position = useMicroworldStore((state) => state.position)
  const replacePosition = useMicroworldStore((state) => state.replacePosition)
  const replaceCache = useMicroworldStore((state) => state.replaceCache)
  const putCachedObservation = useMicroworldStore((state) => state.putCachedObservation)
  const [progress, setProgress] = useState<ProgressEvent[]>([])
  const [widget, setWidget] = useState<WidgetConfig | null>(null)
  const [degradation, setDegradation] = useState<DegradationEvent | null>(null)
  const [observations, setObservations] = useState<ObservationBundle | null>(null)
  const [loadingKey, setLoadingKey] = useState<string | null>(null)
  const [evaluationSource, setEvaluationSource] = useState<'cache' | 'fresh' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sourceFiles, setSourceFiles] = useState<SourceFiles>({})
  const [selectedLine, setSelectedLine] = useState<ResponsibleLine | null>(null)
  const [attributionMessage, setAttributionMessage] = useState<string | null>(null)
  const socket = useRef<WebSocket | null>(null)
  const pendingRequests = useRef(new Map<string, PendingRequest>())
  const positionVersion = useRef(0)
  const dragSettleTimer = useRef<number | undefined>(undefined)

  const evaluatePosition = useCallback(async (nextPosition: KnobPosition, version: number) => {
    // A new input invalidates a prior source selection immediately.  Do this
    // before awaiting the position hash so a late cache lookup cannot erase a
    // source viewer the user has just opened for the current point.
    setSelectedLine(null)
    setAttributionMessage(null)
    const key = await hashPosition(nextPosition)
    if (version !== positionVersion.current) return

    const cacheHit = useMicroworldStore.getState().cache.get(key)
    if (cacheHit) {
      setObservations(cacheHit)
      setEvaluationSource('cache')
      setLoadingKey(null)
      return
    }

    if (socket.current?.readyState !== WebSocket.OPEN) {
      setError('The evaluation connection is not ready.')
      return
    }
    const requestId = crypto.randomUUID()
    pendingRequests.current.set(requestId, { key, version })
    setLoadingKey(key)
    socket.current.send(JSON.stringify({ type: 'evaluate', requestId, position: nextPosition }))
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let disposed = false

    async function start() {
      try {
        const response = await fetch(`${API_BASE}/diffs`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(HERO_1),
          signal: controller.signal,
        })
        if (!response.ok) throw new Error(`Diff request failed (${response.status}).`)
        const { changeId } = (await response.json()) as { changeId: string }
        const nextSocket = new WebSocket(`${socketBase(API_BASE)}/ws/${changeId}`)
        socket.current = nextSocket

        nextSocket.onmessage = (message) => {
          const event = JSON.parse(message.data) as { type?: unknown }
          if (event.type === 'progress') {
            setProgress((current) => [...current, event as ProgressEvent])
            return
          }
          if (event.type === 'complete') {
            const complete = event as CompleteEvent
            replaceCache(new Map(Object.entries(complete.positionCache)))
            replacePosition(complete.widgetConfig.initialPosition)
            setDegradation(null)
            setWidget(complete.widgetConfig)
            setSourceFiles(complete.sourceFiles)
            setSelectedLine(null)
            setAttributionMessage(null)
            setEvaluationSource(null)
            return
          }
          if (isDegradationEvent(event)) {
            setDegradation(event)
            setWidget(null)
            setObservations(null)
            setLoadingKey(null)
            setEvaluationSource(null)
            setSourceFiles({})
            setSelectedLine(null)
            setAttributionMessage(null)
            replacePosition({})
            replaceCache(new Map())
            setError(null)
            return
          }
          if (event.type === 'evaluation') {
            const evaluation = event as EvaluationEvent
            const pending = pendingRequests.current.get(evaluation.requestId)
            pendingRequests.current.delete(evaluation.requestId)
            putCachedObservation(evaluation.positionKey, evaluation.observations)
            if (pending?.version === positionVersion.current) {
              setObservations(evaluation.observations)
              setEvaluationSource(evaluation.source)
              setLoadingKey(null)
              setSelectedLine(null)
              setAttributionMessage(null)
            }
            return
          }
          if (event.type === 'evaluation_error') {
            const failed = event as { requestId?: string; error?: string }
            pendingRequests.current.delete(failed.requestId ?? '')
            setLoadingKey(null)
            setError(failed.error ?? 'Position evaluation failed.')
            return
          }
          if (event.type === 'error') {
            const failed = event as { error?: string }
            setError(failed.error ?? 'Lever could not produce an interactive result.')
          }
        }
        nextSocket.onerror = () => setError('The WebSocket connection failed.')
      } catch (reason) {
        if (!disposed) setError(reason instanceof Error ? reason.message : 'Could not start Lever.')
      }
    }

    void start()
    return () => {
      disposed = true
      controller.abort()
      socket.current?.close()
    }
  }, [putCachedObservation, replaceCache, replacePosition])

  useEffect(() => {
    if (widget === null || degradation !== null || Object.keys(position).length === 0) return
    if (dragSettleTimer.current !== undefined) {
      window.clearTimeout(dragSettleTimer.current)
    }
    const settledPosition = { ...position }
    dragSettleTimer.current = window.setTimeout(() => {
      positionVersion.current += 1
      void evaluatePosition(settledPosition, positionVersion.current)
      dragSettleTimer.current = undefined
    }, DRAG_SETTLE_MS)
    return () => {
      if (dragSettleTimer.current !== undefined) {
        window.clearTimeout(dragSettleTimer.current)
      }
    }
  }, [degradation, evaluatePosition, position, widget])

  const chart = widget === null ? null : widget.charts[0]
  const values = chart ? chartValues(observations, chart.observableId) : null
  const caption = chart ? observationCaption(observations, chart.observableId) : null
  const status = useMemo(() => {
    if (loadingKey) return 'Evaluating this position…'
    if (evaluationSource === 'fresh') {
      return `Fresh microworld evaluation — not individually ground-truth verified; overall microworld confidence: ${widget?.fidelityBand ?? 'unknown'} (${Math.round((widget?.fidelityConfidence ?? 0) * 100)}%).`
    }
    if (evaluationSource === 'cache') return 'Cache hit — no network call'
    if (widget) return 'Verified position'
    if (degradation) return 'Analysis stopped before rendering a toy.'
    return 'Preparing analysis…'
  }, [degradation, evaluationSource, loadingKey, widget])

  const openResponsibleLine = useCallback(() => {
    const responsibleLine = observations?.trace?.responsibleLine
    if (responsibleLine === null || responsibleLine === undefined) {
      setAttributionMessage('No version-exclusive executed entry-point line was recorded for this position.')
      return
    }
    if (sourceFiles[responsibleLine.version] === undefined) {
      setAttributionMessage('The analyzed source file is unavailable for this persisted session.')
      return
    }
    setAttributionMessage(null)
    setSelectedLine(responsibleLine)
  }, [observations, sourceFiles])

  const selectedSourceFile = selectedLine === null ? undefined : sourceFiles[selectedLine.version]

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-6 text-slate-950">
      <header className="space-y-2">
        <p className="text-sm font-medium text-blue-700">Lever / Hero 1</p>
        <h1 className="text-3xl font-semibold">Pull on the behavioral difference</h1>
        <p className="max-w-3xl text-slate-700">
          {degradation
            ? 'Lever stopped before rendering a toy.'
            : widget?.thesis ?? 'Preparing the verified rate-limiter comparison…'}
        </p>
      </header>

      <ol aria-label="Analysis progress" className="space-y-1 text-sm text-slate-700">
        {progress.map((event) => <li key={event.stage}>{event.message}</li>)}
      </ol>

      {error ? <p role="alert" className="text-sm text-red-700">{error}</p> : null}

      {degradation ? <DegradationPanel event={degradation} /> : null}

      {!degradation && widget && chart && values ? (
        <section className="grid gap-8 lg:grid-cols-[18rem_minmax(0,1fr)]">
          <KnobPanel controls={widget.controls} />
          <div className="space-y-3">
            <p className="text-sm text-slate-600" aria-live="polite">{status}</p>
            <HonestChart
              title={chart.label}
              divergence={values.divergence}
              data={[{ x: 'Current position', base: values.base, head: values.head }]}
              onPointClick={openResponsibleLine}
            />
            {attributionMessage ? <p role="status" className="text-sm text-slate-600">{attributionMessage}</p> : null}
            <p aria-live="polite" className="text-base font-medium text-slate-950">
              {caption ?? widget.surpriseMarker?.caption ?? 'Choose a cached position to inspect it.'}
            </p>
            {selectedLine && selectedSourceFile ? (
              <SourceViewer
                responsibleLine={selectedLine}
                sourceFile={selectedSourceFile}
                onClose={() => setSelectedLine(null)}
              />
            ) : null}
          </div>
        </section>
      ) : null}
    </main>
  )
}

export default App
