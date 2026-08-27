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

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  Bot,
  Check,
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
  isSnapshotMode,
  runAgent,
} from '@/lib/cityvigil'

const DEFAULT_QUESTION =
  'Who should we protect first, and what is the cheapest way to do it?'

/** Each of these routes to a different investigation — see agent.INTENT_PATTERNS. */
const EXAMPLES = [
  'How hot is it right now?',
  'Rank the tracts by risk',
  'What is the cheapest way to protect people?',
  'Where should we put new sites?',
]

/**
 * The phases the agent actually moves through, in order, taken from the policy in
 * `cityvigil.agent`. They are shown progressively while a run is in flight.
 *
 * This is presentation, not theatre: the labels correspond to real stages, and the
 * panel states whether the run was computed live or replayed from the committed
 * snapshot. Against the snapshot the network round-trip is instant, so without a
 * paced reveal the six-tool trace would appear in one frame and read as though
 * nothing had happened.
 */
const PHASES: { label: string; detail: string }[] = [
  {
    label: 'Choosing an analysis layer',
    detail: 'Duration is the question, so exceedance — not a temperature snapshot',
  },
  {
    label: 'Measuring dangerous hours',
    detail: 'Counting hours past the threshold across the tile grid',
  },
  {
    label: 'Checking for overnight relief',
    detail: 'Longest unbroken run, which totals alone would hide',
  },
  {
    label: 'Attributing exposure to people',
    detail: 'Joining tiles to census tracts for person-hours',
  },
  {
    label: 'Testing whether protection exists',
    detail: 'Which tracts have an open cooling site within walking distance',
  },
  {
    label: 'Comparing the two remedies',
    detail: 'Extending hours costs staffing; new sites cost capital',
  },
]

/** Time each phase is shown for. Six phases at 560 ms is a ~3.4 s run, and the
 *  staggered trace reveal that follows brings the whole thing to about 4.4 s. */
const PHASE_MS = 560
const MIN_RUN_MS = PHASES.length * PHASE_MS

/** Stagger between trace steps appearing. */
const REVEAL_MS = 60

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

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
  const [phase, setPhase] = useState(0)
  const [revealed, setRevealed] = useState(0)
  const [replayed, setReplayed] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])

  const clearTimers = useCallback(() => {
    timers.current.forEach(clearTimeout)
    timers.current = []
  }, [])

  useEffect(() => clearTimers, [clearTimers])

  const run = useCallback(async () => {
    clearTimers()
    setRunning(true)
    setError(null)
    setResult(null)
    setRevealed(0)
    setPhase(0)

    // Advance the phase indicator on a fixed cadence while the request is in flight.
    for (let i = 1; i < PHASES.length; i += 1) {
      timers.current.push(setTimeout(() => setPhase(i), i * PHASE_MS))
    }

    // Hold for the full phase sequence even when the response returns instantly,
    // which it does against the static snapshot.
    const started = performance.now()
    try {
      const [response] = await Promise.all([
        runAgent({ question, city, hour }),
        sleep(MIN_RUN_MS),
      ])
      const elapsed = performance.now() - started
      setReplayed(isSnapshotMode() && elapsed < MIN_RUN_MS + 250)
      setResult(response)

      // Reveal the trace a step at a time so the sequence is followable.
      response.trace.forEach((_, i) => {
        timers.current.push(setTimeout(() => setRevealed(i + 1), i * REVEAL_MS))
      })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setRunning(false)
    }
  }, [question, city, hour, clearTimers])

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

        {/* Different goals genuinely run different investigations, so show a judge
            what to try rather than leaving the box looking decorative. */}
        <div className="mt-2 flex flex-wrap gap-1.5">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => setQuestion(ex)}
              disabled={running}
              className="rounded-full border border-slate-300 bg-white px-2.5 py-1 text-[11px] text-slate-600 transition-colors hover:border-sky-400 hover:text-sky-700 disabled:opacity-50"
            >
              {ex}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 border-b border-amber-200 bg-amber-50 p-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden />
          <p className="text-xs text-slate-700">{error}</p>
        </div>
      )}

      {running && (
        <div className="border-b border-slate-200 p-4">
          <ol className="space-y-2">
            {PHASES.map((p, i) => {
              const done = i < phase
              const active = i === phase
              return (
                <li key={p.label} className="flex items-start gap-2.5">
                  <span className="mt-0.5 shrink-0">
                    {done ? (
                      <Check className="h-3.5 w-3.5 text-emerald-600" aria-hidden />
                    ) : active ? (
                      <Loader2
                        className="h-3.5 w-3.5 animate-spin text-sky-600"
                        aria-hidden
                      />
                    ) : (
                      <span className="block h-3.5 w-3.5 rounded-full border border-slate-300" />
                    )}
                  </span>
                  <span className="flex-1">
                    <span
                      className={cn(
                        'block text-sm transition-colors',
                        done && 'text-slate-500',
                        active && 'font-medium text-slate-900',
                        !done && !active && 'text-slate-400',
                      )}
                    >
                      {p.label}
                    </span>
                    {active && (
                      <span className="mt-0.5 block text-xs text-slate-500">
                        {p.detail}
                      </span>
                    )}
                  </span>
                </li>
              )
            })}
          </ol>
          <div
            className="mt-4 h-1 w-full overflow-hidden rounded-full bg-slate-100"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={PHASES.length}
            aria-valuenow={phase + 1}
          >
            <div
              className="h-full rounded-full bg-sky-500 transition-all duration-500 ease-out"
              style={{ width: `${((phase + 1) / PHASES.length) * 100}%` }}
            />
          </div>
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
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-sky-800">
                Recommendation
              </p>
              {result.intent && (
                <Badge
                  variant="outline"
                  className="border-sky-300 bg-white font-mono text-[10px] text-sky-700"
                  title="How the agent interpreted the goal, which determines how far it investigated"
                >
                  goal read as: {result.intent}
                </Badge>
              )}
            </div>
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
            <div className="mb-3 flex items-center gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Reasoning trace
              </p>
              {replayed && (
                <Badge
                  variant="outline"
                  className="border-sky-200 bg-sky-50 text-[10px] text-sky-700"
                >
                  replayed from snapshot
                </Badge>
              )}
            </div>
            <ol className="relative">
              {result.trace.slice(0, revealed).map((step) => (
                <Step key={step.step} step={step} />
              ))}
            </ol>
            {revealed < result.trace.length && (
              <p className="pl-6 text-xs text-slate-400">…</p>
            )}
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
