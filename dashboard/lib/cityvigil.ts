/**
 * Typed client for the CityVigil API, plus the colour scales the map uses.
 *
 * The backend is expected on 127.0.0.1:8000 (see scripts/serve.py). It holds the
 * FortyGuard key and has no authentication, so it must stay bound to localhost.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_CITYVIGIL_API ?? 'http://127.0.0.1:8000'

export type LayerKey = 'snapshot' | 'peak_hour' | 'exceedance' | 'persistence'

export interface Health {
  ok: boolean
  cache_mode: 'live' | 'replay' | 'refresh'
  has_api_key: boolean
  base_url: string
  cities: string[]
}

export interface Credits {
  remaining: number | null
  credits_per_heatmap: number
  heatmaps_affordable: number | null
}

export interface LayerMeta {
  key: LayerKey
  label: string
  analytic_type: string
  unit_label: string
  question: string
}

export interface CityEpisode {
  start: string
  end: string
  note: string
}

export interface City {
  key: string
  name: string
  utc_offset_h: number
  danger_threshold_f: number
  episode: CityEpisode
  aoi: GeoJSONFeatureCollection
}

export interface SurfaceSummary {
  analytic_type: string
  units: string
  n_tiles: number
  min: number | null
  mean: number | null
  max: number | null
  threshold_c: number | null
  window: Record<string, unknown>
  label: string
  unit_label: string
  question: string
  rationale: string
}

export interface SurfacesResponse {
  city: string
  surfaces: Partial<Record<LayerKey, SurfaceSummary>>
  stats: {
    cache: { mode: string; hits: number; misses: number; writes: number }
    endpoints_used: Record<string, number>
    layers_used: Record<string, number>
    audit_records: number
  }
}

export interface AuditRecord {
  kind: string
  summary: string
  at: string
  detail: Record<string, unknown>
}

export interface AuditResponse {
  records: AuditRecord[]
  endpoints_used: Record<string, number>
  layers_used: Record<string, number>
  text: string
}

export interface GeoJSONFeatureCollection {
  type: 'FeatureCollection'
  properties?: Record<string, unknown>
  features: Array<{
    type: 'Feature'
    id?: string
    properties: Record<string, unknown>
    geometry: { type: string; coordinates: number[][][] }
  }>
}

export interface SurfaceRequest {
  city?: string
  layers?: LayerKey[]
  start_date?: string | null
  end_date?: string | null
  threshold_f?: number | null
  granularity?: number
}

/** Error carrying the backend's structured detail, so the UI can explain itself. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch (cause) {
    throw new ApiError(
      `Cannot reach the CityVigil API at ${API_BASE}. Start it with: python3 scripts/serve.py`,
      0,
      cause,
    )
  }

  if (!response.ok) {
    let detail: unknown
    try {
      detail = (await response.json())?.detail
    } catch {
      detail = await response.text()
    }
    const message =
      typeof detail === 'object' && detail !== null && 'error' in detail
        ? String((detail as { error: unknown }).error)
        : `Request to ${path} failed (${response.status})`
    throw new ApiError(message, response.status, detail)
  }

  return (await response.json()) as T
}

export const getHealth = () => request<Health>('/health')
export const getCredits = () => request<Credits>('/api/credits')
export const getLayers = () => request<{ layers: LayerMeta[] }>('/api/layers')
export const getCities = () => request<{ cities: City[] }>('/api/cities')
export const getAudit = () => request<AuditResponse>('/api/audit')
export const getSources = () => request<SourcesResponse>('/api/sources')
export const getTractsSummary = () => request<TractsSummary>('/api/tracts/summary')

export const getSurfaces = (body: SurfaceRequest) =>
  request<SurfacesResponse>('/api/surfaces', {
    method: 'POST',
    body: JSON.stringify(body),
  })

export const getSurfaceGeoJSON = (layer: LayerKey, body: SurfaceRequest) =>
  request<GeoJSONFeatureCollection>(`/api/surface/${layer}/geojson`, {
    method: 'POST',
    body: JSON.stringify(body),
  })

export const getExposure = (body: ExposureRequest) =>
  request<ExposureResponse>('/api/exposure', {
    method: 'POST',
    body: JSON.stringify(body),
  })

export const getExposureGeoJSON = (body: ExposureRequest) =>
  request<TractGeoJSON>('/api/exposure/geojson', {
    method: 'POST',
    body: JSON.stringify(body),
  })

/* ---------------------------------------------- vulnerability & person-hours */

export interface DataSourceInfo {
  key: string
  name: string
  url: string
  citation: string
  licence: string
  role: string
}

export interface SourcesResponse {
  sources: DataSourceInfo[]
  manifest: Record<string, { bytes: number; sha256: string; recorded_at: string }>
  citations: string[]
}

