"""Cooling-centre supply: hours parsing, coverage, and the evening gap."""

from __future__ import annotations

import pytest

from cityvigil.geometry import MultiPolygon, Polygon
from cityvigil.supply import (
    COOLING_TYPES,
    CoolingSite,
    coverage_for_tracts,
    open_site_count_by_hour,
    parse_clock,
    supply_summary,
)
from cityvigil.tracts import Tract


def _site(
    site_id: str,
    lon: float,
    lat: float,
    *,
    site_type: str = "Cooling Center",
    hours: dict[str, tuple[float, float]] | None = None,
    ada: bool | None = True,
) -> CoolingSite:
    return CoolingSite(
        site_id=site_id,
        name=f"Site {site_id}",
        organization="Org",
        city="Phoenix",
        address="somewhere",
        site_type=site_type,
        lon=lon,
        lat=lat,
        hours={"Wednesday": (9.0, 17.0)} if hours is None else hours,
        ada_accessible=ada,
        allows_pets=False,
        season_start="2026-05-01",
        season_end="2026-09-30",
    )


def _tract(geoid: str, lon: float, lat: float, half: float = 0.002) -> Tract:
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
        geoid=geoid,
        name=f"Tract {geoid}",
        geometry=geom,
        population=1000,
        age65=100,
        poverty150=200,
        no_vehicle=50,
        disability=100,
        uninsured=100,
        svi_percentile=0.5,
        jobs_total=100,
        jobs_outdoor=10,
    )


# ----------------------------------------------------------- clock parsing


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1:00 PM", 13.0),
        ("9:00 AM", 9.0),
        ("12:00 PM", 12.0),
        ("12:00 AM", 0.0),
        ("5:30 PM", 17.5),
        ("11:45 AM", 11.75),
        ("7 PM", 19.0),
        ("17:00", 17.0),
        ("8", 8.0),
        ("  3:15 p.m.  ", 15.25),
    ],
)
def test_parse_clock_accepts_real_formats(text, expected):
    assert parse_clock(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", [None, "", "Closed", "n/a", "-", "varies", "by appt"])
def test_parse_clock_returns_none_rather_than_guessing(text):
    """Hand-entered hours must fail closed, never be invented."""
    assert parse_clock(text) is None


def test_noon_and_midnight_are_not_confused():
    assert parse_clock("12:00 PM") == 12.0
    assert parse_clock("12:00 AM") == 0.0


# ------------------------------------------------------------------- sites


def test_cooling_types_exclude_hydration():
    """Water is not refuge. Hydration stations must never count as cooling."""
    assert "Cooling Center" in COOLING_TYPES
    assert "Respite Center" in COOLING_TYPES
    assert "Hydration Station" not in COOLING_TYPES
    assert _site("h", 0, 0, site_type="Hydration Station").is_cooling is False


def test_open_at_respects_the_window():
    site = _site("a", 0, 0, hours={"Wednesday": (9.0, 17.0)})
    assert site.open_at("Wednesday", 9.0) is True
    assert site.open_at("Wednesday", 16.9) is True
    assert site.open_at("Wednesday", 17.0) is False, "closing hour is exclusive"
    assert site.open_at("Wednesday", 8.5) is False


def test_unknown_hours_count_as_closed():
    """Overstating availability in a heat-safety tool is the dangerous error."""
    site = _site("a", 0, 0, hours={})
    assert site.open_at("Wednesday", 14.0) is False
    assert site.closing_hour("Wednesday") is None


def test_open_at_is_per_weekday():
    site = _site("a", 0, 0, hours={"Saturday": (10.0, 14.0)})
    assert site.open_at("Saturday", 12.0) is True
    assert site.open_at("Wednesday", 12.0) is False


# ---------------------------------------------------------------- coverage


def test_walkable_coverage_counts_only_open_sites():
    tract = _tract("A", -112.07, 33.45)
    near_open = _site("open", -112.071, 33.4505, hours={"Wednesday": (9.0, 20.0)})
    near_shut = _site("shut", -112.0705, 33.4502, hours={"Wednesday": (9.0, 15.0)})

    at_ten = coverage_for_tracts([tract], [near_open, near_shut], hour=10.0)["A"]
    assert at_ten.open_within_walk == 2
    assert at_ten.sites_within_walk == 2

    at_seventeen = coverage_for_tracts([tract], [near_open, near_shut], hour=17.0)["A"]
    assert at_seventeen.open_within_walk == 1, "the 15:00 closer no longer helps"
    assert at_seventeen.sites_within_walk == 2, "but it is still on the map"
    assert at_seventeen.walkable_cover is True


def test_tract_with_no_open_site_reports_no_cover():
    tract = _tract("A", -112.07, 33.45)
    far = _site("far", -111.5, 33.9, hours={"Wednesday": (9.0, 20.0)})
    cover = coverage_for_tracts([tract], [far], hour=12.0)["A"]
    assert cover.open_within_walk == 0
    assert cover.walkable_cover is False
    assert cover.nearest_open_km is not None and cover.nearest_open_km > 10


def test_no_open_sites_at_all_gives_none_distance():
    tract = _tract("A", -112.07, 33.45)
    shut = _site("shut", -112.071, 33.4505, hours={"Wednesday": (9.0, 12.0)})
    cover = coverage_for_tracts([tract], [shut], hour=20.0)["A"]
    assert cover.nearest_open_km is None
    assert cover.nearest_open_name is None
    assert cover.walkable_cover is False


def test_hydration_counted_separately_from_cooling():
    tract = _tract("A", -112.07, 33.45)
    water = _site("w", -112.0705, 33.4503, site_type="Hydration Station")
    cover = coverage_for_tracts([tract], [water], hour=12.0)["A"]
    assert cover.hydration_within_walk == 1
    assert cover.sites_within_walk == 0, "hydration is not cooling capacity"
    assert cover.walkable_cover is False


def test_nearest_open_site_is_named():
    tract = _tract("A", -112.07, 33.45)
    close = _site("close", -112.0702, 33.4501, hours={"Wednesday": (9.0, 20.0)})
    cover = coverage_for_tracts([tract], [close], hour=12.0)["A"]
    assert cover.nearest_open_name == "Site close"
    assert cover.nearest_open_km == pytest.approx(0.0, abs=0.2)


# --------------------------------------------------------- hours profile


def test_open_count_by_hour_traces_the_evening_collapse():
    """The real network's capacity falls away through the evening; model that shape."""
    sites = [
        _site("a", 0, 0, hours={"Wednesday": (9.0, 17.0)}),
        _site("b", 0, 0, hours={"Wednesday": (9.0, 18.0)}),
        _site("c", 0, 0, hours={"Wednesday": (9.0, 21.0)}),
    ]
    counts = open_site_count_by_hour(sites)
    assert counts[12] == 3
    assert counts[17] == 2
    assert counts[18] == 1
    assert counts[21] == 0
    assert counts[3] == 0


def test_hours_profile_covers_all_24_hours():
    counts = open_site_count_by_hour([_site("a", 0, 0)])
    assert sorted(counts) == list(range(24))


def test_summary_reports_composition_and_vintage_caveat():
    sites = [
        _site("a", 0, 0),
        _site("b", 0, 0, site_type="Respite Center"),
        _site("c", 0, 0, site_type="Hydration Station"),
    ]
    summary = supply_summary(sites)
    assert summary["n_sites"] == 3
    assert summary["n_cooling_sites"] == 2, "hydration excluded from cooling count"
    assert summary["by_type"]["Hydration Station"] == 1
    assert "current season" in summary["vintage_caveat"]
    assert summary["median_weekday_closing_hour"] == 17.0
