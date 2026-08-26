"""What-if simulation: hours extensions, added sites, and greedy placement."""

from __future__ import annotations

import pytest

from cityvigil.errors import ValidationError
from cityvigil.exposure import TractExposure
from cityvigil.geometry import MultiPolygon, Polygon
from cityvigil.simulate import (
    extend_hours,
    greedy_site_placement,
    make_popup_site,
    simulate_added_sites,
    simulate_extended_hours,
)
from cityvigil.supply import CoolingSite
from cityvigil.tracts import Tract
from cityvigil.vulnerability import VulnerabilityScore


def _tract(geoid: str, lon: float, lat: float, pop: int = 1000, half: float = 0.002) -> Tract:
    geom = MultiPolygon(
        (
            Polygon(
                (
                    (lon - half, lat - half),
                    (lon + half, lat - half),
                    (lon + half, lat + half),
                    (lon - half, lat + half),
                    (lon - half, lat - half),
                )
            ),
        )
    )
    return Tract(
        geoid=geoid, name=f"T{geoid}", geometry=geom, population=pop, age65=pop // 10,
        poverty150=pop // 5, no_vehicle=pop // 20, disability=pop // 10,
        uninsured=pop // 10, svi_percentile=0.5, jobs_total=100, jobs_outdoor=10,
    )


def _entry(geoid: str, lon: float, lat: float, pop: int = 1000, hours: float = 80.0,
           vuln: float = 0.6) -> TractExposure:
    return TractExposure(
        tract=_tract(geoid, lon, lat, pop),
        vulnerability=VulnerabilityScore(
            geoid=geoid, score=vuln, components={}, weights_used={}, svi_imputed=False
        ),
        n_tiles=10,
        mean_exceedance_h=hours,
        max_exceedance_h=hours,
        mean_persistence_h=7.0,
        max_persistence_h=8.0,
        mean_temperature_c=36.0,
        threshold_c=37.78,
        window={},
    )


def _site(name: str, lon: float, lat: float, close: float = 17.0) -> CoolingSite:
    return CoolingSite(
        site_id=name, name=name, organization="o", city="Phoenix", address="a",
        site_type="Cooling Center", lon=lon, lat=lat,
        hours={"Wednesday": (9.0, close)},
        ada_accessible=True, allows_pets=False,
        season_start=None, season_end=None,
    )


# ------------------------------------------------------------- extend_hours


def test_extend_hours_moves_the_closing_time():
    s = extend_hours(_site("a", 0, 0, close=17.0), "Wednesday", 3.0)
    assert s.hours["Wednesday"] == (9.0, 20.0)


def test_extend_hours_clamps_at_midnight():
    s = extend_hours(_site("a", 0, 0, close=23.0), "Wednesday", 5.0)
    assert s.hours["Wednesday"][1] == 24.0


def test_extend_hours_leaves_closed_days_alone():
    """No published closing time means nothing to extend; inventing one would
    overstate availability."""
    site = CoolingSite(
        site_id="a", name="a", organization="", city="", address="",
        site_type="Cooling Center", lon=0, lat=0, hours={},
        ada_accessible=None, allows_pets=None, season_start=None, season_end=None,
    )
    assert extend_hours(site, "Wednesday", 3.0).hours == {}


# --------------------------------------------------------- hours simulation


def test_extension_recovers_coverage_lost_to_closing_time():
    entry = _entry("A", -112.07, 33.45)
    site = _site("near", -112.0705, 33.4503, close=17.0)

    before = simulate_extended_hours([entry], [site], extra_hours=0.0, hour=19.0)
    assert before.tracts_covered_before == 0, "shut at 17:00, so nothing at 19:00"

    after = simulate_extended_hours([entry], [site], extra_hours=3.0, hour=19.0)
    assert after.tracts_gained == 1
    assert after.residents_gained == 1000
    assert after.person_hours_gained == pytest.approx(1000 * 80.0)
    assert after.newly_covered_geoids == ("A",)


def test_extension_reports_staffing_cost_and_efficiency():
    entry = _entry("A", -112.07, 33.45)
    sites = [_site("a", -112.0705, 33.4503), _site("b", -112.0706, 33.4504)]
    r = simulate_extended_hours([entry], sites, extra_hours=2.0, hour=19.0)
    assert r.intervention.added_site_hours == pytest.approx(4.0)  # 2 sites x 2h
    assert r.person_hours_per_site_hour == pytest.approx(r.person_hours_gained / 4.0)


