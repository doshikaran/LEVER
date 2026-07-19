export type KnobValue = number | string | boolean
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

export type ObservationBundle = Readonly<{
  base: Record<string, unknown>
  head: Record<string, unknown>
}>

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
  initialPosition: KnobPosition
  surpriseMarker: Readonly<{
    position: KnobPosition
    divergence: number
    caption: string
  }> | null
  presets: readonly unknown[]
  fidelityBand: 'high' | 'medium' | 'low'
  fidelityConfidence: number
}>

export type ProgressEvent = Readonly<{
  type: 'progress'
  stage: 'files_touched' | 'behavior_identified' | 'old_vs_new' | 'building'
  message: string
}>

export type CompleteEvent = Readonly<{
  type: 'complete'
  changeId: string
  widgetConfig: WidgetConfig
  positionCache: Record<string, ObservationBundle>
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
