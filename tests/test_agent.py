"""The agent's decision points.

The happy path is exercised end-to-end by ``scripts/agent.py``. What matters here
are the branches that prove this is a policy and not a fixed sequence: stopping
early, degrading instead of failing, choosing between remedies, and enforcing its
own budget.
"""

from __future__ import annotations

import pytest

from cityvigil.agent import (
    HOURS_REMEDY_SUFFICIENT,
    NO_EVENT_HOURS,
    AgentBudget,
    HeatResponseAgent,
)
from cityvigil.geometry import MultiPolygon, Polygon
from cityvigil.layers import HeatSurface, Tile
from cityvigil.tools import Tool, ToolBox, ToolError, Trace
from cityvigil.tracts import Tract, TractCollection


# --------------------------------------------------------------------- trace


def test_trace_numbers_steps_and_groups_by_kind():
    t = Trace()
    t.add("decide", "first")
    t.add("call", "second", tool="x")
    t.add("call", "third", tool="x")
    assert [s.step for s in t] == [1, 2, 3]
    assert len(t.of_kind("call")) == 2
    assert t.tools_called() == {"x": 2}


def test_trace_renders_rationale_and_tool_args():
    t = Trace()
    t.add("call", "did a thing", rationale="because", tool="tool_a", args={"n": 1}, result="ok")
    text = t.render()
    assert "tool_a(n=1)" in text
    assert "-> ok" in text
    assert "why: because" in text


def test_trace_serialises():
    t = Trace()
    t.add("decide", "s", rationale="r")
    assert t.to_list()[0]["rationale"] == "r"


# ------------------------------------------------------------------ toolbox


def test_toolbox_registers_and_describes():
    box = ToolBox([Tool(name="a", answers="question a", run=lambda: 1, credits=10)])
    assert box.names == ["a"]
    assert "a" in box
    assert box.describe()[0]["answers"] == "question a"


def test_toolbox_rejects_duplicate_names():
    box = ToolBox([Tool(name="a", answers="q", run=lambda: 1)])
    with pytest.raises(ValueError, match="already registered"):
        box.register(Tool(name="a", answers="q", run=lambda: 2))


def test_unknown_tool_lists_alternatives():
    box = ToolBox([Tool(name="a", answers="q", run=lambda: 1)])
    with pytest.raises(ToolError, match="available: \\['a'\\]"):
        box.get("nope")


def test_tool_failure_is_traced_then_raised_for_the_policy_to_handle():
    def boom():
        raise RuntimeError("upstream down")

    box = ToolBox([Tool(name="bad", answers="q", run=boom)])
    trace = Trace()
    with pytest.raises(ToolError, match="upstream down"):
        box.invoke("bad", trace)
    recovered = trace.of_kind("recover")
    assert len(recovered) == 1
    assert "RuntimeError" in recovered[0].rationale


# ------------------------------------------------------------------- budget


def test_budget_blocks_spending_beyond_the_cap():
    b = AgentBudget(max_credits=5000)
    assert b.can_afford(4220)
    b.charge(4220)
    assert not b.can_afford(4220), "a second heatmap would exceed the cap"


def test_agent_refuses_to_start_with_no_credit_budget():
    agent = HeatResponseAgent(_client(_surface(80.0)), budget=AgentBudget(max_credits=0))
    result = agent.run("who needs help?")
    assert "budget exhausted" in result.recommendation
    assert result.trace.of_kind("budget"), "the stop must be visible in the trace"
    assert result.trace.tools_called() == {}, "no tool may be called"


# ---------------------------------------------------------------- fixtures


class _FakeClient:
    """Stands in for FortyGuardClient with a scripted surface."""

    def __init__(self, surface, fail_persistence=False):
        from cityvigil.audit import AuditLog

        self.audit = AuditLog()
        self._surface = surface
        self._fail_persistence = fail_persistence


def _surface(value: float, n: int = 4, analytic: str = "exceedance") -> HeatSurface:
    tiles = []
    for i in range(n):
        y = 33.44 + i * 0.001
        tiles.append(
            Tile(
                tile_id=i,
                geometry={
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-112.08, y],
                            [-112.079, y],
                            [-112.079, y + 0.001],
                            [-112.08, y + 0.001],
                            [-112.08, y],
                        ]
                    ],
                },
                value=value,
            )
        )
    return HeatSurface(
        analytic_type=analytic, units="hour", tiles=tiles, threshold_c=37.78,
        window={"start_date": "2024-07-15", "end_date": "2024-07-21", "filter_type": 4},
    )


