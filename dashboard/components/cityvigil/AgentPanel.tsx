'use client'

/**
 * The agent's reasoning, made visible.
 *
 * For the Agentic AI track this panel is the deliverable, not decoration. It shows
 * the decisions in the order they were taken, each with the reason recorded before
 * the call it justifies — so a reviewer can check that the agent chose the right
 * layer for the right stated reason, and can see where it branched.
 *
 * The planner is a deterministic policy rather than an LLM, and the panel says so.
 * Overstating what is under the hood would undermine the same trail it is showing.
 */

import { useCallback, useState } from 'react'
import {
  AlertTriangle,
  Bot,
  ChevronDown,
  ChevronRight,
  Cpu,
  Loader2,
  Play,
  Wrench,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import {
  type AgentResponse,
  type TraceStep,
  ApiError,
  TRACE_STYLE,
  runAgent,
} from '@/lib/cityvigil'

const DEFAULT_QUESTION =
  'Who should we protect first, and what is the cheapest way to do it?'

interface AgentPanelProps {
  city: string
  hour?: number
}

function Step({ step }: { step: TraceStep }) {
  const style = TRACE_STYLE[step.kind] ?? TRACE_STYLE.call
  const [open, setOpen] = useState(step.kind === 'decide' || step.kind === 'conclude')
  const hasDetail = Boolean(step.rationale || step.tool || step.result)

  return (
    <li className="relative pl-6">
      {/* timeline rail */}
      <span
        className={cn('absolute left-0 top-2 h-2 w-2 rounded-full', style.rail)}
        aria-hidden
      />
      <span className="absolute left-[3px] top-4 h-full w-px bg-slate-200" aria-hidden />

      <div className="pb-4">
        <button
          type="button"
          onClick={() => hasDetail && setOpen((o) => !o)}
          aria-expanded={open}
          className={cn(
            'flex w-full items-start gap-2 text-left',
            hasDetail && 'cursor-pointer',
          )}
        >
          <Badge
            variant="outline"
            className={cn('mt-0.5 shrink-0 text-[10px] font-medium', style.badge)}
          >
            {style.label}
          </Badge>
          <span className="flex-1 text-sm text-slate-800">{step.summary}</span>
          <span className="mt-0.5 shrink-0 font-mono text-[10px] text-slate-400">
            {step.step}
          </span>
          {hasDetail &&
            (open ? (
              <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
            ) : (
              <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
            ))}
        </button>

        {open && hasDetail && (
          <div className="mt-2 space-y-2 border-l-2 border-slate-200 pl-3">
            {step.tool && (
              <p className="font-mono text-[11px] text-slate-600">
                {step.tool}(
                {Object.entries(step.args)
                  .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                  .join(', ')}
                )
              </p>
            )}
            {step.result && (
              <p className="text-xs text-slate-700">
                <span className="text-slate-400">→ </span>
                {step.result}
              </p>
            )}
            {step.rationale && (
              <p className="text-xs leading-relaxed text-slate-600">
                <span className="font-medium text-slate-500">why: </span>
                {step.rationale}
              </p>
            )}
          </div>
        )}
      </div>
    </li>
  )
}

export function AgentPanel({ city, hour = 19 }: AgentPanelProps) {
  const [question, setQuestion] = useState(DEFAULT_QUESTION)
  const [result, setResult] = useState<AgentResponse | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(async () => {
    setRunning(true)
    setError(null)
    try {
      setResult(await runAgent({ question, city, hour }))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setRunning(false)
    }
  }, [question, city, hour])

  const decisions = result?.trace.filter((s) => s.kind === 'decide').length ?? 0
  const recoveries = result?.trace.filter((s) => s.kind === 'recover').length ?? 0

  return (
    <Card className="border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 p-3">
        <Bot className="h-4 w-4 text-sky-600" aria-hidden />
        <h2 className="text-sm font-semibold text-slate-900">Agent</h2>
        <span className="text-xs text-slate-500">
          decides what to investigate, then what to recommend
        </span>
        <Button
          onClick={() => void run()}
          disabled={running}
          size="sm"
          className="ml-auto bg-sky-600 text-white hover:bg-sky-700"
        >
          {running ? (
            <>
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" aria-hidden />
              Reasoning…
            </>
          ) : (
            <>
              <Play className="mr-2 h-3.5 w-3.5" aria-hidden />
              Run agent
            </>
          )}
        </Button>
      </div>

      <div className="border-b border-slate-200 p-3">
        <label htmlFor="agent-question" className="text-[11px] uppercase tracking-wide text-slate-500">
          Goal
        </label>
        <input
          id="agent-question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
          placeholder="Ask the agent something"
        />
        <p className="mt-1.5 text-[11px] text-slate-500">
          Evaluated at {hour}:00 local — the hour when heat is still dangerous but much
          of the cooling network has closed.
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2 border-b border-amber-200 bg-amber-50 p-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden />
          <p className="text-xs text-slate-700">{error}</p>
        </div>
      )}

      {!result && !running && !error && (
        <div className="p-6 text-center">
          <p className="text-sm text-slate-600">
            Run the agent to see every decision it makes and why.
          </p>
          <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-slate-500">
            It picks the analysis layer that answers the question, stops early if there
            is no heat event, degrades rather than fails when a data source is missing,
            and chooses between extending hours and adding sites based on which one the
            gap actually calls for.
          </p>
        </div>
      )}

      {result && (
        <>
          {/* The answer */}
          <div className="border-b border-slate-200 bg-sky-50/60 p-4">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-sky-800">
              Recommendation
            </p>
            <p className="mt-1 text-sm leading-relaxed text-slate-800">
              {result.recommendation}
            </p>
            {result.degraded.length > 0 && (
              <p className="mt-2 text-xs text-amber-700">
                Ran with reduced information: {result.degraded.join('; ')}
              </p>
            )}
          </div>

          {/* How it got there */}
          <div className="grid grid-cols-2 gap-2 border-b border-slate-200 p-3 sm:grid-cols-4">
            {[
              { label: 'Steps', value: String(result.steps) },
              { label: 'Decisions', value: String(decisions) },
              { label: 'Recoveries', value: String(recoveries) },
              { label: 'Credits', value: result.credits_spent.toLocaleString() },
            ].map((s) => (
              <div key={s.label}>
                <p className="text-[10px] uppercase tracking-wide text-slate-500">
                  {s.label}
                </p>
                <p className="text-sm font-semibold tabular-nums text-slate-900">
                  {s.value}
                </p>
              </div>
            ))}
          </div>

          {/* Trace */}
          <div className="max-h-[30rem] overflow-y-auto p-4">
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              Reasoning trace
            </p>
            <ol className="relative">
              {result.trace.map((step) => (
                <Step key={step.step} step={step} />
              ))}
            </ol>
          </div>

          {/* What it can do, and what it is */}
          <div className="space-y-2 border-t border-slate-200 bg-slate-50 p-3">
            <div className="flex items-start gap-2">
              <Wrench className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" aria-hidden />
              <div className="flex flex-wrap gap-1.5">
                {result.capabilities.map((c) => (
                  <Badge
                    key={c.name}
                    variant="outline"
                    className={cn(
                      'font-mono text-[10px]',
                      result.tools_called[c.name]
                        ? 'border-sky-300 bg-sky-50 text-sky-700'
                        : 'border-slate-300 text-slate-500',
                    )}
                    title={`${c.answers} — ${c.credits ? `${c.credits.toLocaleString()} credits` : 'no API cost'}`}
                  >
                    {c.name}
                    {result.tools_called[c.name] ? ` ×${result.tools_called[c.name]}` : ''}
                  </Badge>
                ))}
              </div>
            </div>
            <div className="flex items-start gap-2">
              <Cpu className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" aria-hidden />
              <p className="text-[11px] leading-relaxed text-slate-600">{result.planner}</p>
            </div>
          </div>
        </>
      )}
    </Card>
  )
}
