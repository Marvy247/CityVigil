'use client'

/**
 * Who gets protected first.
 *
 * Ranks census tracts by vulnerability-weighted person-hours of dangerous heat,
 * and shows what the weighting changed relative to raw exposure. That comparison
 * is deliberate: presenting a weighted metric without showing the unweighted one
 * hides the modelling choice inside the headline.
 */

import { useState } from 'react'
import { ArrowDown, ArrowUp, Minus, Users } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { ExposureResponse, TractExposureRow } from '@/lib/cityvigil'
import { compact } from '@/lib/cityvigil'

interface PriorityPanelProps {
  exposure: ExposureResponse | null
  loading?: boolean
  onHoverTract?: (geoid: string | null) => void
  selected?: string | null
}

function StatCard({
  label,
  value,
  sub,
}: {
  label: string
  value: string
  sub?: string
}) {
  return (
    <Card className="border-slate-200 bg-white p-3 shadow-sm">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums text-slate-900">{value}</p>
      {sub && <p className="mt-0.5 text-[11px] text-slate-500">{sub}</p>}
    </Card>
  )
}

function RankDelta({ moved }: { moved: number }) {
  if (moved === 0) {
    return (
      <span className="inline-flex items-center text-slate-500">
        <Minus className="h-3 w-3" aria-hidden />
        <span className="sr-only">unchanged</span>
      </span>
    )
  }
  const up = moved > 0
  return (
    <span
      className={cn(
        'inline-flex items-center gap-0.5 tabular-nums',
        up ? 'text-amber-600' : 'text-sky-600',
      )}
    >
      {up ? (
        <ArrowUp className="h-3 w-3" aria-hidden />
      ) : (
        <ArrowDown className="h-3 w-3" aria-hidden />
      )}
      {Math.abs(moved)}
      <span className="sr-only">
        {up ? `moved up ${moved} places` : `moved down ${-moved} places`}
      </span>
    </span>
  )
}

