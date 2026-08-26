"""The CityVigil agent: sense, judge, branch, and stop.

The loop is not a fixed sequence. At each stage the policy inspects what it has
observed and decides what to do next, and the decision is recorded with its reason
before the call is made. The branch points that matter:

1. **Is there anything to act on?** If mean exceedance is at or near zero for the
   window, there is no heat event; the agent concludes and spends nothing further.
   A pipeline would carry on and produce a confident ranking of nothing.
2. **Can it characterise who is affected?** If tract data is missing, it degrades
   to an exposure-only answer and says so, instead of failing.
3. **Which remedy fits the diagnosis?** After measuring coverage it compares the
   hours gap against the siting gap and simulates the one that matches — extending
   hours when closing times are the binding constraint, planning sites when
   distance is. This is the decision with real consequences: one remedy costs
   staffing, the other costs capital.
4. **Is the cheap fix enough?** If extending hours closes most of the gap, it says
   so rather than also recommending construction.

Budgets are enforced by the agent, not by the caller: it tracks steps and
estimated credits and stops with an explicit ``budget`` trace entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .audit import AuditLog
from .cities import City, get_city
from .exposure import ExposureReport, assign_tiles, build_exposure_report
from .fg_client import FortyGuardClient
from .layers import ExposureLayers
from .simulate import greedy_site_placement, simulate_extended_hours
from .supply import CoolingSite, coverage_for_tracts, load_sites, open_site_count_by_hour
from .tools import Tool, ToolBox, ToolError, Trace
from .tracts import TractCollection, load_tracts
from .vulnerability import VulnerabilityModel

#: Below this mean exceedance, the window holds no heat event worth planning for.
NO_EVENT_HOURS = 1.0

#: If extending hours recovers at least this share of the uncovered person-hours,
#: the agent treats the cheap remedy as sufficient and does not also propose sites.
HOURS_REMEDY_SUFFICIENT = 0.5


@dataclass
class AgentBudget:
    """Limits the agent enforces on itself."""

    max_steps: int = 24
    max_credits: int = 40_000
    spent_credits: int = 0

    def can_afford(self, credits: int) -> bool:
        return self.spent_credits + credits <= self.max_credits

    def charge(self, credits: int) -> None:
        self.spent_credits += credits


@dataclass
class AgentResult:
    """What the agent concluded, and the trace that got it there."""

    question: str
    city: str
    trace: Trace
    findings: dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""
    degraded: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "city": self.city,
            "recommendation": self.recommendation,
            "findings": self.findings,
            "degraded": self.degraded,
            "trace": self.trace.to_list(),
            "tools_called": self.trace.tools_called(),
            "steps": len(self.trace),
        }


class HeatResponseAgent:
    """Decides what to investigate, what it means, and what to recommend."""

    def __init__(
        self,
        client: FortyGuardClient,
        *,
        tracts: TractCollection | None = None,
        sites: list[CoolingSite] | None = None,
        budget: AgentBudget | None = None,
        audit: AuditLog | None = None,
    ) -> None:
        self.client = client
        self.layers = ExposureLayers(client)
        self.budget = budget or AgentBudget()
        self.audit = audit if audit is not None else client.audit
        self._tracts = tracts
        self._sites = sites
        self.toolbox = self._build_toolbox()

    # ------------------------------------------------------------- tools

    def _build_toolbox(self) -> ToolBox:
        return ToolBox(
            [
                Tool(
                    name="dangerous_hours",
                    answers="how many hours a place spends past a danger threshold",
                    run=self._tool_dangerous_hours,
                    credits=4220,
                ),
                Tool(
                    name="relief_hours",
                    answers="whether dangerous heat ever breaks, as an unbroken run",
                    run=self._tool_relief_hours,
                    credits=4220,
                ),
                Tool(
                    name="rank_population",
                    answers="which neighbourhoods hold the most vulnerable exposed people",
                    run=self._tool_rank_population,
                    credits=0,
                ),
                Tool(
                    name="measure_coverage",
                    answers="who has an open cooling site within walking distance",
                    run=self._tool_measure_coverage,
                    credits=0,
                ),
                Tool(
                    name="simulate_longer_hours",
                    answers="what extending cooling-site hours would recover",
                    run=self._tool_simulate_hours,
                    credits=0,
                ),
                Tool(
                    name="plan_new_sites",
                    answers="where new cooling capacity should go first",
                    run=self._tool_plan_sites,
                    credits=0,
                ),
            ]
        )

    def _tool_dangerous_hours(self, city: City, threshold_f: float):
        return self.layers.how_long_dangerous(
            city.aoi,
            threshold=threshold_f,
            threshold_unit="F",
            start_date=city.episode_start,
            end_date=city.episode_end,
        )

    def _tool_relief_hours(self, city: City, threshold_f: float):
        return self.layers.any_relief(
            city.aoi,
            threshold=threshold_f,
            threshold_unit="F",
            start_date=city.episode_start,
            end_date=city.episode_end,
        )

    def _tool_rank_population(self, exceedance, persistence=None) -> ExposureReport:
        tracts = self.tracts()
        return build_exposure_report(
            exceedance,
            tracts,
            VulnerabilityModel(tracts),
            persistence=persistence,
            assignment=assign_tiles(exceedance, tracts),
        )

    def _tool_measure_coverage(self, report: ExposureReport, hour: float):
        sites = self.sites()
        cover = coverage_for_tracts(
            (e.tract for e in report.tracts), sites, hour=hour
        )
        uncovered = [e for e in report.tracts if not cover[e.tract.geoid].walkable_cover]
        counts = open_site_count_by_hour(sites)
        peak_hour = max(counts, key=lambda h: counts[h])

        at_peak = coverage_for_tracts(
            (e.tract for e in report.tracts), sites, hour=float(peak_hour)
        )
        lost_to_hours = [
            e
            for e in report.tracts
            if at_peak[e.tract.geoid].walkable_cover
            and not cover[e.tract.geoid].walkable_cover
        ]
        return {
            "hour": hour,
            "peak_hour": peak_hour,
            "sites_open_now": counts[int(hour)],
            "sites_open_at_peak": counts[peak_hour],
            "uncovered_tracts": len(uncovered),
            "uncovered_person_hours": sum(e.person_hours for e in uncovered),
            "covered_at_peak": sum(
                1 for e in report.tracts if at_peak[e.tract.geoid].walkable_cover
            ),
            "tracts_total": len(report.tracts),
            "hours_gap_tracts": len(lost_to_hours),
            "hours_gap_person_hours": sum(e.person_hours for e in lost_to_hours),
            "hours_gap_residents": sum(e.tract.population for e in lost_to_hours),
        }

    def _tool_simulate_hours(self, report: ExposureReport, hour: float, extra: float):
        return simulate_extended_hours(
            report.tracts, self.sites(), extra_hours=extra, hour=hour
        )

    def _tool_plan_sites(self, report: ExposureReport, hour: float, budget: int):
        return greedy_site_placement(
            report.tracts, self.sites(), budget=budget, hour=hour
        )

    # --------------------------------------------------------- lazy data

    def tracts(self) -> TractCollection:
        if self._tracts is None:
            self._tracts = load_tracts(download=False)
        return self._tracts

    def sites(self) -> list[CoolingSite]:
        if self._sites is None:
            self._sites = load_sites(download=False)
        return self._sites

    # ------------------------------------------------------------- loop

    def run(
        self,
        question: str,
        *,
        city_key: str = "phoenix",
        evening_hour: float = 19.0,
        threshold_f: float | None = None,
    ) -> AgentResult:
        """Investigate a question and decide what to recommend."""
        trace = Trace()
        city = get_city(city_key)
        threshold = threshold_f if threshold_f is not None else city.danger_threshold_f
        result = AgentResult(question=question, city=city.key, trace=trace)

        trace.add(
            "decide",
            f"goal accepted: {question}",
            rationale=(
                f"Study area {city.name}, window {city.episode_start} to "
                f"{city.episode_end}, danger threshold {threshold:.0f} F. "
                f"{len(self.toolbox)} tools available, budget "
                f"{self.budget.max_credits:,} credits."
            ),
        )

        # ── 1. Establish whether there is a heat event at all ───────────────
        tool = self.toolbox.get("dangerous_hours")
        if not self.budget.can_afford(tool.credits):
            trace.add("budget", "stopping before the first query", rationale="credit budget exhausted")
            result.recommendation = "No investigation performed: credit budget exhausted."
            return result

        trace.add(
            "decide",
            "measure exposure duration first",
            rationale=(
                "The question concerns who to protect, which depends on how long "
                "conditions stay dangerous. Only the exceedance layer answers that "
                "in hours; a temperature snapshot returns degrees and cannot be "
                "multiplied by population."
            ),
        )
        try:
            exceedance = self.toolbox.invoke(
                "dangerous_hours", trace, city=city, threshold_f=threshold
            )
        except ToolError as exc:
            # The primary sensing tool is the one failure the agent cannot work
            # around: without exposure there is nothing to reason about. It still
            # has to report that cleanly rather than crash.
            trace.add(
                "conclude",
                "cannot investigate: exposure query unavailable",
                rationale=(
                    "The exceedance layer is the only source of dangerous-hour counts, "
                    "and no other tool can substitute for it. Reporting the blocker "
                    "instead of guessing."
                ),
            )
            result.degraded.append("exposure query unavailable")
            result.findings = {"error": str(exc)}
            result.recommendation = (
                f"No assessment possible: the exposure query failed ({exc}). "
                f"In replay mode this usually means the requested window or threshold "
                f"is not in the committed cache — re-run with "
                f"CITYVIGIL_CACHE_MODE=live to fetch it."
            )
            return result

        self.budget.charge(tool.credits)
        mean_hours = sum(exceedance.values) / len(exceedance)
        trace.add(
            "call",
            "queried cumulative dangerous hours",
            tool="dangerous_hours",
            args={"city": city.key, "threshold_f": threshold},
            result=f"{len(exceedance):,} tiles, mean {mean_hours:.1f} h past threshold",
        )

        # Branch: nothing to act on.
        if mean_hours <= NO_EVENT_HOURS:
            trace.add(
                "conclude",
                "no heat event in this window",
                rationale=(
                    f"Mean exceedance {mean_hours:.2f} h is at or below the "
                    f"{NO_EVENT_HOURS} h floor, so there is no sustained dangerous "
                    f"period to allocate against. Stopping rather than ranking noise."
                ),
            )
            result.findings = {"mean_exceedance_h": round(mean_hours, 2), "event": False}
            result.recommendation = (
                "No action required: the window contains no sustained period above "
                "the danger threshold."
            )
            return result

        trace.add(
            "observe",
            "heat event confirmed",
            rationale=f"Mean {mean_hours:.1f} h past {threshold:.0f} F over the window.",
        )

        # ── 2. Add the relief signal, since totals hide overnight non-relief ─
        persistence = None
        relief_tool = self.toolbox.get("relief_hours")
        if self.budget.can_afford(relief_tool.credits):
            trace.add(
                "decide",
                "also measure unbroken duration",
                rationale=(
                    "Total hours and longest unbroken run are both in hours and are "
                    "not interchangeable. Two blocks can log identical totals while "
                    "one cools overnight and the other never does; mortality tracks "
                    "the second."
                ),
            )
            try:
                persistence = self.toolbox.invoke(
                    "relief_hours", trace, city=city, threshold_f=threshold
                )
                self.budget.charge(relief_tool.credits)
                trace.add(
                    "call",
                    "queried longest unbroken dangerous run",
                    tool="relief_hours",
                    args={"city": city.key, "threshold_f": threshold},
                    result=f"max {max(persistence.values):.1f} h unbroken",
                )
            except ToolError:
                result.degraded.append("persistence layer unavailable")
                trace.add(
                    "recover",
                    "continuing without the relief signal",
                    rationale="Exposure totals are still usable; the answer loses the "
                    "overnight-relief nuance and that is reported.",
                )
        else:
            trace.add("budget", "skipping the relief layer", rationale="credit budget")

        # ── 3. Characterise who is exposed, degrading if data is missing ────
        report: ExposureReport | None = None
        trace.add(
            "decide",
            "attribute exposure to population",
            rationale=(
                "Hours alone cannot rank neighbourhoods. Multiplying by residents "
                "gives person-hours in the API's own units."
            ),
        )
        try:
            report = self.toolbox.invoke(
                "rank_population", trace, exceedance=exceedance, persistence=persistence
            )
            totals = report.totals()
            trace.add(
                "call",
                "ranked tracts by vulnerability-weighted person-hours",
                tool="rank_population",
                args={"tracts": totals["n_tracts"]},
                result=(
                    f"{totals['n_tracts']} tracts, {totals['population']:,} residents, "
                    f"{totals['person_hours']:,.0f} person-hours"
                ),
            )
        except ToolError:
            result.degraded.append("tract population data unavailable")
            trace.add(
                "conclude",
                "exposure-only answer",
                rationale=(
                    "Population data could not be loaded, so the agent cannot say who "
                    "is affected. Reporting exposure alone rather than inventing a "
                    "population layer."
                ),
            )
            result.findings = {
                "mean_exceedance_h": round(mean_hours, 2),
                "max_exceedance_h": round(max(exceedance.values), 2),
                "event": True,
            }
            result.recommendation = (
                f"Sustained dangerous heat confirmed (mean {mean_hours:.1f} h past "
                f"{threshold:.0f} F). Population attribution unavailable — run "
                f"scripts/fetch_data.py to enable prioritisation."
            )
            return result

        # ── 4. Measure coverage, then branch on the cause of the gap ────────
        trace.add(
            "decide",
            f"test whether protection exists at {evening_hour:g}:00",
            rationale=(
                "A cooling site that has closed protects nobody. Coverage must be "
                "evaluated at an hour when it is still dangerous outside, not at the "
                "network's daytime peak."
            ),
        )
        try:
            coverage = self.toolbox.invoke(
                "measure_coverage", trace, report=report, hour=evening_hour
            )
        except ToolError:
            result.degraded.append("cooling-site data unavailable")
            trace.add(
                "conclude",
                "demand-only answer",
                rationale="Supply data missing, so unmet need cannot be separated from need.",
            )
            top = report.ranked(5)
            result.findings = {"top_tracts": [e.tract.geoid for e in top]}
            result.recommendation = (
                "Prioritise the highest-ranked tracts; cooling-site supply data was "
                "unavailable so coverage gaps could not be assessed."
            )
            return result

        trace.add(
            "call",
            "measured walkable coverage",
            tool="measure_coverage",
            args={"hour": evening_hour},
            result=(
                f"{coverage['sites_open_now']} of {coverage['sites_open_at_peak']} sites "
                f"still open; {coverage['uncovered_tracts']} of "
                f"{coverage['tracts_total']} tracts uncovered"
            ),
        )

        hours_gap = coverage["hours_gap_person_hours"]
        uncovered = coverage["uncovered_person_hours"]
        siting_only = coverage["tracts_total"] - coverage["covered_at_peak"]
        share = (hours_gap / uncovered) if uncovered > 0 else 0.0

        trace.add(
            "observe",
            "gap decomposed into two causes",
            rationale=(
                f"{coverage['hours_gap_tracts']} tracts have walkable cooling at "
                f"{coverage['peak_hour']}:00 and lose it by {evening_hour:g}:00 "
                f"({hours_gap:,.0f} person-hours). {siting_only} tracts have none even "
                f"at peak. The first is a schedule problem, the second is a "
                f"construction problem, and they must not be added together."
            ),
        )

        # The consequential branch: which remedy to cost out.
        if coverage["hours_gap_tracts"] > 0:
            trace.add(
                "decide",
                "cost the schedule fix before the capital fix",
                rationale=(
                    "Part of the gap is caused by closing times, which can be closed "
                    "with staffing rather than construction. The cheaper remedy is "
                    "evaluated first so it is not overlooked."
                ),
            )
            best = None
            for extra in (1.0, 2.0, 3.0, 4.0):
                sim = self.toolbox.invoke(
                    "simulate_longer_hours", trace, report=report, hour=evening_hour, extra=extra
                )
                if best is None or sim.person_hours_gained > best.person_hours_gained:
                    best = sim
            assert best is not None
            trace.add(
                "call",
                "simulated hour extensions of 1-4 hours",
                tool="simulate_longer_hours",
                args={"hour": evening_hour},
                result=(
                    f"best: {best.intervention.description} recovers "
                    f"{best.person_hours_gained:,.0f} person-hours for "
                    f"{best.residents_gained:,} residents"
                ),
            )
            result.findings["hours_remedy"] = best.to_dict()

            if share >= HOURS_REMEDY_SUFFICIENT:
                trace.add(
                    "conclude",
                    "schedule change is the primary recommendation",
                    rationale=(
                        f"Closing times account for {share:.0%} of uncovered "
                        f"person-hours, so extending hours addresses most of the gap "
                        f"without capital spend. Not proposing new sites as the lead "
                        f"action."
                    ),
                )
                result.recommendation = (
                    f"Extend cooling-site hours: {best.intervention.description}. "
                    f"Recovers {best.person_hours_gained:,.0f} person-hours across "
                    f"{best.tracts_gained} tracts ({best.residents_gained:,} residents) "
                    f"for {best.intervention.added_site_hours:,.0f} additional "
                    f"site-hours of staffing and no capital cost."
                )
                result.findings["coverage"] = coverage
                return result

            trace.add(
                "observe",
                "schedule change alone is insufficient",
                rationale=(
                    f"Closing times explain only {share:.0%} of uncovered "
                    f"person-hours; the remainder is distance. Both remedies needed."
                ),
            )

        # ── 5. Siting gap dominates: plan capacity ─────────────────────────
        trace.add(
            "decide",
            "plan new cooling capacity",
            rationale=(
                f"{siting_only} of {coverage['tracts_total']} tracts have no walkable "
                f"site even when the network is at full capacity, so no schedule "
                f"change can reach them. Placing greedily by marginal gain gives a "
                f"usable priority order under a limited budget."
            ),
        )
        plan = self.toolbox.invoke(
            "plan_new_sites", trace, report=report, hour=evening_hour, budget=5
        )
        gained = sum(p["person_hours_gained"] for p in plan)
        trace.add(
            "call",
            "planned pop-up cooling sites",
            tool="plan_new_sites",
            args={"hour": evening_hour, "budget": 5},
            result=f"{len(plan)} sites recovering {gained:,.0f} person-hours",
        )
        result.findings["site_plan"] = plan
        result.findings["coverage"] = coverage

        trace.add(
            "conclude",
            "combined recommendation",
            rationale=(
                "Distance is the dominant constraint, so capacity is the lead action, "
                "with the schedule change retained where it helps."
            ),
        )
        lead = plan[0] if plan else None
        result.recommendation = (
            (
                f"Add cooling capacity: {len(plan)} pop-up sites recover "
                f"{gained:,.0f} person-hours, starting with tract "
                f"{lead['target_geoid']} ({lead['residents_gained']:,} residents). "
                if lead
                else "No further capacity placement improves coverage. "
            )
            + (
                f"Also extend hours where sites already exist "
                f"({result.findings['hours_remedy']['gained']['person_hours']:,.0f} "
                f"person-hours, no capital cost)."
                if "hours_remedy" in result.findings
                else ""
            )
        )
        return result
