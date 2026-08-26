'use client'

/**
 * MapLibre rendering of a heat surface.
 *
 * Basemap tiles come from CARTO's free raster endpoint, so no access token is
 * required and the project stays runnable by anyone who clones it. Attribution is
 * kept in the map's own attribution control, as their terms require.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'

import {
  type GeoJSONFeatureCollection,
  type LayerKey,
  RAMPS,
  fillColorExpression,
  formatValue,
} from '@/lib/cityvigil'

const SOURCE_ID = 'cityvigil-tiles'
const FILL_LAYER = 'cityvigil-tiles-fill'
const EXTRUDE_LAYER = 'cityvigil-tiles-3d'
const AOI_SOURCE = 'cityvigil-aoi'
const AOI_LAYER = 'cityvigil-aoi-outline'

/**
 * Metres of extrusion per unit of layer value, chosen so each layer reaches a
 * comparable visual height. Exceedance runs to ~92 hours, persistence to ~8, and
 * temperature sits around 36 °C, so a single scale would flatten two of the three.
 */
const EXTRUDE_SCALE: Record<LayerKey, number> = {
  exceedance: 26,
  persistence: 300,
  snapshot: 65,
  peak_hour: 120,
}

const BASE_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    carto: {
      type: 'raster',
      tiles: ['https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors © CARTO',
    },
  },
  layers: [{ id: 'carto', type: 'raster', source: 'carto' }],
}

interface HeatMapProps {
  geojson: GeoJSONFeatureCollection | null
  layer: LayerKey
  min: number
  max: number
  aoi?: GeoJSONFeatureCollection | null
  loading?: boolean
}

