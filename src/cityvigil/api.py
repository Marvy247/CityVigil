"""HTTP API that the dashboard consumes.

Security note
-------------
This service has **no authentication**. It is intended to be bound to localhost
for development and demo recording only. Do not expose it publicly as-is: the
FortyGuard API key lives in this process, so an open instance lets anyone spend
your credits. If it ever needs to be reachable, put an authenticating proxy in
front of it and add per-IP rate limiting.

Behaviour
---------
Every endpoint is cache-backed, so repeated requests from the UI cost nothing and
return instantly. With ``CITYVIGIL_CACHE_MODE=replay`` the whole API serves from
committed responses with no key at all, which is how a judge runs the demo.
"""

from __future__ import annotations

import os

from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agent import AgentBudget, HeatResponseAgent
from .audit import AuditLog
from .cities import CITIES, get_city
from .config import Settings
from .errors import CacheMiss, CityVigilError, ValidationError
from .exposure import ExposureReport, assign_tiles, build_exposure_report
from .fg_client import FortyGuardClient
from .layers import TIME_OF_MEASURE_NOTE, ExposureLayers, HeatSurface
from .simulate import greedy_site_placement, simulate_extended_hours
from .sources import SOURCES, citations, load_manifest
from .supply import (
    CoolingSite,
    SupplyDataError,
    coverage_for_tracts,
    load_sites,
    open_site_count_by_hour,
    supply_summary,
)
from .tracts import TractCollection, TractDataError, load_tracts
from .vulnerability import VulnerabilityModel, Weights

LayerName = Literal["snapshot", "peak_hour", "exceedance", "persistence"]

#: Which intent method serves each UI-facing layer name, and how to label it.
LAYER_META: dict[str, dict[str, str]] = {
    "snapshot": {
        "label": "Snapshot temperature",
        "analytic_type": "tcm",
        "unit_label": "°C",
        "question": "How hot is it?",
    },
    "peak_hour": {
        "label": "Peak hour",
        "analytic_type": "time_of_measure",
        "unit_label": "hour (local)",
        "question": "When does it peak?",
        "note": TIME_OF_MEASURE_NOTE,
    },
    "exceedance": {
        "label": "Dangerous hours",
        "analytic_type": "exceedance",
        "unit_label": "hours",
        "question": "How long is it dangerous?",
    },
    "persistence": {
        "label": "Longest unbroken stretch",
        "analytic_type": "persistence",
        "unit_label": "hours",
        "question": "Is there any relief?",
    },
}

app = FastAPI(
    title="CityVigil API",
    version="0.1.0",
    description="Heat exposure surfaces from the FortyGuard Temperature API, with a full audit trail.",
)

