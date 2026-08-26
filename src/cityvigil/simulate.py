"""What-if simulation: turning the diagnosis into a decision.

The coverage analysis says where protection fails. That is diagnostic. A city
operations team needs the next sentence: *if we do X, what changes?* This module
answers two questions that map onto the two gap causes, because they have very
different price tags:

**Extend hours.** Keep every site where it is and close later. Costs staffing, not
capital. Measured by re-evaluating coverage at the later hour and differencing the
person-hours that become protected.

**Add sites.** Place new pop-up cooling capacity at chosen points. Costs capital.
Measured by marginal gain per site, greedily, so the ranking answers "if we can
only afford three, which three?"

Honesty constraints carried through every result
-----------------------------------------------
* **Protected ≠ saved.** A person-hour counted as protected means an open cooling
  site was within walking distance during a dangerous hour. Whether anyone walks
  there is a behavioural question this model does not answer, so an explicit
  ``uptake`` factor is applied and always reported. It defaults to 1.0 so the
  headline is a clearly-labelled upper bound rather than a hidden assumption.
* **Straight-line distance.** Coverage uses the same optimistic radius as the rest
  of the project; real walking distance is longer.
* **No capacity model.** A site counts as available if it is open, regardless of
  how many people it can hold.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Sequence

from .errors import ValidationError
from .exposure import TractExposure
from .supply import CoolingSite, Weekday, coverage_for_tracts


@dataclass(frozen=True)
class Intervention:
    """What was changed, in terms a city could actually act on."""

    kind: str
    description: str
    #: Operating cost proxy: additional site-hours of staffing required.
    added_site_hours: float = 0.0
    #: Capital proxy: number of new sites required.
    added_sites: int = 0

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "description": self.description,
            "added_site_hours": round(self.added_site_hours, 1),
            "added_sites": self.added_sites,
        }


@dataclass(frozen=True)
class SimulationResult:
    """Before and after, with the difference attributable to the intervention."""

    intervention: Intervention
    hour: float
    uptake: float

    tracts_covered_before: int
    tracts_covered_after: int
    residents_covered_before: int
    residents_covered_after: int
    person_hours_protected_before: float
    person_hours_protected_after: float
    weighted_person_hours_protected_before: float
    weighted_person_hours_protected_after: float
    n_tracts: int
    newly_covered_geoids: tuple[str, ...]

    @property
    def tracts_gained(self) -> int:
        return self.tracts_covered_after - self.tracts_covered_before

    @property
    def residents_gained(self) -> int:
        return self.residents_covered_after - self.residents_covered_before

    @property
    def person_hours_gained(self) -> float:
        return self.person_hours_protected_after - self.person_hours_protected_before

    @property
    def weighted_gained(self) -> float:
        return (
            self.weighted_person_hours_protected_after
            - self.weighted_person_hours_protected_before
        )

    @property
    def person_hours_per_site_hour(self) -> float | None:
        """Efficiency of an hours extension. ``None`` when no hours were added."""
        if self.intervention.added_site_hours <= 0:
            return None
        return self.person_hours_gained / self.intervention.added_site_hours

    @property
    def person_hours_per_site(self) -> float | None:
        """Efficiency of new capacity. ``None`` when no sites were added."""
        if self.intervention.added_sites <= 0:
            return None
        return self.person_hours_gained / self.intervention.added_sites

    def to_dict(self) -> dict:
        return {
            "intervention": self.intervention.to_dict(),
            "hour": self.hour,
            "uptake": self.uptake,
            "n_tracts": self.n_tracts,
            "before": {
                "tracts_covered": self.tracts_covered_before,
                "residents_covered": self.residents_covered_before,
                "person_hours_protected": round(self.person_hours_protected_before, 1),
                "weighted_person_hours_protected": round(
                    self.weighted_person_hours_protected_before, 1
                ),
            },
            "after": {
                "tracts_covered": self.tracts_covered_after,
                "residents_covered": self.residents_covered_after,
                "person_hours_protected": round(self.person_hours_protected_after, 1),
                "weighted_person_hours_protected": round(
                    self.weighted_person_hours_protected_after, 1
                ),
            },
            "gained": {
                "tracts": self.tracts_gained,
                "residents": self.residents_gained,
                "person_hours": round(self.person_hours_gained, 1),
                "weighted_person_hours": round(self.weighted_gained, 1),
                "person_hours_per_site_hour": (
                    None
                    if self.person_hours_per_site_hour is None
                    else round(self.person_hours_per_site_hour, 1)
                ),
                "person_hours_per_site": (
                    None
                    if self.person_hours_per_site is None
                    else round(self.person_hours_per_site, 1)
                ),
            },
            "newly_covered_geoids": list(self.newly_covered_geoids),
            "caveats": [
                "Protected means an open site was within the walkable radius, not "
                "that anyone travelled to it. Uptake is applied and reported.",
                "Distance is straight-line, so coverage is optimistic.",
                "Sites have no modelled capacity limit.",
            ],
        }


# ------------------------------------------------------------------- internals


def _covered_stats(
    entries: Sequence[TractExposure],
    sites: list[CoolingSite],
    *,
    weekday: Weekday,
    hour: float,
    walkable_km: float,
    uptake: float,
) -> tuple[int, int, float, float, set[str]]:
    """Coverage totals at one hour. Returns tracts, residents, p-h, weighted, geoids."""
    coverage = coverage_for_tracts(
        (e.tract for e in entries),
        sites,
        weekday=weekday,
        hour=hour,
        walkable_km=walkable_km,
    )
    covered = [e for e in entries if coverage[e.tract.geoid].walkable_cover]
    return (
        len(covered),
        sum(e.tract.population for e in covered),
        sum(e.person_hours for e in covered) * uptake,
        sum(e.weighted_person_hours for e in covered) * uptake,
        {e.tract.geoid for e in covered},
    )


def extend_hours(site: CoolingSite, weekday: Weekday, extra_hours: float) -> CoolingSite:
    """Return a copy of ``site`` closing ``extra_hours`` later on ``weekday``.

    A site with no published hours for that day is returned unchanged: there is no
    closing time to extend, and inventing one would overstate availability.
    """
    window = site.hours.get(weekday)
    if window is None:
        return site
    start, end = window
    hours = dict(site.hours)
    hours[weekday] = (start, min(24.0, end + extra_hours))
    return replace(site, hours=hours)


def make_popup_site(
    lon: float, lat: float, *, name: str, opens: float = 12.0, closes: float = 22.0
) -> CoolingSite:
    """Build a hypothetical pop-up cooling site for simulation.

    Marked clearly in its type so it can never be mistaken for a real Heat Relief
    Network record in an export.
    """
    return CoolingSite(
        site_id=f"popup-{name}",
        name=name,
        organization="SIMULATED",
        city="",
        address="hypothetical pop-up site",
        site_type="Cooling Center",
        lon=float(lon),
        lat=float(lat),
        hours={d: (opens, closes) for d in ("Monday", "Tuesday", "Wednesday",
                                            "Thursday", "Friday", "Saturday", "Sunday")},
        ada_accessible=None,
        allows_pets=None,
        season_start=None,
        season_end=None,
    )


# ------------------------------------------------------------------ simulations


def simulate_extended_hours(
    entries: Sequence[TractExposure],
    sites: list[CoolingSite],
    *,
    extra_hours: float,
    weekday: Weekday = "Wednesday",
    hour: float = 19.0,
    walkable_km: float = 0.8,
    uptake: float = 1.0,
) -> SimulationResult:
    """What if every cooling site stayed open ``extra_hours`` longer?

    Evaluated at ``hour`` — the point in the evening where the real network has
    thinned out. Only sites with published hours for that weekday are extended.
    """
    if extra_hours < 0:
        raise ValidationError("extra_hours must be non-negative", field="extra_hours")
    if not 0.0 <= uptake <= 1.0:
        raise ValidationError("uptake must be between 0 and 1", field="uptake")

    cooling = [s for s in sites if s.is_cooling]
    extended = [extend_hours(s, weekday, extra_hours) for s in sites]

    # Staffing proxy: only sites that were open that weekday incur extra hours.
    affected = sum(1 for s in cooling if s.hours.get(weekday) is not None)

    before = _covered_stats(
        entries, sites, weekday=weekday, hour=hour, walkable_km=walkable_km, uptake=uptake
    )
    after = _covered_stats(
        entries, extended, weekday=weekday, hour=hour, walkable_km=walkable_km, uptake=uptake
    )

    return SimulationResult(
        intervention=Intervention(
            kind="extend_hours",
            description=(
                f"Keep every cooling site open {extra_hours:g} hour(s) later on "
                f"{weekday}, evaluated at {hour:g}:00"
            ),
            added_site_hours=affected * extra_hours,
        ),
        hour=hour,
        uptake=uptake,
        tracts_covered_before=before[0],
        tracts_covered_after=after[0],
        residents_covered_before=before[1],
        residents_covered_after=after[1],
        person_hours_protected_before=before[2],
        person_hours_protected_after=after[2],
        weighted_person_hours_protected_before=before[3],
        weighted_person_hours_protected_after=after[3],
        n_tracts=len(entries),
        newly_covered_geoids=tuple(sorted(after[4] - before[4])),
    )


def simulate_added_sites(
    entries: Sequence[TractExposure],
    sites: list[CoolingSite],
    new_sites: Iterable[CoolingSite],
    *,
    weekday: Weekday = "Wednesday",
    hour: float = 19.0,
    walkable_km: float = 0.8,
    uptake: float = 1.0,
) -> SimulationResult:
    """What if these additional cooling sites existed?"""
    if not 0.0 <= uptake <= 1.0:
        raise ValidationError("uptake must be between 0 and 1", field="uptake")

    added = list(new_sites)
    combined = list(sites) + added

    before = _covered_stats(
        entries, sites, weekday=weekday, hour=hour, walkable_km=walkable_km, uptake=uptake
    )
    after = _covered_stats(
        entries, combined, weekday=weekday, hour=hour, walkable_km=walkable_km, uptake=uptake
    )

    return SimulationResult(
        intervention=Intervention(
            kind="add_sites",
            description=(
                f"Add {len(added)} pop-up cooling site(s), evaluated at {hour:g}:00 "
                f"on {weekday}"
            ),
            added_sites=len(added),
        ),
        hour=hour,
        uptake=uptake,
        tracts_covered_before=before[0],
        tracts_covered_after=after[0],
        residents_covered_before=before[1],
        residents_covered_after=after[1],
        person_hours_protected_before=before[2],
        person_hours_protected_after=after[2],
        weighted_person_hours_protected_before=before[3],
        weighted_person_hours_protected_after=after[3],
        n_tracts=len(entries),
        newly_covered_geoids=tuple(sorted(after[4] - before[4])),
    )


def greedy_site_placement(
    entries: Sequence[TractExposure],
    sites: list[CoolingSite],
    *,
    budget: int,
    weekday: Weekday = "Wednesday",
    hour: float = 19.0,
    walkable_km: float = 0.8,
    uptake: float = 1.0,
) -> list[dict]:
    """Where should the next ``budget`` pop-up sites go?

    Greedy marginal gain: repeatedly place a site at the centre of the uncovered
    tract whose weighted person-hours are highest, then re-evaluate. Greedy is
    chosen deliberately over an exact solver — coverage gain is submodular, so
    greedy carries a known quality bound, and the sequence it produces is the
    answer to "if we can only afford three, which three?" rather than an
    all-or-nothing plan.

    Returns one record per placement, in order, with its marginal contribution.
    """
    if budget <= 0:
        raise ValidationError("budget must be positive", field="budget")

    placed: list[CoolingSite] = []
    out: list[dict] = []

    for step in range(1, budget + 1):
        current = list(sites) + placed
        coverage = coverage_for_tracts(
            (e.tract for e in entries),
            current,
            weekday=weekday,
            hour=hour,
            walkable_km=walkable_km,
        )
        uncovered = [e for e in entries if not coverage[e.tract.geoid].walkable_cover]
        if not uncovered:
            break

        # Target the worst-served tract by the allocation objective.
        target = max(uncovered, key=lambda e: e.weighted_person_hours)
        lon, lat = target.tract.geometry.centroid
        candidate = make_popup_site(lon, lat, name=f"popup-{step}-{target.tract.geoid[-6:]}")

        result = simulate_added_sites(
            entries,
            current,
            [candidate],
            weekday=weekday,
            hour=hour,
            walkable_km=walkable_km,
            uptake=uptake,
        )
        placed.append(candidate)
        out.append(
            {
                "order": step,
                "target_geoid": target.tract.geoid,
                "lon": round(lon, 6),
                "lat": round(lat, 6),
                "tracts_gained": result.tracts_gained,
                "residents_gained": result.residents_gained,
                "person_hours_gained": round(result.person_hours_gained, 1),
                "weighted_person_hours_gained": round(result.weighted_gained, 1),
            }
        )
    return out
