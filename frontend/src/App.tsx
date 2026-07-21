import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { MicroworldCanvas } from './components/MicroworldCanvas'
import { KnobPanel } from './components/KnobPanel'
import { DegradationPanel } from './components/DegradationPanel'
import { SourceViewer } from './components/SourceViewer'
import { UnionTree } from './components/UnionTree'
import { SearchTrace } from './components/SearchTrace'
import { ObjectiveSelector } from './components/ObjectiveSelector'
import { useMicroworldStore } from './store/useMicroworldStore'
import type {
  CompleteEvent,
  DegradationEvent,
  EvaluationEvent,
  KnobPosition,
  ObservationBundle,
  ObjectiveResultEvent,
  ProgressEvent,
  ResponsibleLine,
  SearchTraceEvent,
  SearchTracePoint,
  SourceFiles,
  SearchObjective,
  UnsafePredicate,
  WidgetConfig,
} from './types'

const API_BASE = import.meta.env.VITE_LEVER_API_BASE ?? 'http://127.0.0.1:8765'

type HeroConfig = Readonly<{ id: string; label: string; base_file_path: string; head_file_path: string }>

function requireEnv(key: string): string {
  const value = import.meta.env[key]
  if (!value) {
    throw new Error(`Missing required env var ${key} — copy frontend/.env.example to frontend/.env.local`)
  }
  return value
}

const HEROES: readonly HeroConfig[] = [
  {
    id: 'hero1',
    label: 'Hero 1 — rate limiter',
    base_file_path: requireEnv('VITE_HERO1_BASE_FILE_PATH'),
    head_file_path: requireEnv('VITE_HERO1_HEAD_FILE_PATH'),
  },
  {
    id: 'hero2',
    label: 'Hero 2 — retry backoff',
    base_file_path: requireEnv('VITE_HERO2_BASE_FILE_PATH'),
    head_file_path: requireEnv('VITE_HERO2_HEAD_FILE_PATH'),
  },
  {
    id: 'hero3',
    label: 'Hero 3 — permission check',
    base_file_path: requireEnv('VITE_HERO3_BASE_FILE_PATH'),
    head_file_path: requireEnv('VITE_HERO3_HEAD_FILE_PATH'),
  },
  {
    id: 'hero4',
    label: 'Hero 4 — feature flag',
    base_file_path: requireEnv('VITE_HERO4_BASE_FILE_PATH'),
    head_file_path: requireEnv('VITE_HERO4_HEAD_FILE_PATH'),
  },
]
const DRAG_SETTLE_MS = 120

type PendingRequest = Readonly<{ key: string; version: number; position: KnobPosition }>

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

type EvaluationDispatchResult =
  | Readonly<{ kind: 'cache-hit'; observations: ObservationBundle }>
  | Readonly<{ kind: 'not-ready' }>
  | Readonly<{ kind: 'sent' }>

/**
 * Shared cache-check-then-send path used by both evaluatePosition (drag-driven,
 * updates the single "current position" chart, cancellable via positionVersion)
 * and evaluateOnePosition (one grid cell, resolved independently via
 * pendingGridResolvers). Looks up the shared Zustand cache by the
 * already-hashed key; on a miss with an open socket, generates a requestId,
 * calls `registerPending(requestId)` so the caller can record its own
 * bookkeeping *before* the WS message is sent (preserving each call site's
 * original ordering), then sends the request. Callers keep their own distinct
 * state-update / promise-resolution semantics on the returned result — this
 * only unifies the request-sending path they had in common.
 */
function dispatchEvaluationRequest(
  socketRef: WebSocket | null,
  key: string,
  position: KnobPosition,
  registerPending: (requestId: string) => void,
): EvaluationDispatchResult {
  const cacheHit = useMicroworldStore.getState().cache.get(key)
  if (cacheHit) return { kind: 'cache-hit', observations: cacheHit }
  if (socketRef?.readyState !== WebSocket.OPEN) return { kind: 'not-ready' }
  const requestId = crypto.randomUUID()
  registerPending(requestId)
  socketRef.send(JSON.stringify({ type: 'evaluate', requestId, position }))
  return { kind: 'sent' }
}