# Origins allowed to call this API. The dashboard runs on :3000 in development;
# add a deployed origin via CITYVIGIL_ALLOWED_ORIGINS (comma-separated) rather than
# widening this to "*", which would let any site drive an instance holding a key.
_default_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
_extra_origins = [
    o.strip()
    for o in (os.getenv("CITYVIGIL_ALLOWED_ORIGINS") or "").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins + _extra_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_settings = Settings.from_env()
_audit = AuditLog()
_client = FortyGuardClient(_settings, audit=_audit)
_layers = ExposureLayers(_client)


# ------------------------------------------------------------------- schemas


class SurfaceRequest(BaseModel):
    """A request for one or more exposure surfaces over a study area."""

    city: str = Field(default="phoenix", description="Study-area key")
    layers: list[LayerName] = Field(
        default=["snapshot", "exceedance", "persistence"],
        description="Which surfaces to compute",
    )
    start_date: str | None = Field(default=None, description="YYYY-MM-DD; defaults to the city's episode start")
    end_date: str | None = Field(default=None, description="YYYY-MM-DD; defaults to the city's episode end")
    threshold_f: float | None = Field(default=None, description="Danger threshold in Fahrenheit")
    granularity: int = Field(default=100, description="Tile size in metres: 60, 80 or 100")


class ExposureRequest(BaseModel):
    """A request for the vulnerability-weighted person-hours report."""

    city: str = Field(default="phoenix")
    start_date: str | None = Field(default=None)
    end_date: str | None = Field(default=None)
    threshold_f: float | None = Field(default=None)
    granularity: int = Field(default=100)
    weight_svi: float = Field(default=0.50, ge=0, description="Weight on CDC's SVI percentile")
    weight_elderly: float = Field(default=0.30, ge=0, description="Weight on the 65+ share")
    weight_outdoor: float = Field(default=0.20, ge=0, description="Weight on outdoor-worker density")
    limit: int = Field(default=25, ge=1, le=500, description="Tracts returned, worst first")


class CoverageRequest(BaseModel):
    """A request for the cooling-coverage gap analysis."""

    city: str = Field(default="phoenix")
    start_date: str | None = Field(default=None)
    end_date: str | None = Field(default=None)
    threshold_f: float | None = Field(default=None)
    granularity: int = Field(default=100)
    weekday: str = Field(default="Wednesday", description="Weekday whose hours are used")
    hours: list[float] = Field(
        default=[14.0, 16.0, 17.0, 19.0, 20.0],
        description="Hours of day to evaluate coverage at",
    )
    evening_hour: float = Field(
        default=19.0, description="Hour used for the hours-gap comparison"
    )
    walkable_km: float = Field(
        default=0.8, gt=0, le=10, description="Straight-line radius treated as walkable"
    )
    limit: int = Field(default=15, ge=1, le=200)


class SimulateHoursRequest(BaseModel):
    """A what-if request for extending cooling-site opening hours."""

    city: str = Field(default="phoenix")
    granularity: int = Field(default=100)
    weekday: str = Field(default="Wednesday")
    hour: float = Field(default=19.0, description="Hour of day the result is evaluated at")
    extra_hours: list[float] = Field(
        default=[1.0, 2.0, 3.0, 4.0], description="Extensions to compare"
    )
    walkable_km: float = Field(default=0.8, gt=0, le=10)
    uptake: float = Field(
        default=1.0,
        ge=0,
        le=1,
        description="Share of covered residents assumed to actually use a site. "
        "1.0 gives a clearly-labelled upper bound.",
    )


class SimulateSitesRequest(BaseModel):
    """A what-if request for placing additional pop-up cooling sites."""

    city: str = Field(default="phoenix")
    granularity: int = Field(default=100)
    weekday: str = Field(default="Wednesday")
    hour: float = Field(default=19.0)
    budget: int = Field(default=5, ge=1, le=50, description="How many sites to place")
    walkable_km: float = Field(default=0.8, gt=0, le=10)
    uptake: float = Field(default=1.0, ge=0, le=1)


# ------------------------------------------------------- tract data (lazy)

_tracts: TractCollection | None = None
_sites: list[CoolingSite] | None = None
#: Memoised exposure reports. Building one costs a spatial join over ~10k tiles,
#: so the UI must not trigger it on every keystroke.
_exposure_cache: dict[tuple, ExposureReport] = {}
#: Tile-to-tract assignment per (city, granularity); identical across layers.
_assignment_cache: dict[tuple, dict[int, str]] = {}


def get_tracts() -> TractCollection:
    """Load the tract collection once, on first use.

    Deliberately lazy: the surfaces endpoints work without tract data, so a
    missing download should not stop the server from starting.
    """
    global _tracts
    if _tracts is None:
        _tracts = load_tracts(download=False)
        _audit.note(
            "loaded real tract data",
            **_tracts.summary(),
            sources=[s.key for s in SOURCES.values()],
        )
    return _tracts


def get_sites() -> list[CoolingSite]:
    """Load Heat Relief Network sites once, on first use."""
    global _sites
    if _sites is None:
        _sites = load_sites(download=False)
        _audit.note(
            "loaded real cooling-centre supply",
            **{k: v for k, v in supply_summary(_sites).items() if k != "by_type"},
        )
    return _sites


# --------------------------------------------------------------------- utils


def _fetch(layer: str, city_key: str, req: SurfaceRequest) -> HeatSurface:
    """Compute or retrieve one surface, routing through the intent methods."""
    city = get_city(city_key)
    start = req.start_date or city.episode_start
    end = req.end_date or city.episode_end
    threshold = req.threshold_f if req.threshold_f is not None else city.danger_threshold_f

    if layer == "snapshot":
        return _layers.how_hot(
            city.aoi, start_date=start, filter_type=3, granularity=req.granularity
        )
    if layer == "peak_hour":
        return _layers.when_peak(
            city.aoi, start_date=start, filter_type=3, granularity=req.granularity
        )
    if layer == "exceedance":
        return _layers.how_long_dangerous(
            city.aoi,
            threshold=threshold,
            threshold_unit="F",
            start_date=start,
            end_date=end,
            granularity=req.granularity,
        )
    if layer == "persistence":
        return _layers.any_relief(
            city.aoi,
            threshold=threshold,
            threshold_unit="F",
            start_date=start,
            end_date=end,
            granularity=req.granularity,
        )
    raise HTTPException(status_code=400, detail=f"unknown layer {layer!r}")


def _handle(exc: Exception) -> HTTPException:
    """Map internal errors onto meaningful HTTP responses."""
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=422, detail={"error": str(exc), "field": exc.field})
    if isinstance(exc, CacheMiss):
        return HTTPException(
            status_code=409,
            detail={
                "error": str(exc),
                "hint": "The API is in replay mode. Set CITYVIGIL_CACHE_MODE=live to fetch new windows.",
            },
        )
    if isinstance(exc, CityVigilError):
        return HTTPException(status_code=502, detail={"error": str(exc)})
    return HTTPException(status_code=500, detail={"error": str(exc)})


