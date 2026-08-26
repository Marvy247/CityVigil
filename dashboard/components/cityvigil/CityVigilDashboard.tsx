'use client'

/**
 * CityVigil exposure explorer.
 *
 * Phase 1 surface: renders the four FortyGuard analysis layers over a study area
 * with the reasoning behind each layer choice visible alongside. Allocation and
 * economics arrive in later phases (see PLAN.md); nothing here invents numbers it
 * cannot source from the API.
 */

import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, Coins, Database, RefreshCw } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { HeatMap } from './HeatMap'
import { LayerPicker } from './LayerPicker'
import { ProvenancePanel } from './ProvenancePanel'
import {
  type AuditResponse,
  type City,
  type Credits,
  type ExposureResponse,
  type GeoJSONFeatureCollection,
  type Health,
  type LayerKey,
  type LayerMeta,
  type SurfaceSummary,
  type TractsSummary,
  ApiError,
  getAudit,
  getCities,
  getCredits,
  getExposure,
  getHealth,
  getLayers,
  getSurfaceGeoJSON,
  getSurfaces,
  getTractsSummary,
  onSourceChange,
} from '@/lib/cityvigil'
import { AgentPanel } from './AgentPanel'
import { PriorityPanel } from './PriorityPanel'

const ALL_LAYERS: LayerKey[] = ['snapshot', 'peak_hour', 'exceedance', 'persistence']

