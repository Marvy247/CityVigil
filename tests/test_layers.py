"""Layer semantics, parsing, and the recorded rationale for each choice."""

from __future__ import annotations

import pytest

from cityvigil.audit import AuditLog
from cityvigil.errors import ValidationError
from cityvigil.layers import (
    LAYER_GUIDE,
    ExposureLayers,
    explain_layer_choice,
    parse_surface,
)
from conftest import scripted_api


# ------------------------------------------------------------------- parsing


def test_tcm_parsed_into_celsius(tcm_result):
    surface = parse_surface(tcm_result, "tcm")
    assert surface.units == "celsius"
    assert len(surface) == 3
    assert surface.tiles[0].value == pytest.approx(35.9436)
    assert surface.tiles[0].maximum == pytest.approx(40.49)


def test_fahrenheit_tcm_payload_is_converted(tcm_result):
    """If the API ever returns F, the surface must still be Celsius."""
    for f in tcm_result["map_data"]["features"]:
        p = f["properties"]
        for key in ("average_temperature", "min_temperature", "max_temperature"):
            p[key] = p[key] * 9 / 5 + 32
    surface = parse_surface(tcm_result, "tcm")
    assert surface.tiles[0].value == pytest.approx(35.9436, abs=1e-3)


def test_explicit_tile_unit_overrides_inference(tcm_result):
    surface = parse_surface(tcm_result, "tcm", tile_unit="C")
    assert surface.tiles[0].value == pytest.approx(35.9436)


def test_exceedance_parsed_as_hours(exceedance_result):
    surface = parse_surface(exceedance_result, "exceedance", threshold_c=35.0)
    assert surface.units == "hour"
    assert surface.threshold_c == 35.0
    assert surface.values == pytest.approx([40.5626, 25.5136, 33.9012])


def test_tcm_payload_sent_as_exceedance_is_caught(tcm_result):
    """The exact confident-wrong-answer failure mode: mismatched schema."""
    with pytest.raises(ValidationError, match="looks like a tcm payload"):
        parse_surface(tcm_result, "exceedance")


def test_empty_response_explains_likely_cause(tcm_result):
    tcm_result["map_data"]["features"] = []
    with pytest.raises(ValidationError, match="outside US coverage"):
        parse_surface(tcm_result, "tcm")


# ------------------------------------------------------------------ surfaces


def test_hottest_ranks_by_value(exceedance_result):
    surface = parse_surface(exceedance_result, "exceedance", threshold_c=35.0)
    top = surface.hottest(2)
    assert [t.tile_id for t in top] == [0, 2]


def test_summary_reports_units_and_span(exceedance_result):
    summary = parse_surface(exceedance_result, "exceedance", threshold_c=35.0).summary()
    assert summary["units"] == "hour"
    assert summary["n_tiles"] == 3
    assert summary["max"] == pytest.approx(40.5626)
    assert summary["threshold_c"] == 35.0


def test_geojson_export_carries_provenance(exceedance_result):
    surface = parse_surface(
        exceedance_result, "exceedance", threshold_c=35.0, rationale="because hours"
    )
    gj = surface.to_geojson()
    assert gj["type"] == "FeatureCollection"
    assert gj["properties"]["analytic_type"] == "exceedance"
    assert gj["properties"]["rationale"] == "because hours"
    assert len(gj["features"]) == 3
    assert gj["features"][0]["properties"]["units"] == "hour"


def test_geojson_omits_null_envelope_for_analysis_layers(exceedance_result):
    """Analysis tiles have no min/max, so the keys must be absent, not null."""
    props = parse_surface(exceedance_result, "exceedance", threshold_c=35.0).to_geojson()[
        "features"
    ][0]["properties"]
    assert "min" not in props and "max" not in props


def test_geojson_keeps_envelope_for_tcm(tcm_result):
    props = parse_surface(tcm_result, "tcm").to_geojson()["features"][0]["properties"]
    assert props["min"] == pytest.approx(29.16)
    assert props["max"] == pytest.approx(40.49)


def test_geojson_rounds_coordinates(tcm_result):
    """Precision beyond ~0.1 m is payload weight with no analytical value."""
    tcm_result["map_data"]["features"][0]["geometry"]["coordinates"] = [
        [[-112.130320301078, 33.399705671689645]] * 4
    ]
    coords = parse_surface(tcm_result, "tcm").to_geojson()["features"][0]["geometry"][
        "coordinates"
    ]
    assert coords[0][0] == [-112.13032, 33.399706]


