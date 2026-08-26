"""Temperature unit handling.

Why this module exists
---------------------
The FortyGuard API mixes units in a way that is easy to get wrong:

* ``threshold`` on the ``exceedance`` / ``persistence`` analytics is **Celsius**
  (API-side default 30).
* ``tcm`` tiles carry ``average_temperature`` / ``min_temperature`` /
  ``max_temperature``. The client docstring in the official quickstart describes
  these as Fahrenheit, while the sample payloads shipped in that same repo are
  unambiguously Celsius (a San Jose July day reading 20.9 / 27.6).

So the unit of a tile reading cannot be assumed from documentation alone. Every
entry point here either takes an explicit unit or refuses to proceed. Nothing in
CityVigil silently guesses a unit, because a silent guess produces a plausible
number that is wrong by 30-something degrees — the exact "confident wrong answer"
failure mode the organisers warned about.
"""

from __future__ import annotations

from typing import Iterable, Literal, Sequence

from .errors import UnitError

Unit = Literal["C", "F"]

#: Coldest and hottest 2 m ambient air temperatures physically credible on Earth,
#: in Celsius. Used only to reject impossible payloads, not to infer units.
ABS_MIN_C = -90.0
ABS_MAX_C = 60.0

#: Above this Celsius value a reading cannot be Celsius ambient air, so the
#: series must be Fahrenheit. The highest reliably recorded air temperature is
#: ~56.7 C, hence 60 as a safe wall.
CELSIUS_IMPOSSIBLE_ABOVE = 60.0

#: In a heat-analysis context, a maximum at or above this Celsius value means the
#: series really is Celsius: read as Fahrenheit the same number would be a chilly
#: day (25 F = -3.9 C), which is not what a heat study returns.
CELSIUS_LIKELY_AT_OR_ABOVE = 25.0


def c_to_f(celsius: float) -> float:
    """Convert Celsius to Fahrenheit."""
    return celsius * 9.0 / 5.0 + 32.0


def f_to_c(fahrenheit: float) -> float:
    """Convert Fahrenheit to Celsius."""
    return (fahrenheit - 32.0) * 5.0 / 9.0


def to_celsius(value: float, unit: Unit) -> float:
    """Return ``value`` in Celsius, given its declared ``unit``."""
    if unit == "C":
        return float(value)
    if unit == "F":
        return f_to_c(value)
    raise UnitError(f"unknown unit {unit!r}; expected 'C' or 'F'")


def to_fahrenheit(value: float, unit: Unit) -> float:
    """Return ``value`` in Fahrenheit, given its declared ``unit``."""
    if unit == "F":
        return float(value)
    if unit == "C":
        return c_to_f(value)
    raise UnitError(f"unknown unit {unit!r}; expected 'C' or 'F'")


def api_threshold_celsius(value: float, unit: Unit) -> float:
    """Convert a user-facing threshold into the Celsius value the API expects.

    The ``exceedance`` and ``persistence`` analytics take ``threshold`` in
    Celsius. Call this whenever a threshold originates from a human, a config
    file, or a US-facing UI where Fahrenheit is the natural unit.

    >>> round(api_threshold_celsius(100.0, "F"), 2)
    37.78
    >>> api_threshold_celsius(38.0, "C")
    38.0
    """
    celsius = to_celsius(value, unit)
    if not ABS_MIN_C <= celsius <= ABS_MAX_C:
        raise UnitError(
            f"threshold {value} {unit} is {celsius:.1f} C, outside the credible "
            f"ambient range [{ABS_MIN_C}, {ABS_MAX_C}] C — check the unit"
        )
    return celsius


def infer_tile_unit(values: Iterable[float]) -> Unit:
    """Infer the unit of a series of tile temperature readings.

    Inference is only attempted where it is *safe*, and raises otherwise:

    * a maximum above 60 must be Fahrenheit (Celsius ambient air cannot reach it);
    * a maximum at or above 25 while staying at or below 60 must be Celsius
      (in Fahrenheit those readings would describe cold weather, and a heat
      analysis does not return cold weather);
    * anything else is genuinely ambiguous and raises :class:`UnitError`.

    Always prefer passing the unit explicitly. This helper exists for payloads of
    unknown provenance — such as cached responses captured before the unit was
    pinned down.

    :raises UnitError: if the series is empty, non-finite, or ambiguous.
    """
    series: Sequence[float] = [float(v) for v in values]
    if not series:
        raise UnitError("cannot infer a unit from an empty series")

    hi = max(series)
    lo = min(series)

    if hi > CELSIUS_IMPOSSIBLE_ABOVE:
        # Sanity-check the Fahrenheit reading before committing to it.
        if not ABS_MIN_C <= f_to_c(hi) <= ABS_MAX_C:
            raise UnitError(
                f"maximum reading {hi} is not credible as Fahrenheit "
                f"({f_to_c(hi):.1f} C) nor possible as Celsius"
            )
        return "F"

    if hi >= CELSIUS_LIKELY_AT_OR_ABOVE:
        return "C"

    raise UnitError(
        f"readings span [{lo}, {hi}], which is valid as either Celsius or "
        f"Fahrenheit — pass the unit explicitly instead of relying on inference"
    )


def assert_credible_celsius(values: Iterable[float], *, label: str = "readings") -> None:
    """Raise if any value is outside the credible Celsius ambient-air range.

    Used as a post-conversion tripwire: if a unit mix-up slips through anywhere
    upstream, the resulting series will almost always land outside this band, and
    failing loudly here is far better than shipping the number into an
    allocation decision.
    """
    series = [float(v) for v in values]
    if not series:
        raise UnitError(f"{label}: empty series")
    hi, lo = max(series), min(series)
    if not (ABS_MIN_C <= lo and hi <= ABS_MAX_C):
        raise UnitError(
            f"{label}: span [{lo}, {hi}] C falls outside the credible ambient "
            f"range [{ABS_MIN_C}, {ABS_MAX_C}] C — likely a unit mix-up"
        )
