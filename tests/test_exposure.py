"""Tract loading, the vulnerability model, and the person-hours join.

These use small synthetic tracts so the arithmetic is checkable by hand. The
real-data path is exercised separately by ``scripts/analyze_phoenix.py``, which
runs against the actual CDC, TIGERweb and LODES files.
"""

from __future__ import annotations

import pytest

from cityvigil.errors import ValidationError
from cityvigil.exposure import assign_tiles, build_exposure_report
from cityvigil.geometry import MultiPolygon, Polygon
from cityvigil.layers import HeatSurface, Tile
from cityvigil.tracts import (
    CDC_MISSING,
    Tract,
    TractCollection,
    _clean_count,
    _clean_percentile,
)
from cityvigil.vulnerability import (
    DEFAULT_WEIGHTS,
    VulnerabilityModel,
    Weights,
    percentile_ranks,
)


def _box(x0: float, y0: float, x1: float, y1: float) -> MultiPolygon:
    return MultiPolygon((Polygon(((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))),))


def _tract(
    geoid: str,
    *,
    population: int = 1000,
    age65: int = 100,
    svi: float | None = 0.5,
    jobs_total: int = 500,
    jobs_outdoor: int = 50,
    box: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0),
) -> Tract:
    return Tract(
        geoid=geoid,
        name=f"Tract {geoid}",
        geometry=_box(*box),
        population=population,
        age65=age65,
        poverty150=int(population * 0.2),
        no_vehicle=int(population * 0.05),
        disability=int(population * 0.1),
        uninsured=int(population * 0.1),
        svi_percentile=svi,
        jobs_total=jobs_total,
        jobs_outdoor=jobs_outdoor,
    )


def _surface(
    values: dict[int, float],
    analytic_type: str = "exceedance",
    *,
    threshold_c: float | None = 37.78,
) -> HeatSurface:
    tiles = []
    for tile_id, value in values.items():
        # Tiny squares marching along y so each can be placed in a chosen tract.
        y = 0.1 + tile_id * 0.5
        geom = {
            "type": "Polygon",
            "coordinates": [[[0.1, y], [0.2, y], [0.2, y + 0.05], [0.1, y + 0.05], [0.1, y]]],
        }
        tiles.append(Tile(tile_id=tile_id, geometry=geom, value=value))
    return HeatSurface(
        analytic_type=analytic_type,
        units="hour",
        tiles=tiles,
        threshold_c=threshold_c,
        window={"start_date": "2024-07-15", "end_date": "2024-07-21", "filter_type": 4},
    )


# ------------------------------------------------------------ CDC sentinel


def test_cdc_missing_sentinel_becomes_zero_for_counts():
    """-999 read as a count would corrupt every population total."""
    assert _clean_count(CDC_MISSING) == 0
    assert _clean_count(-1) == 0
    assert _clean_count("2381") == 2381
    assert _clean_count(None) == 0


def test_cdc_missing_sentinel_becomes_none_for_percentiles():
    """-999 read as a percentile would dominate any weighted index."""
    assert _clean_percentile(CDC_MISSING) is None
    assert _clean_percentile(-999.0) is None
    assert _clean_percentile(1.5) is None, "out of range is not a percentile"
    assert _clean_percentile(0.9988) == pytest.approx(0.9988)
    assert _clean_percentile("bad") is None


# --------------------------------------------------------------- collection


def test_collection_locates_points_and_totals_population():
    a = _tract("A", population=100, box=(0.0, 0.0, 1.0, 1.0))
    b = _tract("B", population=250, box=(1.0, 0.0, 2.0, 1.0))
    col = TractCollection({"A": a, "B": b})

    assert col.locate(0.5, 0.5).geoid == "A"
    assert col.locate(1.5, 0.5).geoid == "B"
    assert col.locate(9.0, 9.0) is None
    assert col.total_population() == 350
    assert len(col) == 2


def test_collection_summary_counts_data_gaps():
    col = TractCollection(
        {
            "A": _tract("A", population=0, svi=None),
            "B": _tract("B", population=500, svi=0.4),
        }
    )
    summary = col.summary()
    assert summary["zero_population_tracts"] == 1
    assert summary["missing_svi_percentile"] == 1
    assert summary["total_population"] == 500


def test_shares_are_safe_when_population_is_zero():
    """Twelve real Maricopa tracts have zero population."""
    t = _tract("Z", population=0, age65=0, jobs_total=0, jobs_outdoor=0)
    assert t.elderly_share == 0.0
    assert t.poverty_share == 0.0
    assert t.outdoor_job_share == 0.0


# ------------------------------------------------------------- percentiles


def test_percentile_ranks_span_zero_to_one():
    assert percentile_ranks([1.0, 2.0, 3.0]) == [0.0, 0.5, 1.0]