export function CityVigilDashboard() {
  const [health, setHealth] = useState<Health | null>(null)
  const [credits, setCredits] = useState<Credits | null>(null)
  const [layerMeta, setLayerMeta] = useState<LayerMeta[]>([])
  const [city, setCity] = useState<City | null>(null)
  const [summaries, setSummaries] = useState<Partial<Record<LayerKey, SurfaceSummary>>>({})
  const [audit, setAudit] = useState<AuditResponse | null>(null)

  const [active, setActive] = useState<LayerKey>('exceedance')
  const [geojson, setGeojson] = useState<GeoJSONFeatureCollection | null>(null)
  const [geojsonCache, setGeojsonCache] = useState<Partial<Record<LayerKey, GeoJSONFeatureCollection>>>({})

  const [loading, setLoading] = useState(true)
  const [mapLoading, setMapLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [exposure, setExposure] = useState<ExposureResponse | null>(null)
  const [tractsSummary, setTractsSummary] = useState<TractsSummary | null>(null)
  const [exposureLoading, setExposureLoading] = useState(false)
  const [exposureError, setExposureError] = useState<string | null>(null)
  const [hoveredTract, setHoveredTract] = useState<string | null>(null)
  const [snapshot, setSnapshot] = useState(false)

  // Disclose when responses are coming from the committed capture rather than a
  // live API. Silently serving fixed data would misrepresent the demo.
  useEffect(() => onSourceChange(setSnapshot), [])

  /** Load metadata and every layer summary. */
  const loadAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [h, c, l, cities] = await Promise.all([
        getHealth(),
        getCredits(),
        getLayers(),
        getCities(),
      ])
      setHealth(h)
      setCredits(c)
      setLayerMeta(l.layers)
      const first = cities.cities[0] ?? null
      setCity(first)

      const response = await getSurfaces({
        city: first?.key ?? 'phoenix',
        layers: ALL_LAYERS,
      })
      setSummaries(response.surfaces)
      setAudit(await getAudit())
      setCredits(await getCredits())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  /**
   * Load the vulnerability-weighted ranking. Kept separate from the surfaces so a
   * missing tract download degrades this panel only, leaving the map usable.
   */
  useEffect(() => {
    if (!city) return
    let cancelled = false
    setExposureLoading(true)
    setExposureError(null)

    Promise.all([getExposure({ city: city.key, limit: 25 }), getTractsSummary()])
      .then(([report, summary]) => {
        if (cancelled) return
        setExposure(report)
        setTractsSummary(summary)
      })
      .catch((e) => {
        if (!cancelled) {
          setExposureError(e instanceof ApiError ? e.message : String(e))
        }
      })
      .finally(() => !cancelled && setExposureLoading(false))

    return () => {
      cancelled = true
    }
  }, [city])

  /** Fetch tile geometry for the selected layer, memoised per layer. */
  useEffect(() => {
    if (!city || loading) return

    const cached = geojsonCache[active]
    if (cached) {
      setGeojson(cached)
      return
    }

    let cancelled = false
    setMapLoading(true)
    getSurfaceGeoJSON(active, { city: city.key })
      .then((data) => {
        if (cancelled) return
        setGeojsonCache((prev) => ({ ...prev, [active]: data }))
        setGeojson(data)
      })
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : String(e)))
      .finally(() => !cancelled && setMapLoading(false))

    return () => {
      cancelled = true
    }
  }, [active, city, loading, geojsonCache])

  const summary = summaries[active]

  if (error && !summary) {
    return (
      <Card className="border-red-200 bg-red-50 p-6 shadow-sm">
        <div className="flex items-start gap-3">
          <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-600" aria-hidden />
          <div>
            <h2 className="text-sm font-semibold text-red-900">Cannot load exposure data</h2>
            <p className="mt-1 text-sm text-slate-500">{error}</p>
            <Button
              onClick={() => void loadAll()}
              variant="outline"
              size="sm"
              className="mt-3 border-slate-300"
            >
              <RefreshCw className="mr-2 h-3.5 w-3.5" aria-hidden />
              Retry
            </Button>
          </div>
        </div>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">
            {city?.name ?? 'Loading study area…'}
          </h1>
          <p className="mt-0.5 text-sm text-slate-500">
            {city
              ? `${city.episode.start} → ${city.episode.end} · danger threshold ${city.danger_threshold_f} °F`
              : 'Fetching configuration'}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {health && (
            <Badge
              variant="outline"
              className={
                health.cache_mode === 'replay'
                  ? 'border-emerald-300 text-emerald-700'
                  : 'border-slate-300 text-slate-500'
              }
            >
              <Database className="mr-1 h-3 w-3" aria-hidden />
              {health.cache_mode}
            </Badge>
          )}
          {credits?.remaining != null && (
            <Badge variant="outline" className="border-slate-300 tabular-nums text-slate-500">
              <Coins className="mr-1 h-3 w-3" aria-hidden />
              {credits.remaining.toLocaleString()} credits
              <span className="ml-1 text-slate-500">
                ({credits.heatmaps_affordable} maps)
              </span>
            </Badge>
          )}
          <Button
            onClick={() => void loadAll()}
            variant="outline"
            size="sm"
            disabled={loading}
            className="border-slate-300"
          >
            <RefreshCw
              className={`mr-2 h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`}
              aria-hidden
            />
            Refresh
          </Button>
        </div>
      </div>

      {city && (
        <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-500">
          {city.episode.note}
        </p>
      )}

      {snapshot && (
        <div className="flex items-start gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2">
          <Database className="mt-0.5 h-4 w-4 shrink-0 text-sky-600" aria-hidden />
          <p className="text-xs leading-relaxed text-slate-700">
            <span className="font-semibold text-sky-800">Static snapshot.</span> No live
            API is reachable, so these are the committed responses captured from the
            FortyGuard API at default parameters — every figure is real, but changing
            parameters needs the API running locally
            (<code className="text-slate-600">python3 scripts/serve.py</code>).
          </p>
        </div>
      )}

      {/* Agent — placed above the map because the reasoning is the product for
          the Agentic AI track, not an appendix to the visualisation. */}
      {city && <AgentPanel city={city.key} hour={19} />}

      {/* Layer selection */}
      {layerMeta.length > 0 && (
        <LayerPicker
          layers={layerMeta}
          active={active}
          summaries={summaries}
          onSelect={setActive}
          disabled={loading}
        />
      )}

      {/* Map + provenance */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="h-[26rem] xl:col-span-2 xl:h-[34rem]">
          <HeatMap
            geojson={geojson}
            layer={active}
            min={summary?.min ?? 0}
            max={summary?.max ?? 1}
            aoi={city?.aoi ?? null}
            loading={mapLoading || loading}
          />
        </div>
        <div className="xl:h-[34rem] xl:overflow-y-auto">
          <ProvenancePanel
            layer={active}
            summary={summary}
            summaries={summaries}
            audit={audit}
            utcOffsetH={city?.utc_offset_h ?? 0}
          />
        </div>
      </div>

      {error && summary && (
        <p className="text-xs text-amber-600">Last action failed: {error}</p>
      )}

      {/* Who gets protected first */}
      {exposureError ? (
        <Card className="border-amber-200 bg-amber-50 p-4 shadow-sm">
          <div className="flex items-start gap-2">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden />
            <div>
              <p className="text-sm font-semibold text-amber-900">
                Vulnerability ranking unavailable
              </p>
              <p className="mt-1 text-xs text-slate-500">{exposureError}</p>
              <p className="mt-1 text-xs text-slate-500">
                The heat surfaces above are unaffected. Run{' '}
                <code className="text-slate-500">python3 scripts/fetch_data.py</code> to
                download the CDC, Census and LODES sources.
              </p>
            </div>
          </div>
        </Card>
      ) : (
        <PriorityPanel
          exposure={exposure}
          loading={exposureLoading}
          onHoverTract={setHoveredTract}
          selected={hoveredTract}
        />
      )}

      {tractsSummary && (
        <p className="text-[11px] leading-relaxed text-slate-500">
          Tract data: {tractsSummary.n_tracts.toLocaleString()} Maricopa County tracts,{' '}
          {tractsSummary.total_population.toLocaleString()} residents,{' '}
          {tractsSummary.outdoor_jobs.toLocaleString()} jobs in outdoor-exposed sectors.
          Known gaps: {tractsSummary.zero_population_tracts} tracts with zero population,{' '}
          {tractsSummary.missing_svi_percentile} without a CDC SVI percentile. Sources:
          CDC/ATSDR SVI 2022, Census TIGERweb, LEHD LODES8 (2021) — all US federal public
          domain.
        </p>
      )}
    </div>
  )
}
