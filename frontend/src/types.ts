export type KnobValue = number | string | boolean | null
export type KnobPosition = Record<string, KnobValue>

export type NumericDomain = Readonly<{ min: number; max: number; step: number }>
export type EnumDomain = Readonly<{ values: readonly string[] }>

export type ControlDescriptor = Readonly<{
  id: string
  label: string
  binding: Record<string, unknown>
  type: 'scalar' | 'integer' | 'boolean' | 'enum'
  domain: NumericDomain | EnumDomain
  default: KnobValue
  scale: 'linear' | 'log'
  unit: string | null
  axisRole: 'x' | 'y' | null
}>

export type VersionExecutionTrace = Readonly<{
  file: string
  executedLines: readonly number[]
  entryLines: readonly number[]
  lineHits?: Readonly<Record<string, number>>
  /** Full ordered branch outcomes when the decision-tree pack instruments a run. */
  branchDecisions?: readonly BranchDecision[]
}>

export type BranchDecision = Readonly<{
  tag: string
  outcome: boolean
}>

export type ResponsibleLine = Readonly<{
  version: 'base' | 'head'
  file: string
  line: number
  code: string
}>

/** Empirical ``sys.settrace`` evidence collected for this exact knob position. */
export type TraceAttribution = Readonly<{
  base: VersionExecutionTrace
  head: VersionExecutionTrace
  responsibleLine: ResponsibleLine | null
}>

export type ObservationBundle = Readonly<{
  /** Present for persisted Adversary cache entries, not required for fresh evaluation replies. */
  position?: KnobPosition
  base: Record<string, unknown>
  head: Record<string, unknown>
  trace?: TraceAttribution
}>

export type SourceFile = Readonly<{
  path: string
  source: string
}>

export type SourceFiles = Readonly<Partial<Record<'base' | 'head', SourceFile>>>

export type WidgetConfig = Readonly<{
  domainPack: string
  thesis: string
  controls: readonly ControlDescriptor[]
  charts: readonly Readonly<{
    observableId: string
    label: string
    render: string
    compareMode: string
    unit: string | null
    yAxisZeroAnchored: true
  }>[]
  unionTree?: Readonly<{
    observableId: string
    label: string
    render: 'unionTree'
    nodes: readonly Readonly<{
      tag: string
      baseOutcomes: readonly boolean[]
      headOutcomes: readonly boolean[]
      positions: readonly KnobPosition[]
      baseTouched: boolean
      headTouched: boolean
    }>[]
    forkTag: string | null
  }> | null
  initialPosition: KnobPosition
  surpriseMarker: Readonly<{
    position: KnobPosition
    divergence: number
    caption: string
  }> | null
  presets: readonly unknown[]
  fidelityBand: 'high' | 'medium' | 'low'
  fidelityConfidence: number
  /** Rendering discriminator: generated candidates may never use verified UI. */
  speculative: boolean
  /** Deterministic disclosure when candidate source misses named hypothesis evidence. */
  hypothesisCaveat: string | null
}>

export type ProgressEvent = Readonly<{
  type: 'progress'
  stage: 'files_touched' | 'behavior_identified' | 'old_vs_new' | 'building'
  message: string
}>

/** One actual Adversary probe delivered before the terminal widget payload. */
export type SearchTracePoint = Readonly<{
  position: KnobPosition
  divergence: number
  phase: 'explore' | 'exploit'
}>

export type SearchTraceEvent = Readonly<{
  type: 'search_trace'
  tracePoint: SearchTracePoint
}>

export type SearchObjective = 'max_divergence' | 'max_path_divergence' | 'reach_unsafe_state'

export type UnsafePredicate = Readonly<{
  observableId: string
  operator: 'gt' | 'gte' | 'lt' | 'lte' | 'eq' | 'neq'
  target:
    | Readonly<{ kind: 'literal'; value: KnobValue }>
    | Readonly<{ kind: 'knob'; id: string }>
  versions?: 'either' | 'base' | 'head'
}>

export type ObjectiveResultEvent = Readonly<{
  type: 'objective_result'
  requestId: string
  objective: SearchObjective
  unsafePredicate: UnsafePredicate | null
  noUnsafeState: boolean
  reason: string | null
  surpriseMarker: WidgetConfig['surpriseMarker']
  positionCache: Record<string, ObservationBundle>
}>

export type CompleteEvent = Readonly<{
  type: 'complete'
  changeId: string
  widgetConfig: WidgetConfig
  positionCache: Record<string, ObservationBundle>
  sourceFiles: SourceFiles
}>

export type EvaluationEvent = Readonly<{
  type: 'evaluation'
  requestId: string
  positionKey: string
  observations: ObservationBundle
  source: 'cache' | 'fresh'
}>

export type DivergenceReportEntry = Readonly<{
  position: KnobPosition
  version: 'base' | 'head' | string
  observable: string
  harness: unknown
  reference: unknown
}>

/** A distinct terminal outcome; none of these may be rendered as a widget. */
export type DegradationEvent = Readonly<{
  type: 'skipped' | 'unscopable' | 'inert' | 'degraded'
  changeId: string
  degradeReason: string
  plainExplanation: string
  divergenceReport: readonly DivergenceReportEntry[]
  positionCache: Record<string, ObservationBundle>
}>