def _client(surface):
    return _FakeClient(surface)


def _tracts() -> TractCollection:
    geom = MultiPolygon(
        (
            Polygon(
                (
                    (-112.081, 33.439),
                    (-112.078, 33.439),
                    (-112.078, 33.446),
                    (-112.081, 33.446),
                    (-112.081, 33.439),
                )
            ),
        )
    )
    t = Tract(
        geoid="04013000100", name="T1", geometry=geom, population=5000, age65=600,
        poverty150=1000, no_vehicle=250, disability=500, uninsured=500,
        svi_percentile=0.9, jobs_total=400, jobs_outdoor=80,
    )
    return TractCollection({t.geoid: t})


def _agent(surface, *, tracts=None, sites=None, budget=None) -> HeatResponseAgent:
    agent = HeatResponseAgent(
        _client(surface), tracts=tracts, sites=sites, budget=budget or AgentBudget()
    )
    # Patch the registered tools, not the methods: ToolBox captured bound
    # references at construction, so reassigning the methods has no effect.
    agent.toolbox.get("dangerous_hours").run = lambda city, threshold_f: surface
    agent.toolbox.get("relief_hours").run = (
        lambda city, threshold_f: _surface(7.0, len(surface.tiles))
    )
    return agent


# --------------------------------------------------- branch: no heat event


def test_agent_stops_early_when_there_is_no_heat_event():
    """A pipeline would rank noise; the agent declines to."""
    agent = _agent(_surface(0.0), tracts=_tracts(), sites=[])
    result = agent.run("who needs protecting?")

    assert result.findings["event"] is False
    assert "No action required" in result.recommendation
    concluded = result.trace.of_kind("conclude")
    assert concluded and "no heat event" in concluded[0].summary
    assert "rank_population" not in result.trace.tools_called()


def test_no_event_threshold_is_respected_at_the_boundary():
    below = _agent(_surface(NO_EVENT_HOURS - 0.01), tracts=_tracts(), sites=[])
    assert below.run("q").findings["event"] is False

    above = _agent(_surface(NO_EVENT_HOURS + 5.0), tracts=_tracts(), sites=[])
    assert "event" not in above.run("q").findings or above.run("q").findings.get("event") is not False


# ------------------------------------------- branch: degrade, do not fail


def test_agent_degrades_when_population_data_is_missing():
    """Missing tract data must not crash the run or invent a population layer."""
    agent = _agent(_surface(80.0), sites=[])

    def missing(**_):
        raise RuntimeError("tract sources not downloaded")

    agent.toolbox.get("rank_population").run = missing

    result = agent.run("who needs protecting?")
    assert "tract population data unavailable" in result.degraded
    assert "Population attribution unavailable" in result.recommendation
    assert result.findings["event"] is True
    assert result.trace.of_kind("recover"), "the failure must be visible"


def test_agent_degrades_when_cooling_supply_is_missing():
    agent = _agent(_surface(80.0), tracts=_tracts())

    def missing(**_):
        raise RuntimeError("no HRN data")

    agent.toolbox.get("measure_coverage").run = missing

    result = agent.run("who needs protecting?")
    assert "cooling-site data unavailable" in result.degraded
    assert "supply data was unavailable" in result.recommendation


def test_agent_continues_without_the_relief_layer():
    agent = _agent(_surface(80.0), tracts=_tracts(), sites=[])

    def missing(**_):
        raise RuntimeError("persistence unavailable")

    agent.toolbox.get("relief_hours").run = missing
    agent.toolbox.get("measure_coverage").run = lambda **_: _coverage(hours_share=0.9)
    agent.toolbox.get("simulate_longer_hours").run = lambda **_: _sim()

    result = agent.run("who needs protecting?")
    assert "persistence layer unavailable" in result.degraded
    assert result.recommendation, "it still reaches a recommendation"


# ------------------------------------------ branch: which remedy to pick


