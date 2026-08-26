"""Intent-named access to the four analysis layers.

The organisers' own session warning was that the API is asynchronous and that
"picking the wrong analysis layer will hand you a confident wrong answer". This
module is the structural answer to that: callers do not choose an
``analytic_type`` string, they state the question they are asking, and each
function records why its layer answers that question.

Layer semantics, verified against live responses
-----------------------------------------------
=================  ====================================  =========================
Layer              Returns                               Answers
=================  ====================================  =========================
``tcm``            per-tile min/mean/max, **Celsius**    "how hot is it there?"
``time_of_measure``UTC hour 0-23 of each tile's peak     "when does it peak?"
``exceedance``     **count of hours** past threshold     "how long is it dangerous?"
``persistence``    longest **continuous** run of hours   "is there any relief?"
=================  ====================================  =========================

The distinction that matters for CityVigil: ``exceedance`` totals scattered hours
while ``persistence`` measures unbroken duration. Two tiles can record an
identical 14 exceedance hours where one cools every night and the other never
does. Heat mortality tracks the second. Ranking on ``exceedance`` alone would
systematically under-protect the neighbourhoods most at risk, which is exactly
the confident wrong answer the warning referred to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from .errors import ValidationError
from .fg_client import FortyGuardClient
from .units import (
    Unit,
    api_threshold_celsius,
    assert_credible_celsius,
    infer_tile_unit,
    to_celsius,
)

Intent = Literal["how_hot", "when_peak", "how_long", "any_relief"]

#: The official quickstart documents ``time_of_measure`` as a **UTC** hour. Our
#: measurements do not support that reading, and getting it wrong would move every
#: operational recommendation by seven hours.
#:
#: Evidence gathered against the live API for central Phoenix on 2024-07-15:
#:
#: * ``time_of_measure`` returned 16-17 across all 10,177 tiles.
#: * ``env_params`` for the same point and day reports ``timezone: GMT-7`` with
#:   local timestamps, and apparent temperature peaking at 15:00 local.
#: * Phoenix air temperature peaks in the late afternoon, around 16:00-17:00 local.
#:
#: Read as UTC, 16-17 would mean a 09:00-10:00 local peak, which is not physically
#: credible in a desert city. Read as local time it matches the observed diurnal
#: curve. CityVigil therefore treats the value as **local hour** and says so, but
#: the ambiguity is unresolved and is reported rather than hidden: no timezone
#: conversion is applied to it anywhere.
TIME_OF_MEASURE_NOTE: str = (
    "Hour-of-day of peak. The quickstart calls this UTC, but measured evidence "
    "points to local time: the API returned 16-17 for Phoenix, while env_params "
    "for the same day reports GMT-7 with apparent temperature peaking at 15:00 "
    "local. A UTC reading would imply a 09:00 local peak, which is not credible "
    "in Phoenix in July. Treated as local hour; no conversion applied."
)

#: Which layer answers which question, and the justification recorded for it.
LAYER_GUIDE: dict[Intent, tuple[str, str]] = {
    "how_hot": (
        "tcm",
        "Snapshot intensity was asked for, so tcm is correct: it returns per-tile "
        "min/mean/max temperature. Neither exceedance nor persistence can answer "
        "'how hot' — both return hour counts, not degrees.",
    ),
    "when_peak": (
        "time_of_measure",
        "The question is about timing, not magnitude. time_of_measure gives the "
        "hour-of-day each tile peaks, which is what schedules cooling-centre "
        "opening hours and building pre-cooling windows. Treat the hour as local "
        "time: see TIME_OF_MEASURE_NOTE for the evidence and the caveat.",
    ),
    "how_long": (
        "exceedance",
        "Cumulative dangerous duration was asked for. exceedance counts hours past "
        "the threshold, so multiplying by exposed population yields person-hours "
        "directly, in the API's own units rather than an invented index.",
    ),
    "any_relief": (
        "persistence",
        "The question is whether heat ever breaks. persistence returns the longest "
        "continuous run past the threshold, capturing overnight non-relief — the "
        "driver of heat mortality that a total hour count hides.",
    ),
}


# ------------------------------------------------------------------- results


@dataclass(frozen=True)
class Tile:
    """One grid cell of a heat surface."""

    tile_id: int
    geometry: dict
    #: ``tcm``: mean temperature in Celsius. Analysis layers: the ``value`` field.
    value: float
    minimum: float | None = None
    maximum: float | None = None

    @property
    def centroid(self) -> tuple[float, float]:
        """Approximate ``(lon, lat)`` centre of the cell."""
        ring = self.geometry.get("coordinates", [[]])[0]
        points = [p for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
        if not points:
            raise ValidationError("tile geometry has no usable coordinates")
        return (
            sum(float(p[0]) for p in points) / len(points),
            sum(float(p[1]) for p in points) / len(points),
        )


@dataclass(frozen=True)
class HeatSurface:
    """A parsed heatmap response, with its provenance attached."""

    analytic_type: str
    units: str
    tiles: list[Tile]
    stats: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    threshold_c: float | None = None
    window: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.tiles)

    @property
    def values(self) -> list[float]:
        """Every tile's primary value, in tile order."""
        return [t.value for t in self.tiles]

    def hottest(self, n: int = 10) -> list[Tile]:
        """The ``n`` tiles with the highest value."""
        return sorted(self.tiles, key=lambda t: t.value, reverse=True)[:n]

    def summary(self) -> dict[str, Any]:
        """Compact description suitable for the audit trail or a briefing."""
        vals = self.values
        return {
            "analytic_type": self.analytic_type,
            "units": self.units,
            "n_tiles": len(vals),
            "min": min(vals) if vals else None,
            "mean": (sum(vals) / len(vals)) if vals else None,
            "max": max(vals) if vals else None,
            "threshold_c": self.threshold_c,
            "window": self.window,
        }

    def to_geojson(self, *, precision: int = 6) -> dict:
        """Export as a GeoJSON ``FeatureCollection`` for GIS handoff or the map.

        Coordinates are rounded to ``precision`` decimal places. At 6 dp that is
        roughly 0.1 m, three orders of magnitude finer than the 60-100 m tiles,
        and it cuts the payload for a 10k-tile city surface by about 40% — which
        the browser notices and the analysis does not.
        """

        def _round(node):
            if isinstance(node, (int, float)):
                return round(float(node), precision)
            if isinstance(node, (list, tuple)):
                return [_round(child) for child in node]
            return node

        features = []
        for t in self.tiles:
            props: dict[str, Any] = {
                "tile_id": t.tile_id,
                "value": round(t.value, 4),
                "units": self.units,
            }
            # Only tcm carries a min/max envelope; omit the keys elsewhere rather
            # than shipping nulls for every tile.
            if t.minimum is not None:
                props["min"] = round(t.minimum, 4)
            if t.maximum is not None:
                props["max"] = round(t.maximum, 4)
            features.append(
                {
                    "type": "Feature",
                    "id": str(t.tile_id),
                    "properties": props,
                    "geometry": {
                        "type": t.geometry.get("type", "Polygon"),
                        "coordinates": _round(t.geometry.get("coordinates", [])),
                    },
                }
            )

        return {
            "type": "FeatureCollection",
            "properties": {
                "analytic_type": self.analytic_type,
                "units": self.units,
                "threshold_c": self.threshold_c,
                "rationale": self.rationale,
            },
            "features": features,
        }


