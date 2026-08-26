"""Validation metrics and the handling of censored outcome data."""

from __future__ import annotations

import pytest

from cityvigil.geometry import MultiPolygon, Polygon
from cityvigil.validation import (
    DISCLOSURE_THRESHOLD,
    SUPPRESSED,
    ZipOutcome,
    ZipScore,
    auc,
    outcome_summary,
    top_k_precision,
    validate,
)


def _zip_outcome(code: str, deaths: int | None) -> ZipOutcome:
    geom = MultiPolygon(
        (Polygon(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0))),)
    )
    return ZipOutcome(zip_code=code, geometry=geom, deaths=deaths)


def _score(code: str, weighted: float, heat: float, deaths: int | None) -> ZipScore:
    return ZipScore(
        zip_code=code,
        n_tracts=3,
        population=10_000,
        weighted_person_hours=weighted,
        person_hours=weighted * 1.5,
        mean_exceedance_h=heat,
        deaths=deaths,
        high_mortality=deaths is not None and deaths >= DISCLOSURE_THRESHOLD,
    )


# --------------------------------------------------------------- censoring


def test_suppressed_sentinel_is_not_a_count():
    """-999 read as a death count would invert the entire ranking."""
    assert SUPPRESSED == -999
    suppressed = _zip_outcome("85001", None)
    assert suppressed.suppressed is True
    assert suppressed.high_mortality is False


def test_negative_label_is_an_observation_not_a_guess():
    """A suppressed ZIP is known to be below the threshold, so False is real."""
    assert _zip_outcome("85001", None).high_mortality is False
    assert _zip_outcome("85002", 5).high_mortality is False
    assert _zip_outcome("85003", DISCLOSURE_THRESHOLD).high_mortality is True


def test_outcome_summary_counts_censoring():
    outcomes = {
        "a": _zip_outcome("a", 27),
        "b": _zip_outcome("b", 6),
        "c": _zip_outcome("c", None),
        "d": _zip_outcome("d", None),
    }
    s = outcome_summary(outcomes)
    assert s["n_zips"] == 4
    assert s["n_published"] == 2
    assert s["n_suppressed"] == 2
    assert s["n_high_mortality"] == 2
    assert s["published_deaths_total"] == 33
    assert s["min_published"] == 6


# ------------------------------------------------------------------- AUC


def test_auc_perfect_separation():
    assert auc([3.0, 4.0, 1.0, 2.0], [True, True, False, False]) == 1.0


def test_auc_perfect_inversion():
    assert auc([1.0, 2.0, 3.0, 4.0], [True, True, False, False]) == 0.0


def test_auc_coin_flip_on_all_ties():
    assert auc([1.0, 1.0, 1.0, 1.0], [True, True, False, False]) == 0.5


def test_auc_counts_ties_as_half():
    # One positive (2.0) vs negatives (1.0, 2.0): one win, one tie -> 0.75
    assert auc([2.0, 1.0, 2.0], [True, False, False]) == 0.75


def test_auc_undefined_with_one_class():
    assert auc([1.0, 2.0], [True, True]) is None
    assert auc([1.0, 2.0], [False, False]) is None


def test_auc_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        auc([1.0, 2.0], [True])


def test_auc_matches_hand_computed_value():
    """Positives {3,1}, negatives {2,0}: wins = 3>2,3>0,1>0 = 3 of 4."""
    assert auc([3.0, 1.0, 2.0, 0.0], [True, True, False, False]) == 0.75


# ----------------------------------------------------------- precision@k


def test_top_k_precision():
    scores = [10.0, 9.0, 8.0, 1.0]
    labels = [True, False, True, False]
    assert top_k_precision(scores, labels, 2) == 0.5
    assert top_k_precision(scores, labels, 4) == 0.5


def test_top_k_precision_guards():
    assert top_k_precision([], [], 5) is None
    assert top_k_precision([1.0], [True], 0) is None


# ------------------------------------------------------------- verdicts


def test_verdict_reports_improvement_when_weighting_helps():
    scores = [
        _score("a", weighted=100.0, heat=1.0, deaths=20),
        _score("b", weighted=90.0, heat=1.0, deaths=10),
        _score("c", weighted=10.0, heat=5.0, deaths=None),
        _score("d", weighted=5.0, heat=5.0, deaths=None),
    ]
    result = validate(scores)
    assert result.metrics["weighted_person_hours"]["auc"] == 1.0
    assert result.metrics["mean_exceedance_h"]["auc"] == 0.0
    assert "weighting helps" in result.verdict


def test_verdict_admits_when_weighting_hurts():
    """The report must say so plainly rather than bury it."""
    scores = [
        _score("a", weighted=1.0, heat=100.0, deaths=20),
        _score("b", weighted=2.0, heat=90.0, deaths=10),
        _score("c", weighted=100.0, heat=1.0, deaths=None),
        _score("d", weighted=90.0, heat=2.0, deaths=None),
    ]
    result = validate(scores)
    assert "HURTS" in result.verdict
    assert "not justified" in result.verdict


def test_verdict_calls_a_tie_a_tie():
    scores = [
        _score("a", weighted=100.0, heat=100.0, deaths=20),
        _score("b", weighted=90.0, heat=90.0, deaths=10),
        _score("c", weighted=10.0, heat=10.0, deaths=None),
        _score("d", weighted=5.0, heat=5.0, deaths=None),
    ]
    assert "no meaningful difference" in validate(scores).verdict


def test_verdict_undetermined_without_both_classes():
    scores = [
        _score("a", weighted=100.0, heat=1.0, deaths=20),
        _score("b", weighted=90.0, heat=2.0, deaths=10),
    ]
    assert "undetermined" in validate(scores).verdict


def test_result_always_carries_limitations():
    scores = [
        _score("a", weighted=100.0, heat=1.0, deaths=20),
        _score("c", weighted=10.0, heat=5.0, deaths=None),
    ]
    payload = validate(scores).to_dict()
    assert len(payload["limitations"]) >= 4
    assert any("place of injury" in line for line in payload["limitations"])


def test_all_four_candidate_rankings_are_scored():
    """Baselines must always be reported alongside the model."""
    scores = [
        _score("a", weighted=100.0, heat=1.0, deaths=20),
        _score("c", weighted=10.0, heat=5.0, deaths=None),
    ]
    metrics = validate(scores).metrics
    assert set(metrics) == {
        "weighted_person_hours",
        "person_hours",
        "mean_exceedance_h",
        "population",
    }
