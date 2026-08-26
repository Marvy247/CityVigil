"""Unit handling — the mixed C/F trap."""

from __future__ import annotations

import pytest

from cityvigil.errors import UnitError
from cityvigil.units import (
    api_threshold_celsius,
    assert_credible_celsius,
    c_to_f,
    f_to_c,
    infer_tile_unit,
    to_celsius,
    to_fahrenheit,
)


def test_conversion_roundtrip():
    for c in (-40.0, 0.0, 21.5, 36.06, 50.0):
        assert f_to_c(c_to_f(c)) == pytest.approx(c)


def test_known_anchors():
    assert c_to_f(0.0) == pytest.approx(32.0)
    assert c_to_f(100.0) == pytest.approx(212.0)
    assert f_to_c(-40.0) == pytest.approx(-40.0)


def test_threshold_from_fahrenheit_is_converted():
    """A US-facing 100 F threshold must reach the API as 37.78 C, not 100."""
    assert api_threshold_celsius(100.0, "F") == pytest.approx(37.7778, abs=1e-3)


def test_threshold_from_celsius_passes_through():
    assert api_threshold_celsius(35.0, "C") == pytest.approx(35.0)


def test_threshold_rejects_implausible_value():
    """95 C is the classic bug: a Fahrenheit number sent as Celsius."""
    with pytest.raises(UnitError, match="outside the credible"):
        api_threshold_celsius(95.0, "C")


def test_infer_celsius_from_real_phoenix_readings():
    """Live Phoenix values on 2024-07-15 were 35.9-36.2 — Celsius."""
    assert infer_tile_unit([35.9436, 36.1772, 35.8874]) == "C"


def test_infer_fahrenheit_when_celsius_is_impossible():
    """97 F is a real Phoenix reading; as Celsius it would be impossible."""
    assert infer_tile_unit([96.7, 97.1, 96.2]) == "F"


def test_infer_refuses_ambiguous_series():
    """A 10-20 span is a valid cool day in either unit, so refuse to guess."""
    with pytest.raises(UnitError, match="pass the unit explicitly"):
        infer_tile_unit([10.0, 15.0, 20.0])


def test_infer_rejects_empty_series():
    with pytest.raises(UnitError, match="empty series"):
        infer_tile_unit([])


def test_to_celsius_and_fahrenheit_respect_declared_unit():
    assert to_celsius(100.0, "F") == pytest.approx(37.7778, abs=1e-3)
    assert to_celsius(37.0, "C") == pytest.approx(37.0)
    assert to_fahrenheit(37.0, "C") == pytest.approx(98.6)
    assert to_fahrenheit(98.6, "F") == pytest.approx(98.6)


def test_unknown_unit_raises():
    with pytest.raises(UnitError, match="unknown unit"):
        to_celsius(20.0, "K")  # type: ignore[arg-type]


def test_credibility_tripwire_catches_unit_mixup():
    """Fahrenheit values that slipped through unconverted must fail loudly."""
    with pytest.raises(UnitError, match="unit mix-up"):
        assert_credible_celsius([97.0, 99.0, 104.0], label="tcm tile means")


def test_credibility_accepts_real_celsius():
    assert_credible_celsius([35.9, 36.2, 40.5]) is None
