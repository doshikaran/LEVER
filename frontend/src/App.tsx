import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { MicroworldCanvas } from './components/MicroworldCanvas'
import { KnobPanel } from './components/KnobPanel'
import { DegradationPanel } from './components/DegradationPanel'
import { SourceViewer } from './components/SourceViewer'
import { UnionTree } from './components/UnionTree'
import { SearchTrace } from './components/SearchTrace'
import { ObjectiveSelector } from './components/ObjectiveSelector'
import { PrIntake, type DemoInfo } from './components/PrIntake'
import { SessionLedger, type SessionRow } from './components/SessionLedger'
import { ReceiptPanel } from './components/ReceiptPanel'
import { ComposedMicroworld } from './components/ComposedMicroworld'
import { useMicroworldStore } from './store/useMicroworldStore'
import type {
  CompleteEvent,
  ComposedWidgetConfig,
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
  WorldSpec,
} from './types'

const API_BASE = import.meta.env.VITE_LEVER_API_BASE ?? 'http://127.0.0.1:8765'
const DRAG_SETTLE_MS = 120

type PendingRequest = Readonly<{ key: string; version: number; position: KnobPosition }>

const FALLBACK_WORLD: WorldSpec = {
  genre: 'numeric-response',
  stage: { kind: 'curve', layout: 'stacked' },
  affordances: ['evidence-chart', 'scrubber'],
  narrationLine: '',
  playHints: [],
}

function socketBase(apiBase: string) {
  const url = new URL(apiBase)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString().replace(/\/$/, '')
}

function permalinkPath(changeId: string) {
  return `/m/${changeId}`
}

function changeIdFromPath(pathname: string) {
  const match = pathname.match(/^\/m\/([^/]+)\/?$/)
  return match?.[1] ?? null
}

function withWorldSpec(widget: WidgetConfig): WidgetConfig {
  if (widget.worldSpec !== undefined && widget.worldSpec !== null) {
    return widget
  }
  return {
    ...widget,
    worldSpec: {
      ...FALLBACK_WORLD,
      narrationLine: widget.surpriseMarker?.caption ?? widget.thesis,
    },
  }
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
  const rawBase = observations?.base[observableId]
  const rawHead = observations?.head[observableId]
  if (typeof rawBase === 'string' || typeof rawHead === 'string') {
    const base = String(rawBase ?? '')
    const head = String(rawHead ?? '')
    return {
      base: base as unknown as number,
      head: head as unknown as number,
      divergence: base === head ? 0 : 1,
      baseLabel: base,
      headLabel: head,
    }
  }
  const base = Number(rawBase ?? 0)
  const head = Number(rawHead ?? 0)
  return {
    base,
    head,
    divergence: head === base ? 0 : Math.abs(head - base) / Math.max(Math.abs(head), Math.abs(base), 1),
    baseLabel: String(base),
    headLabel: String(head),
  }
}

