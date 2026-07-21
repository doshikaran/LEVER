import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { MicroworldCanvas } from './components/MicroworldCanvas'
import { CodeDiff } from './components/CodeDiff'
import { GenreSimulation } from './components/GenreSimulation'
import { TimelineScrubber } from './components/TimelineScrubber'
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
import { ChallengePanel } from './components/ChallengePanel'
import { TradingCard } from './components/TradingCard'
import { ReceiptDuel, type DuelFrame, type DuelSide } from './components/ReceiptDuel'
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

function asBranchDecisions(value: unknown): { tag: string; outcome: boolean }[] | null {
  if (!Array.isArray(value)) return null
  const out: { tag: string; outcome: boolean }[] = []
  for (const entry of value) {
    if (
      entry !== null
      && typeof entry === 'object'
      && typeof (entry as { tag?: unknown }).tag === 'string'
      && typeof (entry as { outcome?: unknown }).outcome === 'boolean'
    ) {
      out.push({ tag: (entry as { tag: string }).tag, outcome: (entry as { outcome: boolean }).outcome })
    }
  }
  return out
}

function pathFingerprint(path: readonly { tag: string; outcome: boolean }[]) {
  return path.map((step) => `${step.tag}:${step.outcome ? 'T' : 'F'}`).join(' → ')
}

function pathHamming(base: readonly { tag: string; outcome: boolean }[], head: readonly { tag: string; outcome: boolean }[]) {
  const width = Math.max(base.length, head.length)
  if (width === 0) return 0
  let mismatches = 0
  for (let index = 0; index < width; index += 1) {
    const left = base[index]
    const right = head[index]
    if (left === undefined || right === undefined || left.tag !== right.tag || left.outcome !== right.outcome) {
      mismatches += 1
    }
  }
  return mismatches / width
}

function chartValues(observations: ObservationBundle | null, observableId: string) {
  const rawBase = observations?.base[observableId]
  const rawHead = observations?.head[observableId]

  const basePath = asBranchDecisions(rawBase)
  const headPath = asBranchDecisions(rawHead)
  if (basePath !== null || headPath !== null) {
    const base = basePath ?? []
    const head = headPath ?? []
    const divergence = pathHamming(base, head)
    return {
      base: base.length,
      head: head.length,
      divergence,
      baseLabel: base.length === 0 ? 'idle' : `${base.length} step${base.length === 1 ? '' : 's'}`,
      headLabel: head.length === 0 ? 'idle' : `${head.length} step${head.length === 1 ? '' : 's'}`,
    }
  }

  if (typeof rawBase === 'boolean' || typeof rawHead === 'boolean') {
    const base = rawBase === true ? 1 : 0
    const head = rawHead === true ? 1 : 0
    return {
      base,
      head,
      divergence: base === head ? 0 : 1,
      baseLabel: rawBase === true ? 'allow' : rawBase === false ? 'deny' : String(rawBase ?? '—'),
      headLabel: rawHead === true ? 'allow' : rawHead === false ? 'deny' : String(rawHead ?? '—'),
    }
  }

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

  if (rawBase !== null && typeof rawBase === 'object') {
    const baseText = JSON.stringify(rawBase)
    const headText = JSON.stringify(rawHead ?? null)
    return {
      base: 0,
      head: 0,
      divergence: baseText === headText ? 0 : 1,
      baseLabel: 'structured',
      headLabel: 'structured',
    }
  }

  const base = Number(rawBase ?? 0)
  const head = Number(rawHead ?? 0)
  const finite = Number.isFinite(base) && Number.isFinite(head)
  return {
    base: finite ? base : 0,
    head: finite ? head : 0,
    divergence: !finite
      ? 0
      : head === base
        ? 0
        : Math.abs(head - base) / Math.max(Math.abs(head), Math.abs(base), 1),
    baseLabel: finite ? String(base) : '—',
    headLabel: finite ? String(head) : '—',
  }
}