def test_tile_centroid_is_inside_its_own_polygon(tcm_result):
    tile = parse_surface(tcm_result, "tcm").tiles[0]
    lon, lat = tile.centroid
    ring = tile.geometry["coordinates"][0]
    assert min(p[0] for p in ring) <= lon <= max(p[0] for p in ring)
    assert min(p[1] for p in ring) <= lat <= max(p[1] for p in ring)


# -------------------------------------------------------------- layer choice


def test_every_intent_has_a_layer_and_a_rationale():
    assert set(LAYER_GUIDE) == {"how_hot", "when_peak", "how_long", "any_relief"}
    for intent, (analytic_type, rationale) in LAYER_GUIDE.items():
        assert analytic_type in ("tcm", "time_of_measure", "exceedance", "persistence")
        assert len(rationale) > 40, f"{intent} rationale is too thin to defend"


def test_exceedance_and_persistence_are_distinguished():
    """The distinction that stops us under-protecting no-relief neighbourhoods."""
    assert "continuous" in LAYER_GUIDE["any_relief"][1]
    assert "person-hours" in LAYER_GUIDE["how_long"][1]


def test_explain_layer_choice_text():
    text = explain_layer_choice("any_relief")
    assert text.startswith("any_relief -> persistence")


def test_explain_rejects_unknown_intent():
    with pytest.raises(ValidationError, match="unknown intent"):
        explain_layer_choice("how_humid")  # type: ignore[arg-type]


def test_audit_requires_non_empty_rationale():
    log = AuditLog()
    with pytest.raises(ValueError, match="non-empty rationale"):
        log.layer_choice("tcm", question="q", rationale="   ")


# ---------------------------------------------------- intent-driven fetching


def test_how_hot_uses_tcm_and_records_why(make_client, phoenix_aoi, tcm_result):
    client = make_client(scripted_api(tcm_result))
    surface = ExposureLayers(client).how_hot(phoenix_aoi, start_date="2024-07-15")

    assert surface.analytic_type == "tcm"
    assert surface.units == "celsius"

    choices = client.audit.of_kind("layer_choice")
    assert len(choices) == 1
    assert choices[0].detail["analytic_type"] == "tcm"
    assert "returns per-tile" in choices[0].detail["rationale"]


def test_how_long_dangerous_uses_exceedance(make_client, phoenix_aoi, exceedance_result):
    client = make_client(scripted_api(exceedance_result))
    surface = ExposureLayers(client).how_long_dangerous(
        phoenix_aoi, threshold=35.0, start_date="2024-07-15", end_date="2024-07-21"
    )
    assert surface.analytic_type == "exceedance"
    assert surface.units == "hour"
    assert surface.threshold_c == 35.0

    post = next(kw for m, _, kw in client._session.calls if m == "POST")
    assert post["json"]["analytic_type"] == "exceedance"
    assert post["json"]["direction"] == "above"
    assert post["json"]["date_time"]["filter_type"] == 4


def test_any_relief_uses_persistence(make_client, phoenix_aoi, exceedance_result):
    exceedance_result["stats_data"]["analytic_type"] = "persistence"
    client = make_client(scripted_api(exceedance_result))
    surface = ExposureLayers(client).any_relief(
        phoenix_aoi, threshold=35.0, start_date="2024-07-15", end_date="2024-07-21"
    )
    assert surface.analytic_type == "persistence"
    post = next(kw for m, _, kw in client._session.calls if m == "POST")
    assert post["json"]["analytic_type"] == "persistence"


def test_when_peak_uses_time_of_measure(make_client, phoenix_aoi, exceedance_result):
    exceedance_result["stats_data"] = {"analytic_type": "time_of_measure", "units": "utc_hour"}
    client = make_client(scripted_api(exceedance_result))
    surface = ExposureLayers(client).when_peak(phoenix_aoi, start_date="2024-07-15")
    assert surface.analytic_type == "time_of_measure"
    post = next(kw for m, _, kw in client._session.calls if m == "POST")
    assert post["json"]["analytic_type"] == "time_of_measure"
    assert "threshold" not in post["json"]


def test_fahrenheit_threshold_recorded_in_celsius(make_client, phoenix_aoi, exceedance_result):
    client = make_client(scripted_api(exceedance_result))
    surface = ExposureLayers(client).how_long_dangerous(
        phoenix_aoi,
        threshold=100.0,
        threshold_unit="F",
        start_date="2024-07-15",
        end_date="2024-07-21",
    )
    assert surface.threshold_c == pytest.approx(37.7778, abs=1e-3)