export function HeatMap({ geojson, layer, min, max, aoi, loading }: HeatMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const [ready, setReady] = useState(false)
  const [threeD, setThreeD] = useState(false)
  const [hover, setHover] = useState<{ value: number; x: number; y: number } | null>(null)

  // Create the map once.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASE_STYLE,
      center: [-112.075, 33.445],
      zoom: 11,
      attributionControl: { compact: true },
    })
    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'bottom-right')
    map.on('load', () => setReady(true))
    mapRef.current = map

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  // Push tile geometry, and keep the paint expression in step with the layer.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return

    const paint = fillColorExpression(layer, min, max)

    if (!geojson) {
      if (map.getLayer(FILL_LAYER)) map.removeLayer(FILL_LAYER)
      if (map.getSource(SOURCE_ID)) map.removeSource(SOURCE_ID)
      return
    }

    const existing = map.getSource(SOURCE_ID) as maplibregl.GeoJSONSource | undefined
    if (existing) {
      existing.setData(geojson as never)
    } else {
      map.addSource(SOURCE_ID, { type: 'geojson', data: geojson as never })
    }

    if (!map.getLayer(FILL_LAYER)) {
      map.addLayer({
        id: FILL_LAYER,
        type: 'fill',
        source: SOURCE_ID,
        paint: {
          'fill-color': paint as never,
          'fill-opacity': 0.78,
          'fill-outline-color': 'rgba(0,0,0,0)',
        },
      })
    } else {
      map.setPaintProperty(FILL_LAYER, 'fill-color', paint as never)
    }

    // 3D companion. Height encodes the same value the colour does, which is
    // deliberate redundancy: colour alone is hard to rank precisely, while height
    // makes the worst tiles obvious from across the room. MapLibre does this
    // natively, so it costs no extra dependency.
    if (!map.getLayer(EXTRUDE_LAYER)) {
      map.addLayer({
        id: EXTRUDE_LAYER,
        type: 'fill-extrusion',
        source: SOURCE_ID,
        layout: { visibility: 'none' },
        paint: {
          'fill-extrusion-color': paint as never,
          'fill-extrusion-opacity': 0.9,
          'fill-extrusion-base': 0,
          'fill-extrusion-height': [
            'max',
            0,
            ['*', ['-', ['get', 'value'], min], EXTRUDE_SCALE[layer]],
          ] as never,
        },
      })
    } else {
      map.setPaintProperty(EXTRUDE_LAYER, 'fill-extrusion-color', paint as never)
      map.setPaintProperty(EXTRUDE_LAYER, 'fill-extrusion-height', [
        'max',
        0,
        ['*', ['-', ['get', 'value'], min], EXTRUDE_SCALE[layer]],
      ] as never)
    }

    // Fit once to the data we actually received.
    const bounds = new maplibregl.LngLatBounds()
    for (const feature of geojson.features) {
      for (const ring of feature.geometry.coordinates) {
        for (const [lng, lat] of ring as unknown as [number, number][]) {
          bounds.extend([lng, lat])
        }
      }
    }
    if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 32, duration: 600 })
  }, [geojson, layer, min, max, ready])

  // Outline the study area so the analysed footprint is unambiguous.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready || !aoi) return

    const existing = map.getSource(AOI_SOURCE) as maplibregl.GeoJSONSource | undefined
    if (existing) {
      existing.setData(aoi as never)
    } else {
      map.addSource(AOI_SOURCE, { type: 'geojson', data: aoi as never })
    }
    if (!map.getLayer(AOI_LAYER)) {
      map.addLayer({
        id: AOI_LAYER,
        type: 'line',
        source: AOI_SOURCE,
        paint: { 'line-color': '#0284c7', 'line-width': 1.5, 'line-dasharray': [3, 2] },
      })
    }
  }, [aoi, ready])

  // Hover readout: the number under the cursor, in the layer's own units.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return

    const onMove = (e: maplibregl.MapMouseEvent) => {
      if (!map.getLayer(FILL_LAYER)) return
      const hits = map.queryRenderedFeatures(e.point, { layers: [FILL_LAYER] })
      const value = hits[0]?.properties?.value
      setHover(
        typeof value === 'number'
          ? { value, x: e.point.x, y: e.point.y }
          : null,
      )
    }
    const onLeave = () => setHover(null)

    map.on('mousemove', onMove)
    map.on('mouseout', onLeave)
    return () => {
      map.off('mousemove', onMove)
      map.off('mouseout', onLeave)
    }
  }, [ready])

  // Toggle between the flat choropleth and the extruded 3D view, tilting the
  // camera so the height is actually legible.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    if (!map.getLayer(EXTRUDE_LAYER) || !map.getLayer(FILL_LAYER)) return

    map.setLayoutProperty(EXTRUDE_LAYER, 'visibility', threeD ? 'visible' : 'none')
    map.setLayoutProperty(FILL_LAYER, 'visibility', threeD ? 'none' : 'visible')
    map.easeTo({
      pitch: threeD ? 52 : 0,
      bearing: threeD ? -22 : 0,
      duration: 700,
    })
  }, [threeD, ready, geojson])

  const legendStops = useMemo(() => {
    if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return []
    return Array.from({ length: 5 }, (_, i) => min + ((max - min) * i) / 4)
  }, [min, max])

  return (
    <div className="relative h-full w-full overflow-hidden rounded-xl border border-slate-200 shadow-sm">
      <div ref={containerRef} className="h-full w-full" aria-label="Heat exposure map" role="img" />

      <button
        type="button"
        onClick={() => setThreeD((v) => !v)}
        aria-pressed={threeD}
        className={`absolute right-3 top-3 z-20 rounded-lg border px-2.5 py-1.5 text-xs font-medium shadow-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 ${
          threeD
            ? 'border-sky-500 bg-sky-600 text-white'
            : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'
        }`}
        title="Extrude tiles by value — height encodes the same number as the colour"
      >
        {threeD ? '2D view' : '3D view'}
      </button>

      {loading && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-slate-50 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-2">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-sky-600" />
            <p className="text-xs text-slate-500">
              Querying the FortyGuard API — large areas take up to a minute
            </p>
          </div>
        </div>
      )}

      {hover && (
        <div
          className="pointer-events-none absolute z-30 rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-900 shadow-sm"
          style={{ left: hover.x + 12, top: hover.y + 12 }}
        >
          {formatValue(layer, hover.value)}
        </div>
      )}

      {legendStops.length > 0 && (
        <div className="absolute bottom-3 left-3 z-10 rounded-lg border border-slate-200 bg-white/95 p-2">
          <div className="mb-1 flex h-2 w-40 overflow-hidden rounded-full">
            {RAMPS[layer].map((color) => (
              <div key={color} className="flex-1" style={{ background: color }} />
            ))}
          </div>
          <div className="flex justify-between text-[10px] tabular-nums text-slate-500">
            <span>{formatValue(layer, min)}</span>
            <span>{formatValue(layer, max)}</span>
          </div>
        </div>
      )}
    </div>
  )
}