function observationCaption(observations: ObservationBundle | null, observableId: string) {
  if (observations === null) return null
  const rawBase = observations.base[observableId]
  const rawHead = observations.head[observableId]
  const basePath = asBranchDecisions(rawBase)
  const headPath = asBranchDecisions(rawHead)
  if (basePath !== null || headPath !== null) {
    const base = basePath ?? []
    const head = headPath ?? []
    if (pathHamming(base, head) === 0) {
      return `Shared path: ${pathFingerprint(base) || 'idle'}.`
    }
    return `Old: ${pathFingerprint(base) || 'idle'} · New: ${pathFingerprint(head) || 'idle'}.`
  }
  const values = chartValues(observations, observableId)
  if (typeof rawBase === 'boolean' || typeof rawHead === 'boolean') {
    return `Old: ${values.baseLabel}; New: ${values.headLabel}.`
  }
  if (typeof rawBase === 'string' || typeof rawHead === 'string') {
    return `Base state: ${values.baseLabel}; Head state: ${values.headLabel}.`
  }
  const { base, head } = values
  if (base <= 0 || head < 0) return `Base: ${base}; Head: ${head}.`
  return `Head admits ${(head / base).toFixed(1)}× as many requests (${head} vs ${base}).`
}

function isDegradationEvent(event: { type?: unknown }): event is DegradationEvent {
  return ['skipped', 'unscopable', 'inert', 'degraded'].includes(String(event.type))
}

/** Build a read-only duel side from a verified session's widget + measured cache. */
function buildDuelSide(
  changeId: string,
  widget: WidgetConfig,
  sourceFiles: SourceFiles,
  positionCache: Map<string, ObservationBundle>,
): DuelSide {
  const observableId = widget.charts[0]?.observableId ?? widget.unionTree?.observableId ?? 'result'
  const observableLabel = widget.charts[0]?.label ?? widget.unionTree?.label ?? 'Outcome'
  const unit = widget.charts[0]?.unit ?? null
  const seen = new Set<string>()
  const frames: DuelFrame[] = []
  let maxDivergence = 0
  for (const observation of positionCache.values()) {
    if (observation.position === undefined) continue
    const key = canonicalPosition(observation.position)
    if (seen.has(key)) continue
    seen.add(key)
    const values = chartValues(observation, observableId)
    frames.push({
      baseLabel: String(values.baseLabel),
      headLabel: String(values.headLabel),
      divergence: values.divergence,
      diverges: values.divergence > 0,
      caption: observationCaption(observation, observableId),
    })
    maxDivergence = Math.max(maxDivergence, values.divergence)
  }
  maxDivergence = Math.max(maxDivergence, widget.surpriseMarker?.divergence ?? 0)
  return {
    changeId,
    thesis: widget.thesis,
    domainPack: widget.domainPack,
    fidelityBand: widget.fidelityBand,
    fidelityConfidence: widget.fidelityConfidence,
    observableLabel,
    unit,
    base: sourceFiles.base,
    head: sourceFiles.head,
    frames,
    maxDivergence,
  }
}