# ------------------------------------------------------------------- parsing


def parse_surface(
    result: dict,
    analytic_type: str,
    *,
    rationale: str = "",
    threshold_c: float | None = None,
    window: dict[str, Any] | None = None,
    tile_unit: Unit | None = None,
) -> HeatSurface:
    """Turn a raw ``/v1/heatmap`` result into a :class:`HeatSurface`.

    ``tcm`` and the analysis layers return different tile schemas, so they are
    handled separately rather than with a permissive getter that would quietly
    produce zeros for the wrong layer.

    For ``tcm``, the tile unit is inferred and readings are converted to Celsius,
    then checked for credibility. Pass ``tile_unit`` explicitly to skip inference.
    """
    features = (result.get("map_data") or {}).get("features") or []
    if not features:
        raise ValidationError(
            f"{analytic_type} response contained no tiles — the AOI may fall "
            f"outside US coverage, or the window may hold no data"
        )

    stats = result.get("stats_data") or {}
    tiles: list[Tile] = []

    if analytic_type == "tcm":
        means = [float(f["properties"]["average_temperature"]) for f in features]
        unit: Unit = tile_unit or infer_tile_unit(means)

        for f in features:
            props = f["properties"]
            tiles.append(
                Tile(
                    tile_id=int(props.get("tile_id", len(tiles))),
                    geometry=f["geometry"],
                    value=to_celsius(float(props["average_temperature"]), unit),
                    minimum=to_celsius(float(props["min_temperature"]), unit),
                    maximum=to_celsius(float(props["max_temperature"]), unit),
                )
            )
        assert_credible_celsius([t.value for t in tiles], label="tcm tile means")
        units = "celsius"
    else:
        for f in features:
            props = f["properties"]
            if "value" not in props:
                raise ValidationError(
                    f"{analytic_type} tile is missing 'value'; got keys "
                    f"{sorted(props)} — this looks like a tcm payload"
                )
            tiles.append(
                Tile(
                    tile_id=int(props.get("tile_id", len(tiles))),
                    geometry=f["geometry"],
                    value=float(props["value"]),
                )
            )
        units = str(stats.get("units") or ("hour" if analytic_type != "time_of_measure" else "utc_hour"))

    return HeatSurface(
        analytic_type=analytic_type,
        units=units,
        tiles=tiles,
        stats=stats,
        rationale=rationale,
        threshold_c=threshold_c,
        window=window or {},
    )