def _coverage(*, hours_share: float, tracts_total: int = 57, covered_at_peak: int = 14):
    uncovered = 1_000_000.0
    return {
        "hour": 19.0,
        "peak_hour": 15,
        "sites_open_now": 25,
        "sites_open_at_peak": 103,
        "uncovered_tracts": 52,
        "uncovered_person_hours": uncovered,
        "covered_at_peak": covered_at_peak,
        "tracts_total": tracts_total,
        "hours_gap_tracts": 9,
        "hours_gap_person_hours": uncovered * hours_share,
        "hours_gap_residents": 33_954,
    }


class _Sim:
    def __init__(self):
        from cityvigil.simulate import Intervention

        self.intervention = Intervention(
            kind="extend_hours", description="open 3 hour(s) later", added_site_hours=300.0
        )
        self.person_hours_gained = 900_000.0
        self.residents_gained = 33_954
        self.tracts_gained = 9

    def to_dict(self):
        return {
            "intervention": self.intervention.to_dict(),
            "gained": {"person_hours": self.person_hours_gained},
        }


def _sim():
    return _Sim()


def test_agent_recommends_the_cheap_fix_when_hours_dominate():
    """If closing times explain most of the gap, do not propose construction."""
    agent = _agent(_surface(80.0), tracts=_tracts(), sites=[])
    agent.toolbox.get("measure_coverage").run = lambda **_: _coverage(hours_share=0.8)
    agent.toolbox.get("simulate_longer_hours").run = lambda **_: _sim()

    called: list[str] = []
    agent.toolbox.get("plan_new_sites").run = lambda **_: called.append("planned") or []

    result = agent.run("cheapest way to protect people?")
    assert "Extend cooling-site hours" in result.recommendation
    assert "no capital cost" in result.recommendation
    assert called == [], "capacity planning must be skipped when hours suffice"


def test_agent_plans_capacity_when_distance_dominates():
    """If closing times explain little of the gap, the cheap fix is not enough."""
    agent = _agent(_surface(80.0), tracts=_tracts(), sites=[])
    agent.toolbox.get("measure_coverage").run = lambda **_: _coverage(hours_share=0.18)
    agent.toolbox.get("simulate_longer_hours").run = lambda **_: _sim()
    agent.toolbox.get("plan_new_sites").run = lambda **_: [
        {
            "order": 1,
            "target_geoid": "04013112700",
            "residents_gained": 7787,
            "person_hours_gained": 653_996.0,
        }
    ]

    result = agent.run("what should we do?")
    assert "Add cooling capacity" in result.recommendation
    observed = [s for s in result.trace.of_kind("observe") if "insufficient" in s.summary]
    assert observed, "the agent must state why the cheap fix was not enough"


def test_remedy_threshold_boundary_is_documented():
    assert 0.0 < HOURS_REMEDY_SUFFICIENT < 1.0


# --------------------------------------------------------------- reporting


def test_agent_reports_cleanly_when_the_primary_sensing_tool_fails():
    """Regression: an unavailable exposure layer crashed the run instead of
    reporting the blocker. It is the one failure with no workaround, so it must
    still produce a result rather than a traceback."""
    agent = _agent(_surface(80.0), tracts=_tracts(), sites=[])

    def unavailable(**_):
        raise RuntimeError("no cached response for that window")

    agent.toolbox.get("dangerous_hours").run = unavailable

    result = agent.run("who needs protecting?")
    assert "exposure query unavailable" in result.degraded
    assert "No assessment possible" in result.recommendation
    concluded = result.trace.of_kind("conclude")
    assert concluded and "cannot investigate" in concluded[0].summary
    assert result.trace.of_kind("recover"), "the failure must be visible in the trace"


def test_result_exposes_trace_and_tool_counts():
    agent = _agent(_surface(0.0), tracts=_tracts(), sites=[])
    payload = agent.run("q").to_dict()
    assert payload["steps"] > 0
    assert "trace" in payload and isinstance(payload["trace"], list)
    assert "tools_called" in payload
    assert payload["question"] == "q"


def test_every_decision_carries_a_rationale():
    """A decision without a reason is not auditable."""
    agent = _agent(_surface(80.0), tracts=_tracts(), sites=[])
    agent.toolbox.get("measure_coverage").run = lambda **_: _coverage(hours_share=0.8)
    agent.toolbox.get("simulate_longer_hours").run = lambda **_: _sim()

    result = agent.run("q")
    for step in result.trace.of_kind("decide"):
        assert step.rationale.strip(), f"step {step.step} has no rationale"