# ------------------------------------------------------------------ endpoints


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness plus the configuration the UI needs to explain itself."""
    return {
        "ok": True,
        "cache_mode": _settings.cache_mode,
        "has_api_key": _settings.api_key is not None,
        "base_url": _settings.base_url,
        "cities": sorted(CITIES),
    }


@app.get("/api/cities")
def list_cities() -> dict[str, Any]:
    """Study areas, with their AOI geometry and known heat episode."""
    return {"cities": [c.to_dict() for c in CITIES.values()]}


@app.get("/api/layers")
def list_layers() -> dict[str, Any]:
    """The four layers, with the question each one answers."""
    return {"layers": [{"key": k, **v} for k, v in LAYER_META.items()]}


@app.get("/api/credits")
def credits() -> dict[str, Any]:
    """Remaining credits, so the UI can show the budget being spent."""
    remaining = _client.credits_remaining()
    return {
        "remaining": remaining,
        "credits_per_heatmap": 4220,
        "heatmaps_affordable": None if remaining is None else remaining // 4220,
    }


@app.post("/api/surfaces")
def surfaces(req: SurfaceRequest) -> dict[str, Any]:
    """Compute the requested surfaces and return their summaries (no geometry).

    Kept separate from the GeoJSON endpoint so the UI can render headline numbers
    immediately and fetch the heavy tile geometry per selected layer.
    """
    try:
        get_city(req.city)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    out: dict[str, Any] = {}
    for layer in req.layers:
        try:
            surface = _fetch(layer, req.city, req)
        except Exception as exc:  # noqa: BLE001 - mapped to HTTP below
            raise _handle(exc) from exc
        out[layer] = {
            **surface.summary(),
            **LAYER_META[layer],
            "rationale": surface.rationale,
        }

    return {
        "city": req.city,
        "surfaces": out,
        "stats": _client.run_stats(),
    }


@app.post("/api/surface/{layer}/geojson")
def surface_geojson(layer: LayerName, req: SurfaceRequest) -> dict[str, Any]:
    """Full tile geometry for one layer, ready for the map."""
    try:
        surface = _fetch(layer, req.city, req)
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc
    return surface.to_geojson()


@app.get("/api/supply")
def supply() -> dict[str, Any]:
    """Cooling-centre supply: composition, hours profile, and the vintage caveat."""
    try:
        sites = get_sites()
    except SupplyDataError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": str(exc),
                "hint": "Run python3 scripts/fetch_data.py to download the sources.",
            },
        ) from exc

    counts = open_site_count_by_hour(sites, weekday="Wednesday")
    peak_hour = max(counts, key=lambda h: counts[h])
    return {
        "summary": supply_summary(sites),
        "open_by_hour": counts,
        "peak_hour": peak_hour,
        "peak_open": counts[peak_hour],
        "sites": [s.to_dict() for s in sites],
    }


@app.post("/api/coverage")
def coverage(req: CoverageRequest) -> dict[str, Any]:
    """Unmet need: residents with no walkable cooling site open at a given hour.

    Reports the siting gap and the hours gap separately. They have different
    causes and different remedies — one needs new sites, the other only needs
    later closing times — and merging them into a single "uncovered" figure would
    obscure the cheaper fix.
    """
    try:
        report = _exposure_report(
            ExposureRequest(
                city=req.city,
                start_date=req.start_date,
                end_date=req.end_date,
                threshold_f=req.threshold_f,
                granularity=req.granularity,
            )
        )
        sites = get_sites()
    except (TractDataError, SupplyDataError) as exc:
        raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc

    studied = [e.tract for e in report.tracts]
    counts = open_site_count_by_hour(sites, weekday=req.weekday)
    peak_hour = max(counts, key=lambda h: counts[h])

    by_hour = []
    for hour in req.hours:
        cover = coverage_for_tracts(
            studied, sites, weekday=req.weekday, hour=hour, walkable_km=req.walkable_km
        )
        uncovered = [e for e in report.tracts if not cover[e.tract.geoid].walkable_cover]
        by_hour.append(
            {
                "hour": hour,
                "sites_open": counts[int(hour)],
                "tracts_uncovered": len(uncovered),
                "residents_uncovered": sum(e.tract.population for e in uncovered),
                "unmet_person_hours": round(sum(e.person_hours for e in uncovered), 1),
                "unmet_weighted_person_hours": round(
                    sum(e.weighted_person_hours for e in uncovered), 1
                ),
            }
        )

    # Separate the siting gap from the hours gap.
    at_peak = coverage_for_tracts(
        studied, sites, weekday=req.weekday, hour=float(peak_hour), walkable_km=req.walkable_km
    )
    at_evening = coverage_for_tracts(
        studied, sites, weekday=req.weekday, hour=req.evening_hour, walkable_km=req.walkable_km
    )
    lost = [
        e
        for e in report.tracts
        if at_peak[e.tract.geoid].walkable_cover
        and not at_evening[e.tract.geoid].walkable_cover
    ]

    return {
        "framing": (
            "The Heat Relief Network service publishes only the current season, so "
            "this evaluates today's network against a past heat episode. It is not "
            "a record of what was open during that episode."
        ),
        "weekday": req.weekday,
        "walkable_km": req.walkable_km,
        "open_by_hour": counts,
        "peak_hour": peak_hour,
        "by_hour": by_hour,
        "siting_gap": {
            "tracts_total": len(report.tracts),
            "tracts_with_walkable_cover_at_peak": sum(
                1 for e in report.tracts if at_peak[e.tract.geoid].walkable_cover
            ),
            "remedy": "new or relocated sites",
        },
        "hours_gap": {
            "evening_hour": req.evening_hour,
            "tracts_losing_cover": len(lost),
            "residents_affected": sum(e.tract.population for e in lost),
            "person_hours_affected": round(sum(e.person_hours for e in lost), 1),
            "remedy": "later closing times at existing sites, no capital cost",
            "tracts": [
                {
                    **e.to_dict(),
                    "coverage_at_evening": at_evening[e.tract.geoid].to_dict(),
                }
                for e in sorted(lost, key=lambda x: -x.weighted_person_hours)[:10]
            ],
        },
        "worst_served_at_evening": [
            {**e.to_dict(), "coverage": at_evening[e.tract.geoid].to_dict()}
            for e in report.ranked()
            if not at_evening[e.tract.geoid].walkable_cover
        ][: req.limit],
    }


@app.post("/api/simulate/hours")
def simulate_hours(req: SimulateHoursRequest) -> dict[str, Any]:
    """What if every cooling site closed later?

    The prescriptive counterpart to ``/api/coverage``. Returns person-hours and
    residents newly protected, plus the staffing cost proxy, so the trade is
    visible rather than asserted.
    """
    try:
        report = _exposure_report(ExposureRequest(city=req.city, granularity=req.granularity))
        sites = get_sites()
    except (TractDataError, SupplyDataError) as exc:
        raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc

    results = []
    for extra in req.extra_hours:
        try:
            result = simulate_extended_hours(
                report.tracts,
                sites,
                extra_hours=extra,
                weekday=req.weekday,
                hour=req.hour,
                walkable_km=req.walkable_km,
                uptake=req.uptake,
            )
        except ValidationError as exc:
            raise _handle(exc) from exc
        results.append(result.to_dict())

    _audit.decision(
        "simulated cooling-hours extensions",
        hour=req.hour,
        uptake=req.uptake,
        options=[r["intervention"]["description"] for r in results],
    )
    return {"hour": req.hour, "uptake": req.uptake, "options": results}


@app.post("/api/simulate/sites")
def simulate_sites(req: SimulateSitesRequest) -> dict[str, Any]:
    """Where should the next N pop-up cooling sites go?

    Greedy marginal gain over the worst-served tracts. The ordering is the point:
    it answers "if we can only afford three, which three?" rather than presenting
    an all-or-nothing plan.
    """
    try:
        report = _exposure_report(ExposureRequest(city=req.city, granularity=req.granularity))
        sites = get_sites()
    except (TractDataError, SupplyDataError) as exc:
        raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc

    try:
        plan = greedy_site_placement(
            report.tracts,
            sites,
            budget=req.budget,
            weekday=req.weekday,
            hour=req.hour,
            walkable_km=req.walkable_km,
            uptake=req.uptake,
        )
    except ValidationError as exc:
        raise _handle(exc) from exc

    _audit.decision(
        "planned pop-up cooling sites by greedy marginal gain",
        budget=req.budget,
        hour=req.hour,
        placed=len(plan),
    )
    return {
        "hour": req.hour,
        "uptake": req.uptake,
        "budget": req.budget,
        "placements": plan,
        "method": (
            "Greedy marginal gain. Coverage gain is submodular, so greedy carries a "
            "known quality bound and produces a usable priority order."
        ),
        "caveats": [
            "Proposed sites are hypothetical and labelled SIMULATED.",
            "Placed at tract centres, not at real candidate buildings.",
            "Straight-line coverage radius, so gains are optimistic.",
        ],
    }


class AgentRequest(BaseModel):
    """A goal for the agent to investigate."""

    question: str = Field(
        default="Who should we protect first, and what is the cheapest way to do it?"
    )
    city: str = Field(default="phoenix")
    hour: float = Field(default=19.0)
    threshold_f: float | None = Field(default=None)
    max_credits: int = Field(default=40_000, ge=0)


@app.post("/api/agent")
def run_agent(req: AgentRequest) -> dict[str, Any]:
    """Run the agent and return its recommendation with the full reasoning trace.

    The trace is a first-class part of the response, not a debug aid: every layer
    choice and every branch carries the reason it was taken.
    """
    agent = HeatResponseAgent(_client, budget=AgentBudget(max_credits=req.max_credits))
    try:
        result = agent.run(
            req.question,
            city_key=req.city,
            evening_hour=req.hour,
            threshold_f=req.threshold_f,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc

    return {
        **result.to_dict(),
        "capabilities": agent.toolbox.describe(),
        "credits_spent": agent.budget.spent_credits,
        "planner": (
            "Deterministic policy, not an LLM. Chosen so layer selection cannot be "
            "hallucinated and every decision is reproducible and unit-tested."
        ),
    }


@app.get("/api/audit")
def audit() -> dict[str, Any]:
    """The audit trail: every call made and every layer choice, with reasons."""
    return {
        "records": _audit.to_list(),
        "endpoints_used": _audit.endpoints_used(),
        "layers_used": _audit.layers_used(),
        "text": _audit.render_text(),
    }


# ----------------------------------------------------- vulnerability & people


@app.get("/api/sources")
def data_sources() -> dict[str, Any]:
    """The external datasets in use, with citations and download provenance."""
    return {
        "sources": [
            {
                "key": s.key,
                "name": s.name,
                "url": s.url,
                "citation": s.citation,
                "licence": s.licence,
                "role": s.role,
            }
            for s in SOURCES.values()
        ],
        "manifest": load_manifest(),
        "citations": citations(),
    }


@app.get("/api/tracts/summary")
def tracts_summary() -> dict[str, Any]:
    """Coverage of the loaded tract data, including its known gaps."""
    try:
        return get_tracts().summary()
    except TractDataError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": str(exc),
                "hint": "Run python3 scripts/fetch_data.py to download the sources.",
            },
        ) from exc


def _exposure_report(req: ExposureRequest) -> ExposureReport:
    """Build (or reuse) the vulnerability-weighted exposure report."""
    city = get_city(req.city)
    start = req.start_date or city.episode_start
    end = req.end_date or city.episode_end
    threshold = req.threshold_f if req.threshold_f is not None else city.danger_threshold_f

    key = (
        city.key,
        start,
        end,
        threshold,
        req.granularity,
        req.weight_svi,
        req.weight_elderly,
        req.weight_outdoor,
    )
    if key in _exposure_cache:
        return _exposure_cache[key]

    tracts = get_tracts()
    surface_req = SurfaceRequest(
        city=req.city,
        start_date=start,
        end_date=end,
        threshold_f=threshold,
        granularity=req.granularity,
    )
    exceedance = _fetch("exceedance", city.key, surface_req)
    persistence = _fetch("persistence", city.key, surface_req)
    snapshot = _fetch("snapshot", city.key, surface_req)

    # The tile grid is identical across analytic types for a fixed AOI and
    # granularity (verified live), so the spatial join is computed once.
    assign_key = (city.key, req.granularity)
    if assign_key not in _assignment_cache:
        _assignment_cache[assign_key] = assign_tiles(exceedance, tracts)
    assignment = _assignment_cache[assign_key]

    model = VulnerabilityModel(
        tracts,
        Weights(
            svi=req.weight_svi,
            elderly=req.weight_elderly,
            outdoor_workers=req.weight_outdoor,
        ),
    )
    report = build_exposure_report(
        exceedance,
        tracts,
        model,
        persistence=persistence,
        snapshot=snapshot,
        assignment=assignment,
    )
    _audit.decision(
        "ranked tracts by vulnerability-weighted person-hours",
        n_tracts=len(report.tracts),
        **{k: v for k, v in report.totals().items() if k.endswith("hours")},
        weights=model.weights.to_dict(),
    )
    _exposure_cache[key] = report
    return report


@app.post("/api/exposure")
def exposure(req: ExposureRequest) -> dict[str, Any]:
    """Vulnerability-weighted person-hours of dangerous heat, ranked by tract.

    The headline metric is person-hours: ``exceedance`` returns hours past the
    threshold, so multiplying by the exposed population gives person-hours in the
    API's own units rather than an invented index.
    """
    try:
        report = _exposure_report(req)
    except TractDataError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": str(exc),
                "hint": "Run python3 scripts/fetch_data.py to download the sources.",
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc
    return report.to_dict(limit=req.limit)


@app.post("/api/exposure/geojson")
def exposure_geojson(req: ExposureRequest) -> dict[str, Any]:
    """Tract polygons carrying the ranked exposure metrics, for choropleth display."""
    try:
        report = _exposure_report(req)
    except TractDataError as exc:
        raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc
    except Exception as exc:  # noqa: BLE001
        raise _handle(exc) from exc

    ranked = report.ranked()
    features = []
    for position, entry in enumerate(ranked, start=1):
        rings = [
            [[round(x, 6), round(y, 6)] for x, y in polygon.outer]
            for polygon in entry.tract.geometry.polygons
        ]
        payload = entry.to_dict()
        payload["rank"] = position
        features.append(
            {
                "type": "Feature",
                "id": entry.tract.geoid,
                "properties": payload,
                "geometry": {"type": "MultiPolygon", "coordinates": [[r] for r in rings]},
            }
        )

    return {
        "type": "FeatureCollection",
        "properties": {"totals": report.totals(), "model": report.model},
        "features": features,
    }
