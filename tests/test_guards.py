"""Pre-flight guards — every rejection here is a credit not wasted on a wrong answer."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cityvigil.errors import ValidationError
from cityvigil.guards import (
    bbox_area_km2,
    canonical_aoi,
    parse_date,
    polygon_bbox,
    validate_analytic,
    validate_aoi,
    validate_date_time,
    validate_granularity,
    validate_time,
)

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ primitives


@pytest.mark.parametrize("value", [60, 80, 100])
def test_valid_granularities(value):
    assert validate_granularity(value) == value


@pytest.mark.parametrize("value", [20, 50, 90, 120, 0])
def test_invalid_granularity_mentions_the_20m_marketing_figure(value):
    with pytest.raises(ValidationError) as exc:
        validate_granularity(value)
    assert exc.value.field == "granularity"


def test_date_parsing_rejects_wrong_format():
    with pytest.raises(ValidationError, match="YYYY-MM-DD"):
        parse_date("15/07/2024")


def test_date_parsing_rejects_impossible_date():
    with pytest.raises(ValidationError, match="not a real date"):
        parse_date("2024-02-31")


def test_time_must_be_24h_hh_mm():
    assert validate_time("14:00") == "14:00"
    for bad in ("2pm", "24:00", "14:60", "1400"):
        with pytest.raises(ValidationError):
            validate_time(bad)


# -------------------------------------------------------------------- analytic


def test_exceedance_requires_threshold_and_direction():
    with pytest.raises(ValidationError) as exc:
        validate_analytic("exceedance", None, "above")
    assert exc.value.field == "threshold"

    with pytest.raises(ValidationError) as exc:
        validate_analytic("persistence", 35.0, None)
    assert exc.value.field == "direction"

    validate_analytic("exceedance", 35.0, "above")
    validate_analytic("persistence", 35.0, "below")


def test_tcm_forbids_threshold_because_it_would_be_ignored():
    """Silently-ignored parameters are how you think you asked a different question."""
    with pytest.raises(ValidationError, match="ignores threshold"):
        validate_analytic("tcm", 35.0, "above")


def test_unknown_analytic_rejected():
    with pytest.raises(ValidationError) as exc:
        validate_analytic("heatmap", None, None)
    assert exc.value.field == "analytic_type"


# ------------------------------------------------------------------ date_time


def test_filter_type_1_requires_start_time():
    with pytest.raises(ValidationError) as exc:
        validate_date_time("2024-07-15", 1, now=NOW)
    assert exc.value.field == "start_time"


def test_filter_type_4_requires_end_date():
    with pytest.raises(ValidationError) as exc:
        validate_date_time("2024-07-15", 4, now=NOW)
    assert exc.value.field == "end_date"


def test_filter_type_3_rejects_extra_fields():
    """Passing end_date to a single-day query silently changes the window."""
    with pytest.raises(ValidationError, match="does not use end_date"):
        validate_date_time("2024-07-15", 3, end_date="2024-07-21", now=NOW)


def test_valid_windows_build_expected_payload():
    assert validate_date_time("2024-07-15", 3, now=NOW) == {
        "start_date": "2024-07-15",
        "filter_type": 3,
    }
    assert validate_date_time("2024-07-15", 1, start_time="14:00", now=NOW) == {
        "start_date": "2024-07-15",
        "filter_type": 1,
        "start_time": "14:00",
    }
    assert validate_date_time(
        "2024-07-15", 4, end_date="2024-07-21", now=NOW
    ) == {"start_date": "2024-07-15", "filter_type": 4, "end_date": "2024-07-21"}


def test_archive_floor_is_enforced():
    with pytest.raises(ValidationError, match="precedes the archive start"):
        validate_date_time("2020-12-31", 3, now=NOW)


def test_end_date_before_start_date_rejected():
    with pytest.raises(ValidationError, match="before start_date"):
        validate_date_time("2024-07-15", 4, end_date="2024-07-01", now=NOW)


def test_31_day_range_is_allowed():
    """Measured live: 31 days is the longest range the API accepts."""
    validate_date_time("2022-07-01", 4, end_date="2022-07-31", now=NOW)


def test_32_day_range_is_rejected_with_tiling_advice():
    """32 days fails server-side; catch it locally and say what to do instead."""
    with pytest.raises(ValidationError, match="31-day"):
        validate_date_time("2022-07-01", 4, end_date="2022-08-01", now=NOW)


def test_full_season_range_is_rejected():
    """A May-September window is what prompted finding this limit."""
    with pytest.raises(ValidationError) as exc:
        validate_date_time("2022-05-01", 4, end_date="2022-09-30", now=NOW)
    assert exc.value.field == "end_date"
    assert "month-sized" in str(exc.value)


def test_end_time_must_follow_start_time():
    with pytest.raises(ValidationError, match="must be after"):
        validate_date_time("2024-07-15", 2, start_time="15:00", end_time="09:00", now=NOW)


def test_forecast_horizon_caps_at_12_hours():
    """The 6-48h ambition in the original concept dies here, by design."""
    with pytest.raises(ValidationError, match="forecast horizon"):
        validate_date_time("2026-08-28", 3, now=NOW)  # ~36h ahead


def test_within_forecast_horizon_is_allowed():
    validate_date_time("2026-08-26", 1, start_time="22:00", now=NOW)  # +10h


# ------------------------------------------------------------------------ AOI


def test_bbox_extracted_from_feature_collection(phoenix_aoi):
    w, s, e, n = polygon_bbox(phoenix_aoi)
    assert (round(w, 4), round(s, 4), round(e, 4), round(n, 4)) == (
        -112.08,
        33.443,
        -112.068,
        33.453,
    )


def test_phoenix_aoi_accepted_and_measured(phoenix_aoi):
    report = validate_aoi(phoenix_aoi)
    assert report["region"] == "conus"
    assert 1.0 < report["area_km2"] < 1.5


def test_non_us_aoi_rejected(dubai_aoi):
    with pytest.raises(ValidationError, match="United States only"):
        validate_aoi(dubai_aoi)


def test_swapped_coordinates_detected():
    """[lat, lon] instead of [lon, lat] gives a latitude above 90."""
    swapped = {
        "type": "Polygon",
        "coordinates": [
            [[33.443, -112.08], [33.453, -112.08], [33.453, -112.07], [33.443, -112.08]]
        ],
    }
    with pytest.raises(ValidationError, match="coordinates may be swapped"):
        validate_aoi(swapped)


def test_area_cap_enforced_with_tiling_advice():
    huge = {
        "type": "Polygon",
        "coordinates": [
            [[-118.5, 33.7], [-117.6, 33.7], [-117.6, 34.3], [-118.5, 34.3], [-118.5, 33.7]]
        ],
    }
    with pytest.raises(ValidationError, match="Tile the AOI"):
        validate_aoi(huge, plan="hackathon")


def test_empty_aoi_rejected():
    with pytest.raises(ValidationError, match="no coordinates"):
        validate_aoi({"type": "Polygon", "coordinates": []})


def test_area_estimate_is_sane():
    """One degree square at the equator is roughly 12,300 km²."""
    assert bbox_area_km2((0.0, 0.0, 1.0, 1.0)) == pytest.approx(12310, rel=0.02)


# ------------------------------------------------------------- canonical AOI


def test_canonical_aoi_strips_properties(phoenix_aoi):
    """A label on the AOI must not make it a different question."""
    labelled = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Central Phoenix", "owner": "city"},
                "geometry": phoenix_aoi["features"][0]["geometry"],
            }
        ],
    }
    assert canonical_aoi(labelled) == canonical_aoi(phoenix_aoi)
    assert canonical_aoi(labelled)["features"][0]["properties"] == {}


def test_canonical_aoi_unwraps_bare_geometry(phoenix_aoi):
    """FeatureCollection, Feature and bare geometry must all canonicalise alike."""
    geometry = phoenix_aoi["features"][0]["geometry"]
    feature = {"type": "Feature", "properties": {"x": 1}, "geometry": geometry}
    assert canonical_aoi(geometry) == canonical_aoi(feature) == canonical_aoi(phoenix_aoi)


def test_canonical_aoi_absorbs_float_noise(phoenix_aoi):
    """Sub-centimetre float noise must not change the cache key."""
    noisy = {
        "type": "Polygon",
        "coordinates": [
            [[lon + 1e-12, lat - 1e-12] for lon, lat in phoenix_aoi["features"][0]["geometry"]["coordinates"][0]]
        ],
    }
    assert canonical_aoi(noisy) == canonical_aoi(phoenix_aoi)


def test_canonical_aoi_preserves_distinct_footprints(phoenix_aoi, dubai_aoi):
    assert canonical_aoi(phoenix_aoi) != canonical_aoi(dubai_aoi)


def test_canonical_aoi_rejects_non_polygon():
    with pytest.raises(ValidationError, match="no Polygon or MultiPolygon"):
        canonical_aoi({"type": "Point", "coordinates": [-112.07, 33.44]})