function App() {
  const position = useMicroworldStore((state) => state.position)
  const cache = useMicroworldStore((state) => state.cache)
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
  const [detailedOpen, setDetailedOpen] = useState(false)
  const [isPlaying, setIsPlaying] = useState(false)
  const [showSim, setShowSim] = useState(false)
  const [permalinkLoading, setPermalinkLoading] = useState(false)
  const [challengeMode, setChallengeMode] = useState(false)
  const [userBest, setUserBest] = useState(0)
  const [cardOpen, setCardOpen] = useState(false)
  const [duel, setDuel] = useState<{ left: DuelSide; right: DuelSide } | null>(null)
  const [duelPending, setDuelPending] = useState(false)
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
    setChallengeMode(false)
    setUserBest(0)
    setCardOpen(false)
    surpriseBootstrapped.current = null
    selectedTracePosition.current = null
    replacePosition({})
    replaceCache(new Map())
  }, [replaceCache, replacePosition])

  const backToIntake = useCallback(() => {
    setIsPlaying(false)
    setDetailedOpen(false)
    setActiveDemoId(null)
    setShowSim(false)
    resetForNewRun()
    setChangeId(null)
    window.history.replaceState({}, '', '/')
  }, [resetForNewRun])

  const beginChange = useCallback(async (path: string, body?: Record<string, unknown>) => {
    resetForNewRun()
    setShowSim(true)
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
    setShowSim(true)
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
  const simValues = values ?? (unionTree ? chartValues(observations, unionTree.observableId) : null)
  const simObservableLabel = chart?.label ?? unionTree?.label ?? 'Result'
  const observableId = chart?.observableId ?? unionTree?.observableId ?? 'result'
  const caption = objectiveFinding
    ?? observationCaption(observations, observableId)
    ?? null

  // Each measured input becomes one "frame" in the replay timeline, tagged with
  // how much the two versions diverge on it so the scrubber can color it.
  const stepFrames = useMemo(() => {
    const seen = new Set<string>()
    const out: { position: KnobPosition; divergence: number; observation: ObservationBundle }[] = []
    for (const observation of cache.values()) {
      if (observation.position === undefined) continue
      const key = canonicalPosition(observation.position)
      if (seen.has(key)) continue
      seen.add(key)
      out.push({
        position: observation.position,
        divergence: chartValues(observation, observableId).divergence,
        observation,
      })
    }
    return out
  }, [cache, observableId])
  const steps = useMemo(
    () => stepFrames.map((frame) => ({ position: frame.position, divergence: frame.divergence })),
    [stepFrames],
  )
  const measuredPositions = useMemo(() => steps.map((step) => step.position), [steps])

  const surpriseIndex = useMemo(() => {
    const surprise = widget?.surpriseMarker?.position
    if (surprise === undefined) return -1
    const key = canonicalPosition(surprise)
    return steps.findIndex((step) => canonicalPosition(step.position) === key)
  }, [steps, widget?.surpriseMarker?.position])

  const currentStepIndex = useMemo(() => {
    const key = canonicalPosition(position)
    return steps.findIndex((step) => canonicalPosition(step.position) === key)
  }, [steps, position])

  // The largest divergence Lever actually measured — the score to beat in challenge mode.
  const leverBest = useMemo(() => {
    const stepsMax = steps.reduce((max, step) => Math.max(max, step.divergence), 0)
    return Math.max(stepsMax, widget?.surpriseMarker?.divergence ?? 0)
  }, [steps, widget?.surpriseMarker?.divergence])

  // Break the PR: hide Lever's answer while the challenge is active.
  const effectiveSurpriseIndex = challengeMode ? -1 : surpriseIndex

  const seekStep = useCallback(
    (index: number) => {
      if (index < 0 || index >= steps.length) return
      setIsPlaying(false)
      replacePosition(steps[index].position)
    },
    [steps, replacePosition],
  )

  // Land on the surprise frame once the measured cache arrives — judges see the climax first.
  const surpriseBootstrapped = useRef<string | null>(null)
  useEffect(() => {
    if (widget === null || surpriseIndex < 0) return
    if (challengeMode) return
    if (surpriseBootstrapped.current === widget.thesis) return
    surpriseBootstrapped.current = widget.thesis
    seekStep(surpriseIndex)
  }, [widget, surpriseIndex, seekStep, challengeMode])

  // Break the PR: record the biggest divergence the player has stumbled onto.
  useEffect(() => {
    if (!challengeMode) return
    const found = simValues?.divergence ?? 0
    setUserBest((best) => (found > best ? found : best))
  }, [challengeMode, simValues])

  const toggleChallenge = useCallback(() => {
    setChallengeMode((on) => {
      const next = !on
      if (next) {
        setUserBest(0)
        seekStep(0)
      }
      return next
    })
  }, [seekStep])

  const revealChallenge = useCallback(() => {
    setChallengeMode(false)
    if (surpriseIndex >= 0) seekStep(surpriseIndex)
  }, [surpriseIndex, seekStep])

  useEffect(() => {
    if (!isPlaying) return
    if (measuredPositions.length < 2) {
      setIsPlaying(false)
      return
    }
    let index = currentStepIndex >= 0 ? currentStepIndex : 0
    const timer = window.setInterval(() => {
      index = (index + 1) % measuredPositions.length
      replacePosition(measuredPositions[index])
    }, 1100)
    return () => window.clearInterval(timer)
    // currentStepIndex intentionally read once at start; excluding it keeps the
    // interval from resetting every frame it advances.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPlaying, measuredPositions, replacePosition])

  // Arrow keys / Space scrub the timeline like a game replay controller.
  useEffect(() => {
    if (!showSim || widget === null) return
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target !== null) {
        const tag = target.tagName
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable) {
          return
        }
      }
      if (event.key === 'ArrowLeft') {
        event.preventDefault()
        seekStep((currentStepIndex < 0 ? 0 : currentStepIndex) - 1)
      } else if (event.key === 'ArrowRight') {
        event.preventDefault()
        seekStep((currentStepIndex < 0 ? -1 : currentStepIndex) + 1)
      } else if (event.key === ' ' || event.key === 'Spacebar') {
        event.preventDefault()
        if (steps.length > 1) setIsPlaying((playing) => !playing)
      } else if (event.key === 's' || event.key === 'S') {
        if (!challengeMode && surpriseIndex >= 0) {
          event.preventDefault()
          seekStep(surpriseIndex)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [showSim, widget, currentStepIndex, seekStep, steps.length, surpriseIndex, challengeMode])

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

  // Time-travel review: which source lines the current frame actually executed.
  const baseExecutedLines = useMemo(
    () => new Set<number>(observations?.trace?.base.executedLines ?? []),
    [observations],
  )
  const headExecutedLines = useMemo(
    () => new Set<number>(observations?.trace?.head.executedLines ?? []),
    [observations],
  )

  // Diff-as-controller: jump to the first measured frame that executed a line.
  const jumpToLineFrame = useCallback(
    (version: 'base' | 'head', line: number) => {
      const index = stepFrames.findIndex((frame) =>
        (frame.observation.trace?.[version].executedLines ?? []).includes(line),
      )
      if (index >= 0) {
        setAttributionMessage(null)
        seekStep(index)
        return
      }
      setAttributionMessage(
        `No measured frame executed ${version} line ${line}. Try Play to widen the measured set.`,
      )
    },
    [stepFrames, seekStep],
  )

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

  const startDuel = useCallback(async (otherId: string) => {
    if (changeId === null || widget === null) {
      setError('Open a verified microworld before starting a duel.')
      return
    }
    setDuelPending(true)
    try {
      const response = await fetch(`${API_BASE}/diffs/${otherId}`)
      if (!response.ok) {
        throw new Error(response.status === 404 ? 'Unknown session to duel.' : `Load failed (${response.status}).`)
      }
      const payload = await response.json() as CompleteEvent | { type?: string }
      if (payload.type !== 'complete') {
        throw new Error('That session degraded — only verified microworlds can duel.')
      }
      const other = payload as CompleteEvent
      const otherWidget = withWorldSpec(other.widgetConfig)
      const rightCache = new Map(Object.entries(other.positionCache))
      setIsPlaying(false)
      setDuel({
        left: buildDuelSide(changeId, widget, sourceFiles, cache),
        right: buildDuelSide(other.changeId, otherWidget, other.sourceFiles, rightCache),
      })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not start the duel.')
    } finally {
      setDuelPending(false)
    }
  }, [changeId, widget, sourceFiles, cache])

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
      setShowSim(true)
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
    setShowSim(true)
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

  const diverges = simValues ? simValues.divergence > 0 : false
  const humanStep = currentStepIndex >= 0 ? currentStepIndex + 1 : null
  const noteBody =
    caption ??
    widget?.surpriseMarker?.caption ??
    (diverges
      ? 'The two versions produce different results on this input.'
      : 'Both versions behave identically on this input.')

  if (duel !== null) {
    return (
      <main className="min-h-screen px-2 py-8 text-[var(--lever-text)] sm:px-6">
        <ReceiptDuel left={duel.left} right={duel.right} onClose={() => setDuel(null)} />
      </main>
    )
  }

  if (!showSim) {
    return (
      <main className="min-h-screen px-4 py-10 text-[var(--lever-text)] sm:px-6">
        <div className="mx-auto grid max-w-6xl gap-8 lg:grid-cols-[minmax(0,1fr)_17rem]">
          <div className="space-y-8">
            <header className="animate-rise space-y-3">
              <p className="font-display text-4xl font-black tracking-tight text-[var(--lever-text)] sm:text-5xl">
                Lever
              </p>
              <p className="max-w-2xl text-lg leading-relaxed text-[var(--lever-muted)]">
                Turn a pull request into a <span className="font-semibold text-[var(--lever-text)]">playable, verified microworld</span>.
                Paste a PR or try a demo — Lever runs the old and new code on the same inputs and shows you exactly where they diverge.
              </p>
            </header>

            <PrIntake
              prUrl={prUrl}
              onPrUrlChange={setPrUrl}
              onSubmitPr={(event) => void submitPullRequest(event)}
              demos={demos}
              activeDemoId={activeDemoId}
              onRunDemo={(demoId) => void runDemo(demoId)}
              intakePending={intakePending || permalinkLoading}
            />

            {error ? (
              <p role="alert" className="animate-rise text-sm font-medium text-[var(--lever-warning)]">{error}</p>
            ) : null}
          </div>

          <aside className="animate-rise-delay-2 space-y-4 lg:sticky lg:top-6 lg:self-start">
            <SessionLedger sessions={sessions} activeChangeId={changeId} onOpen={openSession} />
          </aside>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen px-4 py-8 text-[var(--lever-text)] sm:px-6">
      <div className="mx-auto grid max-w-6xl gap-8 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="space-y-6">
          <header className="animate-rise space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <button
                type="button"
                data-testid="back-to-intake"
                onClick={backToIntake}
                className="lever-btn rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-[var(--lever-muted)]"
              >
                ← New analysis
              </button>
              {widget ? (
                <span className="lever-chip rounded-full border border-[var(--lever-primary)]/30 bg-[var(--lever-primary)]/5 px-3 py-1 text-xs font-semibold text-[var(--lever-primary)]">
                  Confidence: {widget.fidelityBand} ({Math.round((widget.fidelityConfidence ?? 0) * 100)}%)
                </span>
              ) : null}
            </div>
            <h1 className="font-display max-w-3xl text-2xl font-bold leading-snug text-[var(--lever-text)]">
              {degradation
                ? 'Lever stopped before rendering a toy.'
                : widget?.thesis ?? (intakePending || prospectivePending || permalinkLoading
                  ? 'Reading the change and preparing the simulation…'
                  : 'Preparing analysis…')}
            </h1>
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

          {!degradation && widget && simValues ? (
            <section className="animate-rise space-y-4">
              <div className="grid items-stretch gap-5 lg:grid-cols-2">
                <CodeDiff
                  base={sourceFiles.base}
                  head={sourceFiles.head}
                  baseExecutedLines={baseExecutedLines}
                  headExecutedLines={headExecutedLines}
                  responsibleLine={observations?.trace?.responsibleLine ?? null}
                  onLineClick={jumpToLineFrame}
                />
                <GenreSimulation
                  widget={widget}
                  observations={observations}
                  simValues={simValues}
                  observableLabel={simObservableLabel}
                  unit={chart?.unit ?? null}
                  position={position}
                  controls={widget.controls}
                  caption={caption ?? widget.surpriseMarker?.caption ?? null}
                  measuredCount={measuredPositions.length}
                  isPlaying={isPlaying}
                  canPlay={measuredPositions.length > 1}
                  onPlayToggle={() => setIsPlaying((playing) => !playing)}
                />
              </div>

              <TimelineScrubber
                steps={steps}
                currentIndex={currentStepIndex}
                surpriseIndex={effectiveSurpriseIndex}
                isPlaying={isPlaying}
                canPlay={steps.length > 1}
                onSeek={seekStep}
                onPrev={() => seekStep((currentStepIndex < 0 ? 0 : currentStepIndex) - 1)}
                onNext={() => seekStep((currentStepIndex < 0 ? -1 : currentStepIndex) + 1)}
                onReset={() => seekStep(0)}
                onPlayToggle={() => setIsPlaying((playing) => !playing)}
                onJumpToSurprise={
                  !challengeMode && surpriseIndex >= 0 ? () => seekStep(surpriseIndex) : undefined
                }
              />

              <ChallengePanel
                active={challengeMode}
                userBest={userBest}
                leverBest={leverBest}
                hasSurprise={surpriseIndex >= 0}
                onToggle={toggleChallenge}
                onReveal={revealChallenge}
              />

              <div
                data-testid="step-notes"
                className={`rounded-2xl border px-4 py-3 ${
                  diverges
                    ? 'border-[var(--lever-warning)]/40 bg-orange-50/60'
                    : 'border-slate-200 bg-white'
                }`}
                aria-live="polite"
              >
                <p className="font-display text-xs font-semibold uppercase tracking-wide text-[var(--lever-muted)]">
                  {humanStep ? `Notes for step ${humanStep}` : 'Notes'}
                </p>
                <p className="mt-1 text-sm text-[var(--lever-text)]">
                  {diverges ? '⚡ ' : '✓ '}
                  {noteBody}
                </p>
                <p className="mt-1 text-xs text-[var(--lever-muted)]">{status}</p>
                {attributionMessage ? (
                  <p role="status" className="mt-1 text-xs font-medium text-[var(--lever-warning)]">
                    {attributionMessage}
                  </p>
                ) : null}
                <p className="mt-1 text-[10px] uppercase tracking-wide text-[var(--lever-muted)]">
                  Keys · ← → scrub · Space play · S surprise
                </p>
              </div>

              <div className="lever-panel rounded-2xl p-4">
                <p className="mb-2 font-display text-sm font-semibold text-[var(--lever-text)]">
                  Change the input
                </p>
                <KnobPanel controls={widget.controls} />
              </div>

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
                <button
                  type="button"
                  data-testid="open-card"
                  onClick={() => setCardOpen(true)}
                  className="lever-btn rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold"
                >
                  Trading card
                </button>
                <button
                  type="button"
                  data-testid="toggle-detailed"
                  onClick={() => setDetailedOpen((open) => !open)}
                  className="lever-btn rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-[var(--lever-muted)]"
                >
                  {detailedOpen ? 'Hide detailed view' : 'Show detailed view'}
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

              <TradingCard
                open={cardOpen}
                onClose={() => setCardOpen(false)}
                widget={widget}
                changeId={changeId}
                permalink={
                  changeId !== null
                    ? `${window.location.origin}${permalinkPath(changeId)}`
                    : window.location.href
                }
                surpriseCaption={caption ?? widget.surpriseMarker?.caption ?? null}
              />

              {detailedOpen ? (
                <section className="animate-rise space-y-6 border-t border-slate-200/70 pt-6">
                  {searchTrace.length > 0 ? (
                    <SearchTrace
                      points={searchTrace}
                      controls={widget.controls}
                      onSelectPosition={selectSearchPosition}
                    />
                  ) : null}

                  <div className="grid gap-8 lg:grid-cols-[18rem_minmax(0,1fr)]">
                    <div className="space-y-4">
                      <ObjectiveSelector
                        controls={widget.controls}
                        observableId={observableId}
                        disabled={objectiveLoading}
                        onRun={runObjective}
                      />
                      <form
                        onSubmit={(event) => void submitProspective(event)}
                        className="lever-panel rounded-2xl border border-sky-200/80 bg-gradient-to-br from-sky-50 to-white p-4"
                      >
                        <label htmlFor="prospective-hypothesis" className="font-display block text-sm font-bold">
                          Prospective hypothesis
                        </label>
                        <p className="mt-1 text-xs text-[var(--lever-muted)]">
                          Generate one executable candidate from unwritten code and compare it with the current base module.
                        </p>
                        <div className="mt-3 flex flex-col gap-2">
                          <input
                            id="prospective-hypothesis"
                            aria-label="Prospective hypothesis"
                            value={hypothesis}
                            onChange={(event) => setHypothesis(event.target.value)}
                            placeholder="What if the burst allowance were per-tenant?"
                            className="lever-input min-w-0 flex-1 rounded-xl border border-sky-200 bg-white px-3 py-2 text-sm"
                          />
                          <button
                            type="submit"
                            disabled={!hypothesis.trim() || sourceFiles.base === undefined}
                            className="lever-btn rounded-xl bg-[var(--lever-secondary)] px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                          >
                            Generate candidate
                          </button>
                        </div>
                      </form>
                    </div>
                    <div className="space-y-4">
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
                      {selectedLine && selectedSourceFile ? (
                        <SourceViewer
                          responsibleLine={selectedLine}
                          sourceFile={selectedSourceFile}
                          onClose={() => setSelectedLine(null)}
                        />
                      ) : null}
                    </div>
                  </div>
                </section>
              ) : null}
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
            onDuel={(otherId) => void startDuel(otherId)}
            duelPending={duelPending}
          />
        </aside>
      </div>
    </main>
  )
}

export default App