export function PriorityPanel({
  exposure,
  loading,
  onHoverTract,
  selected,
}: PriorityPanelProps) {
  const [expanded, setExpanded] = useState<string | null>(null)

  if (loading && !exposure) {
    return (
      <Card className="border-slate-200 bg-white p-6 shadow-sm">
        <p className="animate-pulse text-sm text-slate-500">
          Joining heat tiles to census tracts…
        </p>
      </Card>
    )
  }

  if (!exposure) return null

  const { totals, model, rank_shift: rankShift, tracts } = exposure
  const shiftByGeoid = new Map(rankShift.map((r) => [r.geoid, r]))

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <StatCard
          label="Person-hours at risk"
          value={compact(totals.person_hours)}
          sub={`${totals.population.toLocaleString()} residents`}
        />
        <StatCard
          label="Vulnerability-weighted"
          value={compact(totals.weighted_person_hours)}
          sub="allocation objective"
        />
        <StatCard
          label="Borne by 65+"
          value={compact(totals.elderly_person_hours)}
          sub={`${totals.population_65_plus.toLocaleString()} residents aged 65+`}
        />
        <StatCard
          label="Outdoor workers"
          value={totals.outdoor_jobs.toLocaleString()}
          sub="jobs in exposed sectors"
        />
      </div>

      <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-500">
        Person-hours = hours above the {totals.threshold_c?.toFixed(1)} °C threshold ×
        residents exposed, from {totals.tiles_matched.toLocaleString()} tiles joined to{' '}
        {totals.n_tracts} tracts ({totals.tiles_unmatched} unmatched). Weighting:{' '}
        {Object.entries(model.weights)
          .map(([k, v]) => `${k} ${v}`)
          .join(' · ')}
        . {model.caveat}
      </p>

      <Card className="border-slate-200 bg-white shadow-sm">
        <div className="flex items-center gap-2 border-b border-slate-200 p-3">
          <Users className="h-4 w-4 text-sky-600" aria-hidden />
          <h2 className="text-sm font-semibold text-slate-900">
            Protection priority by census tract
          </h2>
          <Badge variant="outline" className="ml-auto border-slate-300 text-[10px]">
            {tracts.length} shown
          </Badge>
        </div>

        <div className="max-h-[26rem] overflow-auto">
          <TooltipProvider>
            <Table>
              <TableHeader className="sticky top-0 bg-white">
                <TableRow className="border-slate-200 hover:bg-transparent">
                  <TableHead className="w-10 text-slate-500">#</TableHead>
                  <TableHead className="text-slate-500">Tract</TableHead>
                  <TableHead className="text-right text-slate-500">Pop</TableHead>
                  <TableHead className="text-right text-slate-500">65+</TableHead>
                  <TableHead className="text-right text-slate-500">Hrs</TableHead>
                  <TableHead className="text-right text-slate-500">Unbroken</TableHead>
                  <TableHead className="text-right text-slate-500">Vuln</TableHead>
                  <TableHead className="text-right text-slate-500">
                    Weighted p-h
                  </TableHead>
                  <TableHead className="w-12 text-right text-slate-500">Δ</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tracts.map((t: TractExposureRow, i) => {
                  const shift = shiftByGeoid.get(t.geoid)
                  const isOpen = expanded === t.geoid
                  return (
                    <>
                      <TableRow
                        key={t.geoid}
                        onMouseEnter={() => onHoverTract?.(t.geoid)}
                        onMouseLeave={() => onHoverTract?.(null)}
                        onClick={() => setExpanded(isOpen ? null : t.geoid)}
                        className={cn(
                          'cursor-pointer border-slate-200 text-xs',
                          selected === t.geoid && 'bg-sky-50',
                        )}
                      >
                        <TableCell className="tabular-nums text-slate-500">
                          {t.rank ?? i + 1}
                        </TableCell>
                        <TableCell className="font-mono text-[11px] text-slate-500">
                          {t.geoid.slice(-6)}
                          {t.vulnerability.svi_imputed && (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span className="ml-1 cursor-help text-amber-500">*</span>
                              </TooltipTrigger>
                              <TooltipContent>
                                CDC SVI percentile missing; weights renormalised
                              </TooltipContent>
                            </Tooltip>
                          )}
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-slate-500">
                          {t.population.toLocaleString()}
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-slate-500">
                          {t.age65.toLocaleString()}
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-slate-500">
                          {t.mean_exceedance_h.toFixed(0)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-slate-500">
                          {t.mean_persistence_h?.toFixed(1) ?? '—'}
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-slate-800">
                          {t.vulnerability.score.toFixed(2)}
                        </TableCell>
                        <TableCell className="text-right font-semibold tabular-nums text-slate-900">
                          {compact(t.weighted_person_hours)}
                        </TableCell>
                        <TableCell className="text-right">
                          {shift ? <RankDelta moved={shift.moved_up} /> : null}
                        </TableCell>
                      </TableRow>
                      {isOpen && (
                        <TableRow key={`${t.geoid}-detail`} className="border-slate-200">
                          <TableCell colSpan={9} className="bg-slate-50 text-[11px]">
                            <p className="text-slate-500">{t.name}</p>
                            <p className="mt-1 font-mono text-slate-500">
                              {t.vulnerability.explanation}
                            </p>
                            <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-4">
                              <div>
                                <dt className="text-slate-500">Resident person-hours</dt>
                                <dd className="tabular-nums text-slate-800">
                                  {t.person_hours.toLocaleString()}
                                </dd>
                              </div>
                              <div>
                                <dt className="text-slate-500">Of which 65+</dt>
                                <dd className="tabular-nums text-slate-800">
                                  {t.elderly_person_hours.toLocaleString()}
                                </dd>
                              </div>
                              <div>
                                <dt className="text-slate-500">
                                  Worker hours (upper bound)
                                </dt>
                                <dd className="tabular-nums text-slate-800">
                                  {t.worker_exposure_hours_upper_bound.toLocaleString()}
                                </dd>
                              </div>
                              <div>
                                <dt className="text-slate-500">Mean temperature</dt>
                                <dd className="tabular-nums text-slate-800">
                                  {t.mean_temperature_c?.toFixed(1) ?? '—'} °C
                                </dd>
                              </div>
                            </dl>
                          </TableCell>
                        </TableRow>
                      )}
                    </>
                  )
                })}
              </TableBody>
            </Table>
          </TooltipProvider>
        </div>
      </Card>
    </div>
  )
}
