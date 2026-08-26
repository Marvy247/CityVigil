"""Joining heat exposure to population: person-hours at risk.

The metric
----------
``exceedance`` returns a **count of hours** each tile spends past the danger
threshold. Multiplied by the people exposed, that is person-hours of dangerous
heat exposure — in the API's own units, not an invented index. This is the single
most important property of the whole design and it is why ``exceedance`` was
chosen over a temperature snapshot.

Stated assumptions
-----------------
**Population is uniform within a tract.** Census tracts are the finest geography
with published age and poverty counts, and nothing tells us where inside a tract
people actually live. Under that assumption, summing ``hours_i × population_i``
over a tract's tiles is exactly ``population_total × mean(hours)``, which is how
it is computed here. Real intra-tract density varies, so a tract's total is more
reliable than any claim about one tile.

**Persistence is never added to exceedance.** They are both in hours and it would
be arithmetically easy to combine them. It would also be wrong: persistence is a
*subset* of exceedance hours (the longest unbroken run), so adding them double
counts. Persistence is carried alongside as an independent severity signal.

**Worker exposure-hours are an unscheduled upper bound.** Outdoor job counts have
no shift information, so attributing the full window to them overstates real
exposure. The figure is reported separately and labelled, never folded into the
resident total.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .errors import ValidationError
from .layers import HeatSurface
from .tracts import Tract, TractCollection
from .vulnerability import VulnerabilityModel, VulnerabilityScore


@dataclass(frozen=True)
class TractExposure:
    """Exposure, population and vulnerability for one tract."""

    tract: Tract
    vulnerability: VulnerabilityScore
    n_tiles: int

    mean_exceedance_h: float
    max_exceedance_h: float
    mean_persistence_h: float | None
    max_persistence_h: float | None
    mean_temperature_c: float | None

    threshold_c: float | None
    window: dict[str, Any]

    # ---------------------------------------------------------------- metrics

    @property
    def person_hours(self) -> float:
        """Resident person-hours above the danger threshold."""
        return self.tract.population * self.mean_exceedance_h

    @property
    def elderly_person_hours(self) -> float:
        """Person-hours borne by residents aged 65+."""
        return self.tract.age65 * self.mean_exceedance_h

    @property
    def worker_exposure_hours_upper_bound(self) -> float:
        """Outdoor-worker exposure-hours, with no shift model applied.

        An upper bound by construction. Reported for comparison, never summed
        with resident person-hours.
        """
        return self.tract.jobs_outdoor * self.mean_exceedance_h

    @property
    def weighted_person_hours(self) -> float:
        """Person-hours scaled by the vulnerability score.

        This is the allocation objective: it ranks by *who* is exposed as well as
        how long, so a small elderly high-SVI tract can outrank a larger, younger
        one with identical heat.
        """
        return self.person_hours * self.vulnerability.score

    def to_dict(self) -> dict:
        return {
            "geoid": self.tract.geoid,
            "name": self.tract.name,
            "population": self.tract.population,
            "age65": self.tract.age65,
            "jobs_outdoor": self.tract.jobs_outdoor,
            "n_tiles": self.n_tiles,
            "mean_exceedance_h": round(self.mean_exceedance_h, 3),
            "max_exceedance_h": round(self.max_exceedance_h, 3),
            "mean_persistence_h": (
                None if self.mean_persistence_h is None else round(self.mean_persistence_h, 3)
            ),
            "max_persistence_h": (
                None if self.max_persistence_h is None else round(self.max_persistence_h, 3)
            ),
            "mean_temperature_c": (
                None if self.mean_temperature_c is None else round(self.mean_temperature_c, 2)
            ),
            "person_hours": round(self.person_hours, 1),
            "elderly_person_hours": round(self.elderly_person_hours, 1),
            "worker_exposure_hours_upper_bound": round(
                self.worker_exposure_hours_upper_bound, 1
            ),
            "vulnerability": self.vulnerability.to_dict(),
            "weighted_person_hours": round(self.weighted_person_hours, 1),
            "threshold_c": self.threshold_c,
        }


@dataclass(frozen=True)
class ExposureReport:
    """Every tract intersecting an analysed area, ranked by weighted person-hours."""

    tracts: tuple[TractExposure, ...]
    unmatched_tiles: int
    total_tiles: int
    threshold_c: float | None
    window: dict[str, Any]
    model: dict[str, Any]

    def ranked(self, limit: int | None = None) -> list[TractExposure]:
        """Tracts ordered by the allocation objective, worst first."""
        order = sorted(self.tracts, key=lambda t: t.weighted_person_hours, reverse=True)
        return order[:limit] if limit else order

    def ranked_by_person_hours(self, limit: int | None = None) -> list[TractExposure]:
        """Tracts ordered by raw person-hours, ignoring vulnerability.

        Kept deliberately: comparing this ordering against :meth:`ranked` shows
        exactly what the vulnerability weighting changes, which is the honest way
        to present a weighted metric.
        """
        order = sorted(self.tracts, key=lambda t: t.person_hours, reverse=True)
        return order[:limit] if limit else order

    def totals(self) -> dict[str, Any]:
        return {
            "n_tracts": len(self.tracts),
            "population": sum(t.tract.population for t in self.tracts),
            "population_65_plus": sum(t.tract.age65 for t in self.tracts),
            "outdoor_jobs": sum(t.tract.jobs_outdoor for t in self.tracts),
            "person_hours": round(sum(t.person_hours for t in self.tracts), 1),
            "elderly_person_hours": round(
                sum(t.elderly_person_hours for t in self.tracts), 1
            ),
            "weighted_person_hours": round(
                sum(t.weighted_person_hours for t in self.tracts), 1
            ),
            "worker_exposure_hours_upper_bound": round(
                sum(t.worker_exposure_hours_upper_bound for t in self.tracts), 1
            ),
            "tiles_matched": self.total_tiles - self.unmatched_tiles,
            "tiles_unmatched": self.unmatched_tiles,
            "threshold_c": self.threshold_c,
        }

    def rank_shift(self, limit: int = 10) -> list[dict[str, Any]]:
        """How the vulnerability weighting reorders the priority list.

        Positive ``moved_up`` means the tract is more urgent once who lives there
        is taken into account than raw exposure alone implies.
        """
        weighted = [t.tract.geoid for t in self.ranked()]
        raw = [t.tract.geoid for t in self.ranked_by_person_hours()]
        out = []
        for position, geoid in enumerate(weighted[:limit]):
            out.append(
                {
                    "geoid": geoid,
                    "rank_weighted": position + 1,
                    "rank_person_hours": raw.index(geoid) + 1,
                    "moved_up": raw.index(geoid) - position,
                }
            )
        return out

    def to_dict(self, limit: int | None = None) -> dict:
        return {
            "totals": self.totals(),
            "model": self.model,
            "window": self.window,
            "rank_shift": self.rank_shift(),
            "tracts": [t.to_dict() for t in self.ranked(limit)],
        }


def assign_tiles(surface: HeatSurface, tracts: TractCollection) -> dict[int, str]:
    """Map ``tile_id -> tract GEOID`` for every tile that falls in a tract.

    Computed once and reused across layers. Verified against the live API: for a
    fixed AOI and granularity, every analytic type returns the same tile ids with
    the same centroids, so one assignment serves the exceedance, persistence and
    snapshot surfaces. That turns three spatial joins into one.
    """
    assignment: dict[int, str] = {}
    for tile in surface.tiles:
        geoid = tracts.index.find(tile.centroid)
        if geoid is not None:
            assignment[tile.tile_id] = geoid
    return assignment


def _group_by_tract(
    surface: HeatSurface, assignment: dict[int, str]
) -> tuple[dict[str, list[float]], int]:
    """Group tile values by tract using a precomputed assignment."""
    grouped: dict[str, list[float]] = {}
    unmatched = 0
    for tile in surface.tiles:
        geoid = assignment.get(tile.tile_id)
        if geoid is None:
            unmatched += 1
            continue
        grouped.setdefault(geoid, []).append(tile.value)
    return grouped, unmatched


def build_exposure_report(
    exceedance: HeatSurface,
    tracts: TractCollection,
    model: VulnerabilityModel,
    *,
    persistence: HeatSurface | None = None,
    snapshot: HeatSurface | None = None,
    assignment: dict[int, str] | None = None,
) -> ExposureReport:
    """Join an exceedance surface to tracts and rank by vulnerability-weighted
    person-hours.

    ``persistence`` and ``snapshot`` are optional context layers. They are carried
    through per tract but never merged into the person-hours figure.

    ``assignment`` lets a caller supply a precomputed tile-to-tract mapping from
    :func:`assign_tiles`, avoiding a repeated spatial join.

    :raises ValidationError: if the primary surface is not an exceedance layer,
        since person-hours are only meaningful in hours past a threshold.
    """
    if exceedance.analytic_type != "exceedance":
        raise ValidationError(
            f"person-hours require an exceedance surface (hours past a threshold); "
            f"got {exceedance.analytic_type!r}. A tcm snapshot returns degrees and "
            f"cannot be multiplied by population to yield person-hours.",
            field="analytic_type",
        )

    if assignment is None:
        assignment = assign_tiles(exceedance, tracts)

    exc_by_tract, unmatched = _group_by_tract(exceedance, assignment)
    per_by_tract, _ = _group_by_tract(persistence, assignment) if persistence else ({}, 0)
    snap_by_tract, _ = _group_by_tract(snapshot, assignment) if snapshot else ({}, 0)

    def mean(values: Iterable[float]) -> float | None:
        items = list(values)
        return (sum(items) / len(items)) if items else None

    exposures: list[TractExposure] = []
    for geoid, values in exc_by_tract.items():
        tract = tracts[geoid]
        persistence_values = per_by_tract.get(geoid, [])
        exposures.append(
            TractExposure(
                tract=tract,
                vulnerability=model.score(tract),
                n_tiles=len(values),
                mean_exceedance_h=sum(values) / len(values),
                max_exceedance_h=max(values),
                mean_persistence_h=mean(persistence_values),
                max_persistence_h=max(persistence_values) if persistence_values else None,
                mean_temperature_c=mean(snap_by_tract.get(geoid, [])),
                threshold_c=exceedance.threshold_c,
                window=exceedance.window,
            )
        )

    return ExposureReport(
        tracts=tuple(exposures),
        unmatched_tiles=unmatched,
        total_tiles=len(exceedance),
        threshold_c=exceedance.threshold_c,
        window=exceedance.window,
        model=model.describe(),
    )