function App() {
  const [selectedHeroId, setSelectedHeroId] = useState(HEROES[0].id)
  const selectedHero = HEROES.find((hero) => hero.id === selectedHeroId) ?? HEROES[0]
  const position = useMicroworldStore((state) => state.position)
  const replacePosition = useMicroworldStore((state) => state.replacePosition)
  const replaceCache = useMicroworldStore((state) => state.replaceCache)
  const putCachedObservation = useMicroworldStore((state) => state.putCachedObservation)
  const [progress, setProgress] = useState<ProgressEvent[]>([])
  const [searchTrace, setSearchTrace] = useState<SearchTracePoint[]>([])
  const [widget, setWidget] = useState<WidgetConfig | null>(null)
  const [changeId, setChangeId] = useState<string | null>(null)
  const [degradation, setDegradation] = useState<DegradationEvent | null>(null)
  const [observations, setObservations] = useState<ObservationBundle | null>(null)
  const [observedPosition, setObservedPosition] = useState<KnobPosition | null>(null)
  const [loadingKey, setLoadingKey] = useState<string | null>(null)
  const [evaluationSource, setEvaluationSource] = useState<'cache' | 'fresh' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sourceFiles, setSourceFiles] = useState<SourceFiles>({})
  const [selectedLine, setSelectedLine] = useState<ResponsibleLine | null>(null)
  const [attributionMessage, setAttributionMessage] = useState<string | null>(null)
  const [pinStatus, setPinStatus] = useState<string | null>(null)
  const [objectiveLoading, setObjectiveLoading] = useState(false)
  const [objectiveFinding, setObjectiveFinding] = useState<string | null>(null)
  const [hypothesis, setHypothesis] = useState('')
  const [prospectivePending, setProspectivePending] = useState(false)
  const socket = useRef<WebSocket | null>(null)
  const pendingRequests = useRef(new Map<string, PendingRequest>())
  const pendingGridResolvers = useRef(
    new Map<string, Readonly<{ resolve: (observations: ObservationBundle | null) => void; reject: (error: Error) => void }>>(),
  )
  const positionVersion = useRef(0)
  const dragSettleTimer = useRef<number | undefined>(undefined)
  const selectedTracePosition = useRef<KnobPosition | null>(null)

  const evaluatePosition = useCallback(async (nextPosition: KnobPosition, version: number) => {
    // A new input invalidates a prior source selection immediately.  Do this
    // before awaiting the position hash so a late cache lookup cannot erase a
    // source viewer the user has just opened for the current point.
    setSelectedLine(null)
    setAttributionMessage(null)
    setPinStatus(null)
    const key = await hashPosition(nextPosition)
    if (version !== positionVersion.current) return

    const result = dispatchEvaluationRequest(socket.current, key, nextPosition, (requestId) => {
      pendingRequests.current.set(requestId, { key, version, position: { ...nextPosition } })
      setLoadingKey(key)
    })
    if (result.kind === 'cache-hit') {
      setObservations(result.observations)
      setObservedPosition({ ...nextPosition })
      setEvaluationSource('cache')
      setLoadingKey(null)
      return
    }
    if (result.kind === 'not-ready') {
      setError('The evaluation connection is not ready.')
    }
  }, [])

  // A permission-grid cell's evaluation must not disturb the single "current
  // position" chart state (observations/observedPosition/loadingKey) that
  // evaluatePosition above owns, and must not be cancelled by positionVersion
  // bumps from concurrent knob drags. It reuses the same WebSocket protocol
  // and cache (so cache hits are shared) but resolves via its own map instead.
  const evaluateOnePosition = useCallback(async (nextPosition: KnobPosition): Promise<ObservationBundle | null> => {
    const key = await hashPosition(nextPosition)
    return new Promise<ObservationBundle | null>((resolve, reject) => {
      const result = dispatchEvaluationRequest(socket.current, key, nextPosition, (requestId) => {
        pendingGridResolvers.current.set(requestId, { resolve, reject })
      })
      if (result.kind === 'cache-hit') {
        resolve(result.observations)
      } else if (result.kind === 'not-ready') {
        resolve(null)
      }
      // 'sent': the resolver was already registered above; connectToChange's
      // onmessage handler resolves/rejects it when a reply (or a hero switch
      // that closes this socket) arrives.
    })
  }, [])

  const evaluateManyPositions = useCallback(async (positions: readonly KnobPosition[]) => {
    const entries = await Promise.all(
      positions.map(async (candidatePosition) => {
        const observations = await evaluateOnePosition(candidatePosition)
        return [JSON.stringify(candidatePosition), observations] as const
      }),
    )
    const result: Record<string, ObservationBundle> = {}
    for (const [key, observations] of entries) {
      if (observations !== null) result[key] = observations
    }
    return result
  }, [evaluateOnePosition])

  // Grid-cell fetches are awaited via Promise.all in evaluateManyPositions. If
  // the socket that would have delivered their reply closes first (hero
  // switch, unmount, or reconnecting to a new change), any resolver left in
  // this map would otherwise never settle — hanging that Promise.all forever
  // with no visible error. Reject them all instead so callers observe a clear
  // failure.
  const rejectPendingGridResolvers = useCallback((message: string) => {
    if (pendingGridResolvers.current.size === 0) return
    for (const { reject } of pendingGridResolvers.current.values()) {
      reject(new Error(message))
    }
    pendingGridResolvers.current.clear()
  }, [])

  const connectToChange = useCallback((nextChangeId: string) => {
    rejectPendingGridResolvers('The evaluation connection was replaced before this position could be evaluated.')
    socket.current?.close()
    const nextSocket = new WebSocket(`${socketBase(API_BASE)}/ws/${nextChangeId}`)
    socket.current = nextSocket
    nextSocket.onmessage = (message) => {
      const event = JSON.parse(message.data) as { type?: unknown }
      if (event.type === 'progress') {
        setProgress((current) => [...current, event as ProgressEvent])
        return
      }
      if (event.type === 'search_trace') {
        const traceEvent = event as SearchTraceEvent
        setSearchTrace((current) => [...current, traceEvent.tracePoint])
        return
      }
      if (event.type === 'complete') {
        const complete = event as CompleteEvent
        replaceCache(new Map(Object.entries(complete.positionCache)))
        replacePosition(selectedTracePosition.current ?? complete.widgetConfig.initialPosition)
        setDegradation(null)
        setWidget(complete.widgetConfig)
        setChangeId(complete.changeId)
        setSourceFiles(complete.sourceFiles)
        setObservedPosition(null)
        setSelectedLine(null)
        setAttributionMessage(null)
        setPinStatus(null)
        setEvaluationSource(null)
        setObjectiveLoading(false)
        setObjectiveFinding(null)
        setProspectivePending(false)
        return
      }
      if (isDegradationEvent(event)) {
        setDegradation(event)
        setWidget(null)
        setChangeId(null)
        setObservations(null)
        setObservedPosition(null)
        setLoadingKey(null)
        setEvaluationSource(null)
        setSourceFiles({})
        setSelectedLine(null)
        setAttributionMessage(null)
        setPinStatus(null)
        setSearchTrace([])
        selectedTracePosition.current = null
        replacePosition({})
        replaceCache(new Map())
        setError(null)
        setObjectiveLoading(false)
        setObjectiveFinding(null)
        setProspectivePending(false)
        return
      }
      if (event.type === 'evaluation') {
        const evaluation = event as EvaluationEvent
        const gridResolver = pendingGridResolvers.current.get(evaluation.requestId)
        if (gridResolver) {
          pendingGridResolvers.current.delete(evaluation.requestId)
          putCachedObservation(evaluation.positionKey, evaluation.observations)
          gridResolver.resolve(evaluation.observations)
          return
        }
        const pending = pendingRequests.current.get(evaluation.requestId)
        pendingRequests.current.delete(evaluation.requestId)
        putCachedObservation(evaluation.positionKey, evaluation.observations)
        if (pending?.version === positionVersion.current) {
          setObservations(evaluation.observations)
          setObservedPosition(pending.position)
          setEvaluationSource(evaluation.source)
          setLoadingKey(null)
          setSelectedLine(null)
          setAttributionMessage(null)
        }
        return
      }
      if (event.type === 'evaluation_error') {
        const failed = event as { requestId?: string; error?: string }
        const gridResolver = pendingGridResolvers.current.get(failed.requestId ?? '')
        if (gridResolver) {
          pendingGridResolvers.current.delete(failed.requestId ?? '')
          gridResolver.resolve(null)
          return
        }
        pendingRequests.current.delete(failed.requestId ?? '')
        setLoadingKey(null)
        setError(failed.error ?? 'Position evaluation failed.')
        return
      }
      if (event.type === 'objective_started') {
        setSearchTrace([])
        setObjectiveLoading(true)
        setObjectiveFinding(null)
        return
      }
      if (event.type === 'objective_result') {
        const result = event as ObjectiveResultEvent
        replaceCache(new Map(Object.entries(result.positionCache)))
        setObjectiveLoading(false)
        if (result.surpriseMarker !== null) {
          selectedTracePosition.current = { ...result.surpriseMarker.position }
          replacePosition(result.surpriseMarker.position)
          setObjectiveFinding(result.surpriseMarker.caption)
        } else {
          setObjectiveFinding(result.reason ?? 'No unsafe state was reached.')
        }
        return
      }
      if (event.type === 'objective_error') {
        const failed = event as { error?: string }
        setObjectiveLoading(false)
        setError(failed.error ?? 'Security search failed.')
        return
      }
      if (event.type === 'error') {
        const failed = event as { error?: string }
        setProspectivePending(false)
        setError(failed.error ?? 'Lever could not produce an interactive result.')
      }
    }
    nextSocket.onerror = () => {
      setProspectivePending(false)
      setError('The WebSocket connection failed.')
    }
  }, [putCachedObservation, replaceCache, replacePosition, rejectPendingGridResolvers])

  useEffect(() => {
    const controller = new AbortController()
    let disposed = false

    // Switching heroes must not leave the previous hero's widget, progress log,
    // or cached position visible while the new hero's diff is still loading.
    setProgress([])
    setSearchTrace([])
    setWidget(null)
    setChangeId(null)
    setDegradation(null)
    setObservations(null)
    setObservedPosition(null)
    setLoadingKey(null)
    setEvaluationSource(null)
    setSourceFiles({})
    setSelectedLine(null)
    setAttributionMessage(null)
    setPinStatus(null)
    setError(null)
    setObjectiveLoading(false)
    setObjectiveFinding(null)
    setProspectivePending(false)
    selectedTracePosition.current = null
    replacePosition({})
    replaceCache(new Map())

    async function start() {
      try {
        const response = await fetch(`${API_BASE}/diffs`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(selectedHero),
          signal: controller.signal,
        })
        if (!response.ok) throw new Error(`Diff request failed (${response.status}).`)
        const { changeId } = (await response.json()) as { changeId: string }
        connectToChange(changeId)
      } catch (reason) {
        if (!disposed) setError(reason instanceof Error ? reason.message : 'Could not start Lever.')
      }
    }

    void start()
    return () => {
      disposed = true
      controller.abort()
      rejectPendingGridResolvers('Hero changed before this position could be evaluated')
      socket.current?.close()
    }
  }, [connectToChange, selectedHeroId, selectedHero, replaceCache, replacePosition, rejectPendingGridResolvers])

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
  const unionTree = widget?.unionTree ?? null
  const values = chart ? chartValues(observations, chart.observableId) : null
  const caption = objectiveFinding ?? (chart ? observationCaption(observations, chart.observableId) : null)
  const status = useMemo(() => {
    if (objectiveLoading) return 'Searching boundary-weighted adversarial inputs…'
    if (loadingKey) return 'Evaluating this position…'
    if (evaluationSource === 'fresh') {
      return `Fresh microworld evaluation — not individually ground-truth verified; overall microworld confidence: ${widget?.fidelityBand ?? 'unknown'} (${Math.round((widget?.fidelityConfidence ?? 0) * 100)}%).`
    }
    if (evaluationSource === 'cache') return 'Cache hit — no network call'
    if (widget) return 'Verified position'
    if (degradation) return 'Analysis stopped before rendering a toy.'
    return 'Preparing analysis…'
  }, [degradation, evaluationSource, loadingKey, objectiveLoading, widget])

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
  const hasCurrentObservation = (
    observations !== null
    && observedPosition !== null
    && canonicalPosition(observedPosition) === canonicalPosition(position)
  )

  const pinCurrentPosition = useCallback(async () => {
    if (changeId === null || observedPosition === null || !hasCurrentObservation) {
      setPinStatus('Evaluate this exact position before pinning it.')
      return
    }
    setPinStatus('Writing regression test…')
    try {
      const response = await fetch(`${API_BASE}/diffs/${changeId}/pin`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ position: observedPosition }),
      })
      const payload = await response.json() as { testPath?: string; detail?: string }
      if (!response.ok || payload.testPath === undefined) {
        throw new Error(payload.detail ?? `Pin request failed (${response.status}).`)
      }
      setPinStatus(`Pinned regression test: ${payload.testPath}`)
    } catch (reason) {
      setPinStatus(reason instanceof Error ? reason.message : 'Could not write the regression test.')
    }
  }, [changeId, hasCurrentObservation, observedPosition])

  const selectSearchPosition = useCallback((nextPosition: KnobPosition) => {
    // Search Trace clicks use the same Zustand position and cache-forward
    // evaluation path as knob drags. They never synthesize an inverse query.
    selectedTracePosition.current = { ...nextPosition }
    replacePosition(nextPosition)
  }, [replacePosition])

  const runObjective = useCallback((objective: SearchObjective, unsafePredicate?: UnsafePredicate) => {
    if (socket.current?.readyState !== WebSocket.OPEN) {
      setError('The search connection is not ready.')
      return
    }
    socket.current.send(JSON.stringify({
      type: 'search_objective',
      requestId: crypto.randomUUID(),
      objective,
      unsafePredicate,
    }))
  }, [])

  const submitProspective = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!hypothesis.trim()) return
    try {
      setError(null)
      setProgress([])
      setSearchTrace([])
      setWidget(null)
      setDegradation(null)
      setObservations(null)
      setObservedPosition(null)
      setEvaluationSource(null)
      setObjectiveFinding(null)
      setProspectivePending(true)
      const response = await fetch(`${API_BASE}/prospective`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ base_file_path: selectedHero.base_file_path, hypothesis }),
      })
      if (!response.ok) throw new Error(`Prospective request failed (${response.status}).`)
      const { changeId: prospectiveChangeId } = await response.json() as { changeId: string }
      setChangeId(prospectiveChangeId)
      connectToChange(prospectiveChangeId)
    } catch (reason) {
      setProspectivePending(false)
      setError(reason instanceof Error ? reason.message : 'Could not start prospective analysis.')
    }
  }, [connectToChange, hypothesis, selectedHero])

  return (
    <main className="min-h-screen bg-[var(--lever-background)] px-6 py-6 text-[var(--lever-text)]">
      <div className="mx-auto max-w-6xl space-y-6">
        <nav aria-label="Select hero" className="flex gap-2 p-3">
          {HEROES.map((hero) => (
            <button
              key={hero.id}
              type="button"
              aria-pressed={hero.id === selectedHeroId}
              onClick={() => setSelectedHeroId(hero.id)}
              className="rounded-md border border-[var(--lever-text)]/30 px-3 py-1.5 text-sm aria-pressed:border-[var(--lever-primary)] aria-pressed:bg-[var(--lever-primary)] aria-pressed:text-[var(--lever-surface)]"
            >
              {hero.label}
            </button>
          ))}
        </nav>
        <header className="space-y-2">
          <p className="text-sm font-medium text-[var(--lever-primary)]">Lever / {selectedHero.label}</p>
          <h1 className="text-3xl font-semibold">Pull on the behavioral difference</h1>
          <p className="max-w-3xl text-[var(--lever-text)]">
            {degradation
              ? 'Lever stopped before rendering a toy.'
              : widget?.thesis ?? (prospectivePending
                ? 'Generating one executable candidate from unwritten code…'
                : 'Preparing the verified comparison…')}
          </p>
          <form onSubmit={(event) => void submitProspective(event)} className="max-w-3xl rounded-lg border border-blue-700/30 bg-blue-50 p-3 text-slate-900">
            <label htmlFor="prospective-hypothesis" className="block text-sm font-semibold">Prospective hypothesis</label>
            <p className="mt-1 text-xs">Generate one executable candidate from unwritten code, then compare it with current behavior.</p>
            <div className="mt-2 flex gap-2">
              <input
                id="prospective-hypothesis"
                aria-label="Prospective hypothesis"
                value={hypothesis}
                onChange={(event) => setHypothesis(event.target.value)}
                placeholder="What if the burst allowance were per-tenant instead of shared?"
                className="min-w-0 flex-1 rounded border border-blue-700/40 bg-white px-3 py-2 text-sm"
              />
              <button type="submit" disabled={!hypothesis.trim()} className="rounded bg-blue-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">Generate candidate</button>
            </div>
          </form>
        </header>

        <ol aria-label="Analysis progress" className="space-y-1 text-sm text-[var(--lever-text)]">
          {progress.map((event) => <li key={event.stage}>{event.message}</li>)}
        </ol>

        {error ? <p role="alert" className="text-sm text-[var(--lever-warning)]">{error}</p> : null}

        {degradation ? <DegradationPanel event={degradation} /> : null}

        {!degradation && searchTrace.length > 0 ? (
          <SearchTrace
            points={searchTrace}
            controls={widget?.controls ?? []}
            onSelectPosition={selectSearchPosition}
          />
        ) : null}

        {!degradation && widget && (unionTree !== null || (chart && values)) ? (
          <section className="grid gap-8 lg:grid-cols-[18rem_minmax(0,1fr)]">
            <div className="space-y-4">
              <KnobPanel controls={widget.controls} />
              <ObjectiveSelector
                controls={widget.controls}
                observableId={chart?.observableId ?? unionTree?.observableId ?? 'result'}
                disabled={objectiveLoading}
                onRun={runObjective}
              />
            </div>
            <div className="space-y-3">
              <p className="text-sm text-[var(--lever-text)]" aria-live="polite">{status}</p>
              {unionTree ? (
                <UnionTree tree={unionTree} />
              ) : chart && values ? (
                <MicroworldCanvas
                  widget={widget}
                  title={chart.label}
                  divergence={values.divergence}
                  data={[{ x: 'Current position', base: values.base, head: values.head }]}
                  onPointClick={openResponsibleLine}
                  controls={widget.controls}
                  basePosition={position}
                  onCellsNeeded={evaluateManyPositions}
                  currentObservation={observations}
                />
              ) : null}
              {attributionMessage ? <p role="status" className="text-sm text-[var(--lever-text)]">{attributionMessage}</p> : null}
              <p aria-live="polite" className="text-base font-medium text-[var(--lever-text)]">
                {caption ?? widget.surpriseMarker?.caption ?? 'Choose a cached position to inspect it.'}
              </p>
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => void pinCurrentPosition()}
                  disabled={!hasCurrentObservation || pinStatus === 'Writing regression test…'}
                  className="rounded-md border border-[var(--lever-primary)] px-3 py-2 text-sm font-medium text-[var(--lever-text)] enabled:hover:bg-[var(--lever-surface)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Pin this
                </button>
                {pinStatus ? <p role="status" className="text-sm text-[var(--lever-text)]">{pinStatus}</p> : null}
              </div>
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
      </div>
    </main>
  )
}

export default App
