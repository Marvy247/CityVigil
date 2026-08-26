'use client'

/**
 * The panel that keeps the project honest.
 *
 * Shows the rationale recorded for the selected layer, the exceedance-versus-
 * persistence contrast, and the raw audit trail. Nothing here is generated for
 * display: it is the same trail the engine wrote while making the calls.
 */

import { useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronRight, Info } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { AuditResponse, LayerKey, SurfaceSummary } from '@/lib/cityvigil'
import { formatValue } from '@/lib/cityvigil'

interface ProvenancePanelProps {
  layer: LayerKey
  summary?: SurfaceSummary
  summaries: Partial<Record<LayerKey, SurfaceSummary>>
  audit: AuditResponse | null
  utcOffsetH: number
}

export function ProvenancePanel({
  layer,
  summary,
  summaries,
  audit,
  utcOffsetH,
}: ProvenancePanelProps) {
  const [trailOpen, setTrailOpen] = useState(false)

  const exceedance = summaries.exceedance
  const persistence = summaries.persistence
  const peak = summaries.peak_hour

  return (
    <div className="space-y-3">
      {/* Why this layer */}
      {summary && (
        <Card className="border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-start gap-2">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-sky-600" aria-hidden />
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Why this layer
              </p>
              <p className="mt-1 text-sm leading-relaxed text-slate-500">
                {summary.rationale}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge variant="outline" className="border-slate-300 font-mono text-[10px]">
                  {summary.analytic_type}
                </Badge>
                <Badge variant="outline" className="border-slate-300 text-[10px]">
                  {summary.n_tiles.toLocaleString()} tiles
                </Badge>
                <Badge variant="outline" className="border-slate-300 text-[10px]">
                  units: {summary.units}
                </Badge>
                {summary.threshold_c !== null && (
                  <Badge variant="outline" className="border-slate-300 text-[10px]">
                    threshold {summary.threshold_c.toFixed(1)} °C
                  </Badge>
                )}
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* The distinction that drives allocation */}
      {exceedance && persistence && (
        <Card className="border-amber-200 bg-amber-50 p-4 shadow-sm">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden />
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-amber-800">
                Total hours vs. unbroken hours
              </p>
              <dl className="mt-2 grid grid-cols-2 gap-3 text-sm">
                <div>
                  <dt className="text-[11px] text-slate-500">Worst total exposure</dt>
                  <dd className="tabular-nums font-semibold text-slate-900">
                    {formatValue('exceedance', exceedance.max)}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] text-slate-500">Worst unbroken stretch</dt>
                  <dd className="tabular-nums font-semibold text-slate-900">
                    {formatValue('persistence', persistence.max)}
                  </dd>
                </div>
              </dl>
              <p className="mt-2 text-xs leading-relaxed text-slate-500">
                Both are measured in hours, and they are not interchangeable. Two
                blocks can log identical totals while one cools overnight and the
                other never does. Heat mortality tracks the second, so ranking on
                totals alone would systematically under-protect the areas most at
                risk.
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* Peak timing, reported without a timezone conversion */}
      {peak?.mean != null && (
        <Card className="border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Peak timing
          </p>
          <p className="mt-1 text-sm text-slate-500">
            Mean peak at{' '}
            <span className="font-semibold tabular-nums text-slate-900">
              {String(Math.round(peak.mean)).padStart(2, '0')}:00
            </span>{' '}
            <span className="text-slate-500">local</span>
          </p>
          <p className="mt-1 text-xs text-slate-500">
            The quickstart documents this as a UTC hour, but measurement disagrees:
            the API returns 16–17 here, while <code>env_params</code> reports GMT-7
            with apparent temperature peaking at 15:00 local. A UTC reading would
            imply a 09:00 local peak, which is not credible in Phoenix in July.
            Treated as local time with no conversion applied.
          </p>
        </Card>
      )}

      {/* Raw trail */}
      {audit && (
        <Card className="border-slate-200 bg-white shadow-sm">
          <button
            type="button"
            onClick={() => setTrailOpen((o) => !o)}
            aria-expanded={trailOpen}
            className="flex w-full items-center justify-between p-4 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          >
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Audit trail
              <span className="ml-2 font-normal normal-case text-slate-500">
                {audit.records.length} records
              </span>
            </span>
            {trailOpen ? (
              <ChevronDown className="h-4 w-4 text-slate-500" aria-hidden />
            ) : (
              <ChevronRight className="h-4 w-4 text-slate-500" aria-hidden />
            )}
          </button>

          <div className="px-4 pb-3">
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(audit.endpoints_used).map(([endpoint, count]) => (
                <Badge
                  key={endpoint}
                  variant="outline"
                  className="border-slate-300 font-mono text-[10px]"
                >
                  {endpoint} ×{count}
                </Badge>
              ))}
            </div>
          </div>

          <div
            className={cn(
              'overflow-hidden transition-all',
              trailOpen ? 'max-h-96' : 'max-h-0',
            )}
          >
            <pre className="max-h-96 overflow-auto border-t border-slate-200 bg-slate-50 p-3 text-[10px] leading-relaxed text-slate-500">
              {audit.text || 'No calls recorded yet.'}
            </pre>
          </div>
        </Card>
      )}
    </div>
  )
}