export interface TractsSummary {
  n_tracts: number
  total_population: number
  zero_population_tracts: number
  missing_svi_percentile: number
  total_jobs: number
  outdoor_jobs: number
}

export interface ExposureRequest {
  city?: string
  start_date?: string | null
  end_date?: string | null
  threshold_f?: number | null
  granularity?: number
  weight_svi?: number
  weight_elderly?: number
  weight_outdoor?: number
  limit?: number
}

export interface VulnerabilityDetail {
  geoid: string
  score: number
  components: Record<string, number>
  weights_used: Record<string, number>
  svi_imputed: boolean
  explanation: string
}

export interface TractExposureRow {
  geoid: string
  name: string
  population: number
  age65: number
  jobs_outdoor: number
  n_tiles: number
  mean_exceedance_h: number
  max_exceedance_h: number
  mean_persistence_h: number | null
  max_persistence_h: number | null
  mean_temperature_c: number | null
  person_hours: number
  elderly_person_hours: number
  worker_exposure_hours_upper_bound: number
  vulnerability: VulnerabilityDetail
  weighted_person_hours: number
  threshold_c: number | null
  rank?: number
}

export interface ExposureTotals {
  n_tracts: number
  population: number
  population_65_plus: number
  outdoor_jobs: number
  person_hours: number
  elderly_person_hours: number
  weighted_person_hours: number
  worker_exposure_hours_upper_bound: number
  tiles_matched: number
  tiles_unmatched: number
  threshold_c: number | null
}

export interface RankShift {
  geoid: string
  rank_weighted: number
  rank_person_hours: number
  moved_up: number
}

export interface ModelInfo {
  weights: Record<string, number>
  normalisation: string
  n_tracts_ranked: number
  component_sources: Record<string, string>
  caveat: string
}

export interface ExposureResponse {
  totals: ExposureTotals
  model: ModelInfo
  window: Record<string, unknown>
  rank_shift: RankShift[]
  tracts: TractExposureRow[]
}

export interface TractGeoJSON {
  type: 'FeatureCollection'
  properties: { totals: ExposureTotals; model: ModelInfo }
  features: Array<{
    type: 'Feature'
    id: string
    properties: TractExposureRow & { rank: number }
    geometry: { type: 'MultiPolygon'; coordinates: number[][][][] }
  }>
}

/** Compact large counts: 17,576,225 -> "17.6M". */
export function compact(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  const abs = Math.abs(value)
  if (abs >= 1e9) return `${(value / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}k`
  return value.toFixed(0)
}

/* ------------------------------------------------------------------ colours */

/**
 * Per-layer colour ramps.
 *
 * `persistence` deliberately uses a different hue family from `exceedance`. The
 * two are both measured in hours and are easy to confuse, and conflating them is
 * the specific analytical error this project is built to avoid — so they must not
 * look alike on the map.
 */
export const RAMPS: Record<LayerKey, string[]> = {
  snapshot: ['#2c7bb6', '#abd9e9', '#ffffbf', '#fdae61', '#d7191c'],
  peak_hour: ['#3b0f70', '#8c2981', '#de4968', '#fe9f6d', '#fcfdbf'],
  exceedance: ['#fff5eb', '#fdd0a2', '#fd8d3c', '#d94801', '#7f2704'],
  persistence: ['#f7f4f9', '#d4b9da', '#c994c7', '#ce1256', '#67001f'],
}

/**
 * Build a MapLibre `interpolate` expression across a value domain.
 *
 * Falls back to a flat mid-ramp colour when a layer is uniform (min === max),
 * because an interpolate expression with equal stops is invalid.
 */
export function fillColorExpression(
  layer: LayerKey,
  min: number,
  max: number,
): unknown {
  const ramp = RAMPS[layer]
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) {
    return ramp[Math.floor(ramp.length / 2)]
  }
  const stops = ramp.flatMap((color, i) => [
    min + ((max - min) * i) / (ramp.length - 1),
    color,
  ])
  return ['interpolate', ['linear'], ['get', 'value'], ...stops]
}

/** Format a value with the units the layer actually reports. */
export function formatValue(layer: LayerKey, value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—'
  switch (layer) {
    case 'snapshot':
      return `${value.toFixed(1)} °C`
    case 'peak_hour':
      return `${Math.round(value)}:00`
    default:
      return `${value.toFixed(1)} h`
  }
}

/**
 * Convert a UTC hour to a city's local clock hour.
 *
 * Deliberately NOT applied to `time_of_measure`. Measurement indicates that layer
 * already returns local hours despite the quickstart calling it UTC, so converting
 * it would shift every scheduling recommendation by seven hours. Kept for genuine
 * UTC inputs only.
 */
export function toLocalHour(utcHour: number, utcOffsetH: number): number {
  return (((Math.round(utcHour) + utcOffsetH) % 24) + 24) % 24
}