def test_extension_with_no_effect_gains_nothing():
    """A site already open at the evaluated hour cannot be improved by extending."""
    entry = _entry("A", -112.07, 33.45)
    site = _site("open-late", -112.0705, 33.4503, close=22.0)
    r = simulate_extended_hours([entry], [site], extra_hours=2.0, hour=19.0)
    assert r.tracts_gained == 0
    assert r.person_hours_gained == pytest.approx(0.0)


def test_uptake_scales_the_protected_total():
    """Uptake must be applied and visible, never a hidden assumption."""
    entry = _entry("A", -112.07, 33.45)
    site = _site("near", -112.0705, 33.4503, close=17.0)
    full = simulate_extended_hours([entry], [site], extra_hours=3.0, hour=19.0, uptake=1.0)
    third = simulate_extended_hours([entry], [site], extra_hours=3.0, hour=19.0, uptake=0.3)
    assert third.person_hours_gained == pytest.approx(full.person_hours_gained * 0.3)
    assert third.uptake == 0.3
    assert third.to_dict()["uptake"] == 0.3


def test_negative_extension_and_bad_uptake_rejected():
    entry = _entry("A", -112.07, 33.45)
    with pytest.raises(ValidationError, match="non-negative"):
        simulate_extended_hours([entry], [], extra_hours=-1.0)
    with pytest.raises(ValidationError, match="uptake"):
        simulate_extended_hours([entry], [], extra_hours=1.0, uptake=1.5)


def test_result_always_carries_caveats():
    entry = _entry("A", -112.07, 33.45)
    payload = simulate_extended_hours([entry], [], extra_hours=1.0).to_dict()
    assert any("not that anyone travelled" in c for c in payload["caveats"])
    assert any("straight-line" in c for c in payload["caveats"])


# ---------------------------------------------------------- added sites


def test_popup_site_is_labelled_simulated():
    """A hypothetical site must never be mistakable for a real HRN record."""
    s = make_popup_site(-112.07, 33.45, name="test")
    assert s.organization == "SIMULATED"
    assert s.site_id.startswith("popup-")
    assert s.is_cooling is True


def test_adding_a_site_covers_a_previously_uncovered_tract():
    entry = _entry("A", -112.07, 33.45)
    r = simulate_added_sites(
        [entry], [], [make_popup_site(-112.0703, 33.4502, name="p1")], hour=19.0
    )
    assert r.tracts_gained == 1
    assert r.intervention.added_sites == 1
    assert r.person_hours_per_site == pytest.approx(r.person_hours_gained)


def test_adding_a_distant_site_gains_nothing():
    entry = _entry("A", -112.07, 33.45)
    r = simulate_added_sites(
        [entry], [], [make_popup_site(-111.0, 34.5, name="far")], hour=19.0
    )
    assert r.tracts_gained == 0


# ------------------------------------------------------- greedy placement


def test_greedy_targets_highest_weighted_tract_first():
    """The first site must go to the worst-served tract by the allocation objective."""
    low = _entry("LOW", -112.20, 33.30, pop=1000, hours=80.0, vuln=0.2)
    high = _entry("HIGH", -112.07, 33.45, pop=9000, hours=90.0, vuln=0.9)
    plan = greedy_site_placement([low, high], [], budget=2, hour=19.0)
    assert plan[0]["target_geoid"] == "HIGH"
    assert plan[1]["target_geoid"] == "LOW"


def test_greedy_respects_budget_and_orders_placements():
    entries = [_entry(f"T{i}", -112.10 + i * 0.05, 33.40, pop=1000 * (5 - i)) for i in range(4)]
    plan = greedy_site_placement(entries, [], budget=3, hour=19.0)
    assert len(plan) == 3
    assert [p["order"] for p in plan] == [1, 2, 3]


def test_greedy_stops_when_everything_is_covered():
    entry = _entry("A", -112.07, 33.45)
    covered = make_popup_site(-112.0702, 33.4501, name="already")
    plan = greedy_site_placement([entry], [covered], budget=5, hour=19.0)
    assert plan == [], "nothing left to cover, so no sites should be proposed"


def test_greedy_rejects_zero_budget():
    with pytest.raises(ValidationError, match="budget must be positive"):
        greedy_site_placement([_entry("A", -112.07, 33.45)], [], budget=0)


def test_greedy_marginal_gains_are_reported_per_placement():
    a = _entry("A", -112.20, 33.30, pop=2000)
    b = _entry("B", -112.07, 33.45, pop=5000)
    plan = greedy_site_placement([a, b], [], budget=2, hour=19.0)
    assert all(p["person_hours_gained"] > 0 for p in plan)
    assert sum(p["tracts_gained"] for p in plan) == 2