def test_percentile_ranks_average_ties():
    """Many tracts have exactly zero outdoor workers; they must rank equally."""
    ranks = percentile_ranks([0.0, 0.0, 0.0, 5.0])
    assert ranks[0] == ranks[1] == ranks[2]
    assert ranks[3] == 1.0


def test_percentile_ranks_edge_cases():
    assert percentile_ranks([]) == []
    assert percentile_ranks([7.0]) == [0.5]


# ------------------------------------------------------- vulnerability model


def test_weights_normalise_and_reject_nonsense():
    assert Weights(1, 1, 2).total == 4
    with pytest.raises(ValidationError):
        Weights(svi=-1)
    with pytest.raises(ValidationError, match="at least one weight"):
        Weights(0, 0, 0)


def test_score_combines_components_with_normalised_weights():
    col = TractCollection({"A": _tract("A", svi=1.0, age65=500, population=1000)})
    model = VulnerabilityModel(col, Weights(svi=0.5, elderly=0.3, outdoor_workers=0.2))
    score = model.score(col["A"])
    # Single tract: both percentile ranks are 0.5 by definition.
    expected = 1.0 * 0.5 + 0.5 * 0.3 + 0.5 * 0.2
    assert score.score == pytest.approx(expected)
    assert score.svi_imputed is False


def test_missing_svi_renormalises_instead_of_imputing():
    """A tract with no CDC percentile must not be scored as if SVI were zero."""
    col = TractCollection({"A": _tract("A", svi=None)})
    model = VulnerabilityModel(col, Weights(svi=0.5, elderly=0.3, outdoor_workers=0.2))
    score = model.score(col["A"])

    assert score.svi_imputed is True
    assert "svi" not in score.components
    assert sum(score.weights_used.values()) == pytest.approx(1.0)
    # Remaining weights become 0.6 / 0.4, both applied to a rank of 0.5.
    assert score.score == pytest.approx(0.5)


def test_higher_svi_scores_higher():
    col = TractCollection(
        {
            "LOW": _tract("LOW", svi=0.1, box=(0.0, 0.0, 1.0, 1.0)),
            "HIGH": _tract("HIGH", svi=0.9, box=(1.0, 0.0, 2.0, 1.0)),
        }
    )
    model = VulnerabilityModel(col)
    assert model.score(col["HIGH"]).score > model.score(col["LOW"]).score


def test_ranks_are_county_relative_not_aoi_relative():
    """Scores must not change when a different subset is analysed."""
    tracts = {
        f"T{i}": _tract(f"T{i}", age65=i * 100, population=1000, svi=0.5) for i in range(1, 6)
    }
    model = VulnerabilityModel(TractCollection(tracts))
    before = model.score(tracts["T3"]).score
    # Scoring a subset must not re-rank anything.
    model.score_many([tracts["T1"], tracts["T3"]])
    assert model.score(tracts["T3"]).score == pytest.approx(before)


def test_outdoor_density_used_when_area_supplied():
    """A small tract with the same job count is denser, so more vulnerable."""
    col = TractCollection(
        {
            "BIG": _tract("BIG", jobs_outdoor=100, box=(0.0, 0.0, 1.0, 1.0)),
            "SMALL": _tract("SMALL", jobs_outdoor=100, box=(1.0, 0.0, 2.0, 1.0)),
        }
    )
    model = VulnerabilityModel(col, area_km2={"BIG": 100.0, "SMALL": 1.0})
    assert (
        model.score(col["SMALL"]).components["outdoor_workers"]
        > model.score(col["BIG"]).components["outdoor_workers"]
    )


def test_describe_exposes_weights_and_caveat():
    model = VulnerabilityModel(TractCollection({"A": _tract("A")}), DEFAULT_WEIGHTS)
    described = model.describe()
    assert described["weights"]["svi"] == 0.5
    assert "not fitted" in described["caveat"]
    assert "svi" in described["component_sources"]


def test_explain_is_human_readable():
    col = TractCollection({"A": _tract("A", svi=0.8)})
    text = VulnerabilityModel(col).score(col["A"]).explain()
    assert "svi" in text and "elderly" in text


# ---------------------------------------------------------------- exposure


def _two_tract_setup():
    # Tile 0 centroid ~ (0.15, 0.125) -> A;  tile 1 centroid ~ (0.15, 0.625) -> B
    a = _tract("A", population=1000, age65=100, svi=0.5, box=(0.0, 0.0, 1.0, 0.5))
    b = _tract("B", population=2000, age65=800, svi=0.9, box=(0.0, 0.5, 1.0, 1.0))
    col = TractCollection({"A": a, "B": b})
    return col, VulnerabilityModel(col)


def test_person_hours_are_population_times_mean_hours():
    col, model = _two_tract_setup()
    report = build_exposure_report(_surface({0: 10.0, 1: 20.0}), col, model)
    by_geoid = {e.tract.geoid: e for e in report.tracts}

    assert by_geoid["A"].person_hours == pytest.approx(1000 * 10.0)
    assert by_geoid["B"].person_hours == pytest.approx(2000 * 20.0)
    assert by_geoid["B"].elderly_person_hours == pytest.approx(800 * 20.0)