# ------------------------------------------------------------- intent access


class ExposureLayers:
    """Question-shaped access to the heatmap analytics.

    Each method states the question in its name, records the layer choice and its
    rationale to the audit trail, and returns a parsed :class:`HeatSurface`.
    """

    def __init__(self, client: FortyGuardClient) -> None:
        self.client = client

    def _fetch(
        self,
        intent: Intent,
        polygon_aoi: dict,
        question: str,
        *,
        threshold: float | None = None,
        threshold_unit: Unit = "C",
        direction: str | None = None,
        **window: Any,
    ) -> HeatSurface:
        analytic_type, rationale = LAYER_GUIDE[intent]
        self.client.audit.layer_choice(
            analytic_type,
            question=question,
            rationale=rationale,
            threshold=threshold,
            threshold_unit=threshold_unit,
            direction=direction,
            **window,
        )
        result = self.client.create_heatmap(
            polygon_aoi,
            analytic_type=analytic_type,  # type: ignore[arg-type]
            threshold=threshold,
            threshold_unit=threshold_unit,
            direction=direction,
            **window,
        )
        threshold_c = (
            None if threshold is None else api_threshold_celsius(threshold, threshold_unit)
        )
        return parse_surface(
            result,
            analytic_type,
            rationale=rationale,
            threshold_c=threshold_c,
            window={k: v for k, v in window.items() if k != "polygon_aoi"},
        )

    # -- how hot is it? -----------------------------------------------------

    def how_hot(
        self,
        polygon_aoi: dict,
        *,
        start_date: str,
        filter_type: int = 3,
        granularity: int = 100,
        start_time: str | None = None,
        end_time: str | None = None,
        end_date: str | None = None,
        question: str = "How hot is each part of the AOI?",
    ) -> HeatSurface:
        """Snapshot temperatures in Celsius (``tcm``)."""
        return self._fetch(
            "how_hot",
            polygon_aoi,
            question,
            start_date=start_date,
            filter_type=filter_type,
            granularity=granularity,
            start_time=start_time,
            end_time=end_time,
            end_date=end_date,
        )

    # -- when does it peak? -------------------------------------------------

    def when_peak(
        self,
        polygon_aoi: dict,
        *,
        start_date: str,
        filter_type: int = 3,
        granularity: int = 100,
        start_time: str | None = None,
        end_time: str | None = None,
        end_date: str | None = None,
        question: str = "At what hour does each part of the AOI peak?",
    ) -> HeatSurface:
        """UTC hour-of-day of each tile's peak (``time_of_measure``)."""
        return self._fetch(
            "when_peak",
            polygon_aoi,
            question,
            start_date=start_date,
            filter_type=filter_type,
            granularity=granularity,
            start_time=start_time,
            end_time=end_time,
            end_date=end_date,
        )

    # -- how long is it dangerous? -----------------------------------------

    def how_long_dangerous(
        self,
        polygon_aoi: dict,
        *,
        threshold: float,
        threshold_unit: Unit = "C",
        start_date: str,
        end_date: str,
        filter_type: int = 4,
        granularity: int = 100,
        direction: str = "above",
        question: str = "How many hours past the danger threshold does each tile spend?",
    ) -> HeatSurface:
        """Total hours past the threshold (``exceedance``).

        Multiply by exposed population to get person-hours of exposure.
        """
        return self._fetch(
            "how_long",
            polygon_aoi,
            question,
            threshold=threshold,
            threshold_unit=threshold_unit,
            direction=direction,
            start_date=start_date,
            end_date=end_date,
            filter_type=filter_type,
            granularity=granularity,
        )

    # -- is there any relief? ----------------------------------------------

    def any_relief(
        self,
        polygon_aoi: dict,
        *,
        threshold: float,
        threshold_unit: Unit = "C",
        start_date: str,
        end_date: str,
        filter_type: int = 4,
        granularity: int = 100,
        direction: str = "above",
        question: str = "What is the longest unbroken dangerous stretch per tile?",
    ) -> HeatSurface:
        """Longest continuous run past the threshold (``persistence``)."""
        return self._fetch(
            "any_relief",
            polygon_aoi,
            question,
            threshold=threshold,
            threshold_unit=threshold_unit,
            direction=direction,
            start_date=start_date,
            end_date=end_date,
            filter_type=filter_type,
            granularity=granularity,
        )


def explain_layer_choice(intent: Intent) -> str:
    """Return the recorded justification for the layer that answers ``intent``."""
    if intent not in LAYER_GUIDE:
        raise ValidationError(
            f"unknown intent {intent!r}; expected one of {sorted(LAYER_GUIDE)}"
        )
    analytic_type, rationale = LAYER_GUIDE[intent]
    return f"{intent} -> {analytic_type}: {rationale}"