function observationCaption(observations: ObservationBundle | null, observableId: string) {
  if (observations === null) return null
  const values = chartValues(observations, observableId)
  if (typeof observations.base[observableId] === 'string' || typeof observations.head[observableId] === 'string') {
    return `Base state: ${values.baseLabel}; Head state: ${values.headLabel}.`
  }
  const { base, head } = values
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
  const [bossCelebrate, setBossCelebrate] = useState(false)
  const [hypothesis, setHypothesis] = useState('')
  const [prospectivePending, setProspectivePending] = useState(false)
  const [prUrl, setPrUrl] = useState('')
  const [demos, setDemos] = useState<DemoInfo[]>([])
  const [sessions, setSessions] = useState<SessionRow[]>([])
  const [intakePending, setIntakePending] = useState(false)
  const [activeDemoId, setActiveDemoId] = useState<string | null>(null)
  const [shareStatus, setShareStatus] = useState<string | null>(null)
  const [receiptOpen, setReceiptOpen] = useState(false)
  const [permalinkLoading, setPermalinkLoading] = useState(false)
  const [composed, setComposed] = useState<ComposedWidgetConfig | null>(null)
  const socket = useRef<WebSocket | null>(null)
  const pendingRequests = useRef(new Map<string, PendingRequest>())
  const positionVersion = useRef(0)
  const dragSettleTimer = useRef<number | undefined>(undefined)
  const selectedTracePosition = useRef<KnobPosition | null>(null)
  const permalinkBootstrapped = useRef(false)

  const refreshSessions = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/sessions`)
      if (!response.ok) return
      const rows = await response.json() as SessionRow[]
      setSessions(rows)
    } catch {
      // Ledger is optional if the API is mid-boot.
    }
  }, [])

  const applyCompletePayload = useCallback((complete: CompleteEvent) => {
    const nextWidget = withWorldSpec(complete.widgetConfig)
    replaceCache(new Map(Object.entries(complete.positionCache)))
    replacePosition(selectedTracePosition.current ?? nextWidget.initialPosition)
    setDegradation(null)
    setWidget(nextWidget)
    setChangeId(complete.changeId)
    setSourceFiles(complete.sourceFiles)
    setObservedPosition(null)
    setSelectedLine(null)
    setAttributionMessage(null)
    setPinStatus(null)
    setEvaluationSource(null)
    setObjectiveLoading(false)
    setObjectiveFinding(null)
    setBossCelebrate(false)
    setProspectivePending(false)
    setReceiptOpen(false)
    window.history.replaceState({}, '', permalinkPath(complete.changeId))
  }, [replaceCache, replacePosition])

  const applyDegradationPayload = useCallback((event: DegradationEvent) => {
    setDegradation(event)
    setWidget(null)
    setChangeId(event.changeId)
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
    setBossCelebrate(false)
    setProspectivePending(false)
    setReceiptOpen(false)
    window.history.replaceState({}, '', permalinkPath(event.changeId))
  }, [replaceCache, replacePosition])

  const evaluatePosition = useCallback(async (nextPosition: KnobPosition, version: number) => {
    setSelectedLine(null)
    setAttributionMessage(null)
    setPinStatus(null)
    const key = await hashPosition(nextPosition)
    if (version !== positionVersion.current) return

    const cacheHit = useMicroworldStore.getState().cache.get(key)
    if (cacheHit) {
      setObservations(cacheHit)
      setObservedPosition({ ...nextPosition })
      setEvaluationSource('cache')
      setLoadingKey(null)
      return
    }

    if (socket.current?.readyState !== WebSocket.OPEN) {
      setError('The evaluation connection is not ready.')
      return
    }
    const requestId = crypto.randomUUID()
    pendingRequests.current.set(requestId, { key, version, position: { ...nextPosition } })
    setLoadingKey(key)
    socket.current.send(JSON.stringify({ type: 'evaluate', requestId, position: nextPosition }))
  }, [])

  const connectToChange = useCallback((nextChangeId: string) => {
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
        applyCompletePayload(event as CompleteEvent)
        void refreshSessions()
        return
      }
      if (isDegradationEvent(event)) {
        applyDegradationPayload(event)
        void refreshSessions()
        return
      }
      if (event.type === 'evaluation') {
        const evaluation = event as EvaluationEvent
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
        pendingRequests.current.delete(failed.requestId ?? '')
        setLoadingKey(null)
        setError(failed.error ?? 'Position evaluation failed.')
        return
      }
      if (event.type === 'objective_started') {
        setSearchTrace([])
        setObjectiveLoading(true)
        setObjectiveFinding(null)
        setBossCelebrate(false)
        return
      }
      if (event.type === 'objective_result') {
        const result = event as ObjectiveResultEvent
        replaceCache(new Map(Object.entries(result.positionCache)))
        setObjectiveLoading(false)
        if (result.surpriseMarker !== null && !result.noUnsafeState) {
          selectedTracePosition.current = { ...result.surpriseMarker.position }
          replacePosition(result.surpriseMarker.position)
          setObjectiveFinding(result.surpriseMarker.caption)
          setBossCelebrate(result.objective === 'reach_unsafe_state')
        } else if (result.surpriseMarker !== null) {
          selectedTracePosition.current = { ...result.surpriseMarker.position }
          replacePosition(result.surpriseMarker.position)
          setObjectiveFinding(result.surpriseMarker.caption)
          setBossCelebrate(false)
        } else {
          setObjectiveFinding(result.reason ?? 'No unsafe state was reached.')
          setBossCelebrate(false)
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
  }, [applyCompletePayload, applyDegradationPayload, putCachedObservation, refreshSessions, replaceCache, replacePosition])

  const resetForNewRun = useCallback(() => {
    setError(null)
    setProgress([])
    setSearchTrace([])
    setWidget(null)
    setDegradation(null)
    setObservations(null)
    setObservedPosition(null)
    setEvaluationSource(null)
    setObjectiveFinding(null)
    setBossCelebrate(false)
    setSelectedLine(null)
    setAttributionMessage(null)
    setPinStatus(null)
    setShareStatus(null)
    setReceiptOpen(false)
    setProspectivePending(false)
    setComposed(null)
    selectedTracePosition.current = null
    replacePosition({})
    replaceCache(new Map())
  }, [replaceCache, replacePosition])

  const beginChange = useCallback(async (path: string, body?: Record<string, unknown>) => {
    resetForNewRun()
    setIntakePending(true)
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
      const payload = await response.json() as { changeId?: string; detail?: string }
      if (!response.ok || payload.changeId === undefined) {
        throw new Error(
          typeof payload.detail === 'string'
            ? payload.detail
            : `Intake failed (${response.status}).`,
        )
      }
      setChangeId(payload.changeId)
      window.history.replaceState({}, '', permalinkPath(payload.changeId))
      connectToChange(payload.changeId)
    } catch (reason) {
      setIntakePending(false)
      setError(reason instanceof Error ? reason.message : 'Could not start Lever.')
    }
  }, [connectToChange, resetForNewRun])

  const loadPermalink = useCallback(async (nextChangeId: string) => {
    setPermalinkLoading(true)
    setError(null)
    setIntakePending(false)
    try {
      const response = await fetch(`${API_BASE}/diffs/${nextChangeId}`)
      if (!response.ok) {
        throw new Error(response.status === 404 ? 'Unknown microworld permalink.' : `Load failed (${response.status}).`)
      }
      const payload = await response.json() as CompleteEvent | DegradationEvent | { type?: string }
      if (payload.type === 'complete') {
        selectedTracePosition.current = null
        applyCompletePayload(payload as CompleteEvent)
        connectToChange(nextChangeId)
      } else if (isDegradationEvent(payload)) {
        applyDegradationPayload(payload)
      } else {
        throw new Error('Persisted session has no interactive payload.')
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not open permalink.')
    } finally {
      setPermalinkLoading(false)
    }
  }, [applyCompletePayload, applyDegradationPayload, connectToChange])

  useEffect(() => {
    const controller = new AbortController()
    void fetch(`${API_BASE}/demos`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Demo catalog failed (${response.status}).`)
        return response.json() as Promise<DemoInfo[]>
      })
      .then((catalog) => {
        setDemos(catalog)
      })
      .catch(() => {
        // Demo chips are optional; PR paste still works if the catalog is down.
      })
    void refreshSessions()
    return () => controller.abort()
  }, [refreshSessions])

  useEffect(() => {
    if (permalinkBootstrapped.current) return
    permalinkBootstrapped.current = true
    const routed = changeIdFromPath(window.location.pathname)
    if (routed !== null) {
      void loadPermalink(routed)
    }
  }, [loadPermalink])

  useEffect(() => {
    if (widget !== null || degradation !== null) {
      setIntakePending(false)
    }
  }, [degradation, widget])

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
    if (permalinkLoading) return 'Opening shared microworld…'
    if (objectiveLoading) return 'Searching boundary-weighted adversarial inputs…'
    if (loadingKey) return 'Evaluating this position…'
    if (evaluationSource === 'fresh') {
      return `Fresh microworld evaluation — not individually ground-truth verified; overall microworld confidence: ${widget?.fidelityBand ?? 'unknown'} (${Math.round((widget?.fidelityConfidence ?? 0) * 100)}%).`
    }
    if (evaluationSource === 'cache') return 'Cache hit — no network call'
    if (widget) return 'Verified position'
    if (degradation) return 'Analysis stopped before rendering a toy.'
    return 'Preparing analysis…'
  }, [degradation, evaluationSource, loadingKey, objectiveLoading, permalinkLoading, widget])

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

  const sharePermalink = useCallback(async () => {
    if (changeId === null) {
      setShareStatus('Nothing to share yet.')
      return
    }
    const absolute = `${window.location.origin}${permalinkPath(changeId)}`
    window.history.replaceState({}, '', permalinkPath(changeId))
    try {
      await navigator.clipboard.writeText(absolute)
      setShareStatus('Permalink copied.')
    } catch {
      setShareStatus(absolute)
    }
  }, [changeId])

  const selectSearchPosition = useCallback((nextPosition: KnobPosition) => {
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

  const submitPullRequest = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!prUrl.trim()) return
    setActiveDemoId(null)
    await beginChange('/prs', { url: prUrl.trim() })
  }, [beginChange, prUrl])

  const runDemo = useCallback(async (demoId: string) => {
    setActiveDemoId(demoId)
    setPrUrl('')
    if (demoId === 'compose-hero1') {
      resetForNewRun()
      setIntakePending(true)
      try {
        const response = await fetch(`${API_BASE}/compose/demos/hero1`)
        if (!response.ok) throw new Error(`Compose demo failed (${response.status}).`)
        const payload = await response.json() as {
          composedWidgetConfig: ComposedWidgetConfig
        }
        setComposed(payload.composedWidgetConfig)
        setChangeId('compose-hero1')
        setIntakePending(false)
      } catch (reason) {
        setIntakePending(false)
        setError(reason instanceof Error ? reason.message : 'Could not load composed demo.')
      }
      return
    }
    await beginChange(`/demos/${demoId}/run`)
  }, [beginChange, resetForNewRun])

  const openSession = useCallback((nextChangeId: string) => {
    void loadPermalink(nextChangeId)
  }, [loadPermalink])

  const submitProspective = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!hypothesis.trim()) return
    const basePath = sourceFiles.base?.path
    if (basePath === undefined) {
      setError('Run a demo or PR first so Lever has a base module to mutate.')
      return
    }
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
      setBossCelebrate(false)
      setProspectivePending(true)
      setIntakePending(true)
      const response = await fetch(`${API_BASE}/prospective`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ base_file_path: basePath, hypothesis }),
      })
      if (!response.ok) throw new Error(`Prospective request failed (${response.status}).`)
      const { changeId: prospectiveChangeId } = await response.json() as { changeId: string }
      setChangeId(prospectiveChangeId)
      window.history.replaceState({}, '', permalinkPath(prospectiveChangeId))
      connectToChange(prospectiveChangeId)
    } catch (reason) {
      setProspectivePending(false)
      setIntakePending(false)
      setError(reason instanceof Error ? reason.message : 'Could not start prospective analysis.')
    }
  }, [connectToChange, hypothesis, sourceFiles.base?.path])

  return (
    <main className="min-h-screen px-4 py-8 text-[var(--lever-text)] sm:px-6">
      <div className="mx-auto grid max-w-6xl gap-8 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="space-y-7">
          <header className="space-y-5">
            <PrIntake
              prUrl={prUrl}
              onPrUrlChange={setPrUrl}
              onSubmitPr={(event) => void submitPullRequest(event)}
              demos={demos}
              activeDemoId={activeDemoId}
              onRunDemo={(demoId) => void runDemo(demoId)}
              intakePending={intakePending || permalinkLoading}
            />
            <form
              onSubmit={(event) => void submitProspective(event)}
              className="lever-panel animate-rise max-w-3xl rounded-2xl border border-sky-200/80 bg-gradient-to-br from-sky-50 to-white p-4 text-[var(--lever-text)]"
            >
              <label htmlFor="prospective-hypothesis" className="font-display block text-base font-bold">
                Prospective hypothesis
              </label>
              <p className="mt-1 text-sm text-[var(--lever-muted)]">
                Generate one executable candidate from unwritten code, then compare it with the current base module from the active run.
              </p>
              <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                <input
                  id="prospective-hypothesis"
                  aria-label="Prospective hypothesis"
                  value={hypothesis}
                  onChange={(event) => setHypothesis(event.target.value)}
                  placeholder="What if the burst allowance were per-tenant instead of shared?"
                  className="lever-input min-w-0 flex-1 rounded-xl border border-sky-200 bg-white px-4 py-2.5 text-sm"
                />
                <button
                  type="submit"
                  disabled={!hypothesis.trim() || sourceFiles.base === undefined}
                  className="lever-btn rounded-xl bg-[var(--lever-secondary)] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
                >
                  Generate candidate
                </button>
              </div>
            </form>
            <p className="animate-fade max-w-3xl text-base leading-relaxed text-[var(--lever-muted)]">
              {degradation
                ? 'Lever stopped before rendering a toy.'
                : widget?.thesis ?? (intakePending || prospectivePending || permalinkLoading
                  ? 'Reading the change and preparing analysis…'
                  : 'Waiting for a pull request URL or demo selection.')}
            </p>
          </header>

          <ol aria-label="Analysis progress" className="space-y-2 text-sm text-[var(--lever-muted)]">
            {progress.map((event, index) => (
              <li
                key={`${event.stage}-${index}`}
                className="progress-item flex items-center gap-2"
                style={{ animationDelay: `${index * 40}ms` }}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--lever-primary)]" />
                {event.message}
              </li>
            ))}
          </ol>

          {intakePending && progress.length === 0 && !permalinkLoading ? (
            <div className="lever-panel relative overflow-hidden rounded-2xl p-4" aria-live="polite">
              <div className="lever-shimmer absolute inset-0 opacity-60" />
              <p className="relative font-display text-sm font-semibold text-[var(--lever-primary)]">
                Computing the verified world…
              </p>
            </div>
          ) : null}

          {error ? <p role="alert" className="animate-rise text-sm font-medium text-[var(--lever-warning)]">{error}</p> : null}

          {composed ? (
            <div className="animate-rise max-w-3xl">
              <ComposedMicroworld config={composed} />
            </div>
          ) : null}

          {degradation ? <DegradationPanel event={degradation} /> : null}

          {!degradation && searchTrace.length > 0 ? (
            <div className="animate-rise">
              <SearchTrace
                points={searchTrace}
                controls={widget?.controls ?? []}
                onSelectPosition={selectSearchPosition}
              />
            </div>
          ) : null}

          {!degradation && widget && (unionTree !== null || (chart && values)) ? (
            <section className="animate-rise grid gap-8 lg:grid-cols-[18rem_minmax(0,1fr)]">
              <div className="space-y-4">
                <KnobPanel controls={widget.controls} />
                <ObjectiveSelector
                  controls={widget.controls}
                  observableId={chart?.observableId ?? unionTree?.observableId ?? 'result'}
                  disabled={objectiveLoading}
                  onRun={runObjective}
                />
              </div>
              <div className="space-y-4">
                <p className="text-sm text-[var(--lever-muted)]" aria-live="polite">{status}</p>
                {bossCelebrate ? (
                  <p
                    role="status"
                    data-testid="boss-celebrate"
                    className="boss-celebrate rounded-2xl border border-[var(--lever-warning)] bg-orange-50 px-4 py-3 text-sm font-semibold text-[var(--lever-warning)]"
                  >
                    Unsafe state found empirically — not a model guess.
                  </p>
                ) : null}
                {unionTree ? (
                  <UnionTree tree={unionTree} />
                ) : chart && values ? (
                  <MicroworldCanvas
                    widget={widget}
                    title={chart.label}
                    divergence={values.divergence}
                    baseValue={values.base}
                    headValue={values.head}
                    data={[{ x: 'Current position', base: values.base, head: values.head }]}
                    onPointClick={openResponsibleLine}
                  />
                ) : null}
                {attributionMessage ? <p role="status" className="text-sm text-[var(--lever-muted)]">{attributionMessage}</p> : null}
                <p aria-live="polite" className="font-display text-lg font-semibold text-[var(--lever-text)]">
                  {caption ?? widget.surpriseMarker?.caption ?? widget.worldSpec.narrationLine ?? 'Choose a cached position to inspect it.'}
                </p>
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={() => void pinCurrentPosition()}
                    disabled={!hasCurrentObservation || pinStatus === 'Writing regression test…'}
                    className="lever-btn rounded-xl border border-[var(--lever-primary)] px-4 py-2.5 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Pin this
                  </button>
                  <button
                    type="button"
                    data-testid="share-permalink"
                    onClick={() => void sharePermalink()}
                    className="lever-btn rounded-xl border border-[var(--lever-secondary)] px-4 py-2.5 text-sm font-semibold text-[var(--lever-secondary)]"
                  >
                    Share
                  </button>
                  <button
                    type="button"
                    data-testid="show-receipt"
                    onClick={() => setReceiptOpen((open) => !open)}
                    className="lever-btn rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold"
                  >
                    {receiptOpen ? 'Hide receipt' : 'Show receipt'}
                  </button>
                  {pinStatus ? <p role="status" className="text-sm text-[var(--lever-muted)]">{pinStatus}</p> : null}
                  {shareStatus ? <p role="status" className="text-sm text-[var(--lever-muted)]">{shareStatus}</p> : null}
                </div>
                {changeId !== null ? (
                  <ReceiptPanel
                    changeId={changeId}
                    widget={widget}
                    open={receiptOpen}
                    onClose={() => setReceiptOpen(false)}
                  />
                ) : null}
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

          {!degradation && changeId !== null && widget === null && searchTrace.length === 0 && !error ? (
            <p className="text-sm text-[var(--lever-muted)]" aria-live="polite">
              {intakePending || permalinkLoading
                ? 'Search fog appears as soon as the Adversary starts probing.'
                : null}
            </p>
          ) : null}
        </div>

        <aside className="animate-rise-delay-2 space-y-4 lg:sticky lg:top-6 lg:self-start">
          <SessionLedger
            sessions={sessions}
            activeChangeId={changeId}
            onOpen={openSession}
          />
        </aside>
      </div>
    </main>
  )
}

export default App
