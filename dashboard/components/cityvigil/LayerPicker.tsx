'use client'

/**
 * Layer selector.
 *
 * Each layer is labelled by the *question it answers* rather than by its API
 * name, because choosing a layer by name is exactly how teams end up with a
 * confident wrong answer. The underlying `analytic_type` is still shown, so the
 * mapping stays inspectable.
 */

import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { LayerKey, LayerMeta, SurfaceSummary } from '@/lib/cityvigil'
import { formatValue } from '@/lib/cityvigil'

interface LayerPickerProps {
  layers: LayerMeta[]
  active: LayerKey
  summaries: Partial<Record<LayerKey, SurfaceSummary>>
  onSelect: (layer: LayerKey) => void
  disabled?: boolean
}

export function LayerPicker({
  layers,
  active,
  summaries,
  onSelect,
  disabled,
}: LayerPickerProps) {
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
      {layers.map((meta) => {
        const summary = summaries[meta.key]
        const isActive = meta.key === active
        return (
          <Card
            key={meta.key}
            role="button"
            tabIndex={disabled ? -1 : 0}
            aria-pressed={isActive}
            aria-disabled={disabled}
            onClick={() => !disabled && onSelect(meta.key)}
            onKeyDown={(e) => {
              if (disabled) return
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onSelect(meta.key)
              }
            }}
            className={cn(
              'cursor-pointer border-slate-200 bg-white p-3 shadow-sm transition-colors',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400',
              isActive
                ? 'border-sky-500 bg-white ring-1 ring-sky-500/40'
                : 'hover:border-slate-300 hover:bg-slate-50',
              disabled && 'cursor-not-allowed opacity-60',
            )}
          >
            <p className="text-[11px] uppercase tracking-wide text-slate-500">
              {meta.question}
            </p>
            <p className="mt-0.5 text-sm font-semibold text-slate-900">{meta.label}</p>
            <p className="mt-1 font-mono text-[10px] text-slate-500">
              {meta.analytic_type}
            </p>
            {summary && (
              <p className="mt-2 text-xs tabular-nums text-slate-500">
                {formatValue(meta.key, summary.min)}
                <span className="mx-1 text-slate-500">→</span>
                {formatValue(meta.key, summary.max)}
              </p>
            )}
          </Card>
        )
      })}
    </div>
  )
}