def test_totals_sum_across_tracts():
    col, model = _two_tract_setup()
    totals = build_exposure_report(_surface({0: 10.0, 1: 20.0}), col, model).totals()
    assert totals["person_hours"] == pytest.approx(10_000 + 40_000)
    assert totals["population"] == 3000
    assert totals["tiles_matched"] == 2
    assert totals["tiles_unmatched"] == 0


def test_snapshot_surface_is_rejected_for_person_hours():
    """Degrees cannot be multiplied by population to make person-hours."""
    col, model = _two_tract_setup()
    with pytest.raises(ValidationError, match="require an exceedance surface"):
        build_exposure_report(_surface({0: 36.0}, analytic_type="tcm"), col, model)


def test_unmatched_tiles_are_counted_not_silently_dropped():
    col, model = _two_tract_setup()
    far = HeatSurface(
        analytic_type="exceedance",
        units="hour",
        tiles=[
            Tile(
                tile_id=99,
                geometry={
                    "type": "Polygon",
                    "coordinates": [[[50, 50], [51, 50], [51, 51], [50, 51], [50, 50]]],
                },
                value=5.0,
            )
        ],
        threshold_c=37.78,
    )
    report = build_exposure_report(far, col, model)
    assert report.unmatched_tiles == 1
    assert report.totals()["tiles_matched"] == 0


def test_persistence_is_carried_but_never_summed_into_exceedance():
    col, model = _two_tract_setup()
    report = build_exposure_report(
        _surface({0: 90.0, 1: 90.0}),
        col,
        model,
        persistence=_surface({0: 8.0, 1: 8.0}),
    )
    entry = report.tracts[0]
    assert entry.mean_persistence_h == pytest.approx(8.0)
    # Person-hours must reflect exceedance alone, not exceedance + persistence.
    assert entry.person_hours == pytest.approx(entry.tract.population * 90.0)


def test_vulnerability_weighting_reorders_priorities():
    """The whole point: a smaller, more vulnerable tract can outrank a bigger one."""
    a = _tract("BIG_YOUNG", population=10_000, age65=100, svi=0.05, box=(0.0, 0.0, 1.0, 0.5))
    b = _tract("SMALL_OLD", population=6_000, age65=3_000, svi=0.99, box=(0.0, 0.5, 1.0, 1.0))
    col = TractCollection({"BIG_YOUNG": a, "SMALL_OLD": b})
    model = VulnerabilityModel(col)

    report = build_exposure_report(_surface({0: 50.0, 1: 50.0}), col, model)
    raw = [e.tract.geoid for e in report.ranked_by_person_hours()]
    weighted = [e.tract.geoid for e in report.ranked()]

    assert raw[0] == "BIG_YOUNG", "raw exposure favours the larger population"
    assert weighted[0] == "SMALL_OLD", "weighting favours the more vulnerable tract"


def test_rank_shift_reports_movement():
    a = _tract("BIG_YOUNG", population=10_000, age65=100, svi=0.05, box=(0.0, 0.0, 1.0, 0.5))
    b = _tract("SMALL_OLD", population=6_000, age65=3_000, svi=0.99, box=(0.0, 0.5, 1.0, 1.0))
    col = TractCollection({"BIG_YOUNG": a, "SMALL_OLD": b})
    shift = build_exposure_report(
        _surface({0: 50.0, 1: 50.0}), col, VulnerabilityModel(col)
    ).rank_shift()
    top = shift[0]
    assert top["geoid"] == "SMALL_OLD"
    assert top["moved_up"] == 1


def test_worker_hours_are_labelled_upper_bound_and_kept_separate():
    col, model = _two_tract_setup()
    report = build_exposure_report(_surface({0: 10.0, 1: 10.0}), col, model)
    totals = report.totals()
    # Worker hours must not be inside the resident person-hours total.
    assert totals["person_hours"] == pytest.approx(1000 * 10 + 2000 * 10)
    assert "worker_exposure_hours_upper_bound" in totals


def test_assignment_can_be_reused_across_layers():
    col, model = _two_tract_setup()
    exceedance = _surface({0: 10.0, 1: 20.0})
    assignment = assign_tiles(exceedance, col)
    assert assignment == {0: "A", 1: "B"}

    report = build_exposure_report(exceedance, col, model, assignment=assignment)
    assert report.totals()["tiles_matched"] == 2


def test_report_serialises_with_model_provenance():
    col, model = _two_tract_setup()
    payload = build_exposure_report(_surface({0: 10.0, 1: 20.0}), col, model).to_dict()
    assert "weights" in payload["model"]
    assert payload["totals"]["n_tracts"] == 2
    assert payload["tracts"][0]["vulnerability"]["explanation"]
