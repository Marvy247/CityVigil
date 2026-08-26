"""Pre-flight request guards.

Every guard here runs *before* an HTTP call. Two reasons:

1. **Credits.** They are only charged on success, but a successful call that
   answered the wrong question is worse than a rejected one — it produces a
   confident wrong answer that flows into an allocation decision.
2. **Agent recovery.** A :class:`ValidationError` carries the offending field, so
   the agent loop can repair the request instead of retrying it blindly.

All limits encoded here were verified against the official quickstart client and
the hackathon FAQ, not assumed. See ``PLAN.md`` for the source of each.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Literal, Sequence

from .errors import ValidationError

# --------------------------------------------------------------------- limits

#: Valid ``analytic_type`` values on ``POST /v1/heatmap``.
ANALYTIC_TYPES: tuple[str, ...] = ("tcm", "time_of_measure", "exceedance", "persistence")

#: Analytics that additionally require ``threshold`` (Celsius) and ``direction``.
THRESHOLD_ANALYTICS: frozenset[str] = frozenset({"exceedance", "persistence"})

#: Spatial resolutions the API accepts, in metres.
GRANULARITIES: tuple[int, ...] = (60, 80, 100)

#: ``filter_type`` semantics. Value -> (label, required companion fields).
FILTER_TYPES: dict[int, tuple[str, tuple[str, ...]]] = {
    1: ("single hour", ("start_time",)),
    2: ("range of hours", ("start_time", "end_time")),
    3: ("single day", ()),
    4: ("range of days", ("end_date",)),
}

#: Earliest date in the archive (hackathon FAQ).
DATA_START = date(2021, 1, 1)

#: Forecast horizon for heatmaps (hackathon FAQ). Anything beyond is rejected
#: server-side, so we reject it here first with a clearer message.
FORECAST_HORIZON = timedelta(hours=12)

#: Maximum span for a ``filter_type=4`` range-of-days request, measured live.
#: 31 days succeeds; 32 days fails as a task error; 46 and 53 days are rejected at
#: submit with a 500. The API publishes no limit, so this was found by probing —
#: cheaply, because failed tasks cost no credits. Analyses covering a longer period
#: must be split into month-sized windows and combined client-side.
MAX_RANGE_DAYS = 31

#: Coverage is the United States only. Rough inclusive bounding boxes, as
#: (min_lon, min_lat, max_lon, max_lat). Generous on purpose: the aim is to catch
#: "you pointed this at Dubai", not to police coastlines.
US_BBOXES: dict[str, tuple[float, float, float, float]] = {
    "conus": (-125.1, 24.4, -66.8, 49.5),
    "alaska": (-172.5, 51.0, -129.9, 71.6),
    "hawaii": (-160.6, 18.8, -154.7, 22.3),
    "puerto_rico": (-67.4, 17.8, -65.2, 18.6),
}

#: Heatmap area caps by plan, in square kilometres (from the published pricing
#: page: Basic up to 10 mi², Pro up to 50 mi²).
PLAN_AREA_CAP_KM2: dict[str, float] = {
    "basic": 25.9,
    "pro": 129.5,
    "hackathon": 129.5,
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

Direction = Literal["above", "below"]


# ---------------------------------------------------------------- primitives


def parse_date(value: str, *, field: str = "start_date") -> date:
    """Validate a ``YYYY-MM-DD`` string and return it as a :class:`date`."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValidationError(
            f"{field} must be a 'YYYY-MM-DD' string, got {value!r}", field=field
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{field}={value!r} is not a real date", field=field) from exc


def validate_time(value: str, *, field: str = "start_time") -> str:
    """Validate an ``HH:MM`` 24-hour clock string (the format the API expects)."""
    if not isinstance(value, str) or not _TIME_RE.match(value):
        raise ValidationError(
            f"{field} must be an 'HH:MM' 24-hour string, got {value!r}", field=field
        )
    return value


def validate_granularity(value: int) -> int:
    """Validate spatial resolution in metres."""
    if value not in GRANULARITIES:
        raise ValidationError(
            f"granularity must be one of {GRANULARITIES} metres, got {value!r}. "
            f"Note the marketing figure of ~20 m is not a selectable value.",
            field="granularity",
        )
    return value


def validate_analytic(
    analytic_type: str,
    threshold: float | None = None,
    direction: str | None = None,
) -> None:
    """Validate the analytic selection and its threshold companions.

    ``threshold`` must already be in **Celsius** — use
    :func:`cityvigil.units.api_threshold_celsius` to convert first.
    """
    if analytic_type not in ANALYTIC_TYPES:
        raise ValidationError(
            f"analytic_type must be one of {ANALYTIC_TYPES}, got {analytic_type!r}",
            field="analytic_type",
        )

    needs = analytic_type in THRESHOLD_ANALYTICS
    if needs:
        if threshold is None:
            raise ValidationError(
                f"analytic_type={analytic_type!r} requires threshold in CELSIUS",
                field="threshold",
            )
        if direction not in ("above", "below"):
            raise ValidationError(
                f"analytic_type={analytic_type!r} requires direction 'above' or "
                f"'below', got {direction!r}",
                field="direction",
            )
    else:
        if threshold is not None or direction is not None:
            raise ValidationError(
                f"analytic_type={analytic_type!r} ignores threshold/direction; "
                f"passing them means the request does not do what you think",
                field="analytic_type",
            )


def validate_date_time(
    start_date: str,
    filter_type: int,
    start_time: str | None = None,
    end_time: str | None = None,
    end_date: str | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate a full ``date_time`` block and return it ready for the payload.

    Enforces the archive floor (2021-01-01), the 12-hour forecast ceiling, the
    companion fields each ``filter_type`` requires, and forward ordering.
    """
    if filter_type not in FILTER_TYPES:
        raise ValidationError(
            f"filter_type must be one of "
            f"{ {k: v[0] for k, v in FILTER_TYPES.items()} }, got {filter_type!r}",
            field="filter_type",
        )
    label, required = FILTER_TYPES[filter_type]
    supplied = {"start_time": start_time, "end_time": end_time, "end_date": end_date}

    for field in required:
        if supplied[field] is None:
            raise ValidationError(
                f"filter_type={filter_type} ({label}) requires {field}", field=field
            )
    for field, value in supplied.items():
        if value is not None and field not in required:
            raise ValidationError(
                f"filter_type={filter_type} ({label}) does not use {field}; "
                f"supplying it will silently change which window is analysed",
                field=field,
            )

    start = parse_date(start_date, field="start_date")
    block: dict[str, Any] = {"start_date": start_date, "filter_type": filter_type}

    if start_time is not None:
        block["start_time"] = validate_time(start_time, field="start_time")
    if end_time is not None:
        block["end_time"] = validate_time(end_time, field="end_time")
        if start_time is not None and end_time <= start_time:
            raise ValidationError(
                f"end_time {end_time} must be after start_time {start_time}",
                field="end_time",
            )

    end = start
    if end_date is not None:
        end = parse_date(end_date, field="end_date")
        if end < start:
            raise ValidationError(
                f"end_date {end_date} is before start_date {start_date}", field="end_date"
            )
        span_days = (end - start).days + 1
        if span_days > MAX_RANGE_DAYS:
            raise ValidationError(
                f"range of {span_days} days exceeds the API's {MAX_RANGE_DAYS}-day "
                f"limit for filter_type=4 (measured: 31 days succeeds, 32 fails). "
                f"Split the period into month-sized windows and combine them "
                f"client-side.",
                field="end_date",
            )
        block["end_date"] = end_date

    _check_window_bounds(start, end, start_time, end_time, now=now)
    return block


def _check_window_bounds(
    start: date,
    end: date,
    start_time: str | None,
    end_time: str | None,
    *,
    now: datetime | None,
) -> None:
    """Enforce the archive floor and the 12-hour forecast ceiling."""
    if start < DATA_START:
        raise ValidationError(
            f"start_date {start.isoformat()} precedes the archive start "
            f"{DATA_START.isoformat()}; earlier dates are rejected by the API",
            field="start_date",
        )

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    ceiling = now + FORECAST_HORIZON

    latest_time = end_time or start_time or "23:59"
    hh, mm = (int(p) for p in latest_time.split(":"))
    requested_end = datetime(end.year, end.month, end.day, hh, mm, tzinfo=timezone.utc)

    if requested_end > ceiling:
        raise ValidationError(
            f"window ends {requested_end.isoformat()} which is beyond the "
            f"{int(FORECAST_HORIZON.total_seconds() // 3600)}-hour forecast horizon "
            f"(ceiling {ceiling.isoformat()}). Longer horizons must come from "
            f"CityVigil's own forecast model, not from the FortyGuard API.",
            field="end_date" if end_time or end != start else "start_date",
        )


# ----------------------------------------------------------------------- AOI


def polygon_bbox(polygon_aoi: dict) -> tuple[float, float, float, float]:
    """Return ``(min_lon, min_lat, max_lon, max_lat)`` for a GeoJSON AOI.

    Accepts a ``FeatureCollection``, a ``Feature``, or a bare geometry, matching
    the shapes the API tolerates.
    """
    coords = list(_iter_positions(polygon_aoi))
    if not coords:
        raise ValidationError("AOI contains no coordinates", field="polygon_aoi")
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return (min(lons), min(lats), max(lons), max(lats))


def _iter_positions(node: Any) -> Iterable[Sequence[float]]:
    """Yield every ``[lon, lat]`` position found anywhere in a GeoJSON object."""
    if isinstance(node, dict):
        if "features" in node:
            for feature in node["features"]:
                yield from _iter_positions(feature)
        elif "geometry" in node:
            yield from _iter_positions(node["geometry"])
        elif "coordinates" in node:
            yield from _iter_positions(node["coordinates"])
        return
    if isinstance(node, (list, tuple)):
        if (
            len(node) >= 2
            and all(isinstance(v, (int, float)) for v in node[:2])
        ):
            yield (float(node[0]), float(node[1]))
            return
        for child in node:
            yield from _iter_positions(child)


def bbox_area_km2(bbox: tuple[float, float, float, float]) -> float:
    """Approximate bounding-box area in km² using a local equirectangular scale.

    Good to a few percent at city scale, which is all that an area cap needs.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    mid_lat = math.radians((min_lat + max_lat) / 2.0)
    km_per_deg_lat = 110.574
    km_per_deg_lon = 111.320 * math.cos(mid_lat)
    return abs(max_lat - min_lat) * km_per_deg_lat * abs(max_lon - min_lon) * km_per_deg_lon


def _round_coords(node: Any, precision: int) -> Any:
    """Recursively round every coordinate to ``precision`` decimal places."""
    if isinstance(node, (int, float)):
        return round(float(node), precision)
    if isinstance(node, (list, tuple)):
        return [_round_coords(child, precision) for child in node]
    return node


def _iter_geometries(node: Any) -> Iterable[dict]:
    """Yield every polygonal geometry found in a GeoJSON object."""
    if isinstance(node, dict):
        if "features" in node:
            for feature in node["features"]:
                yield from _iter_geometries(feature)
            return
        if "geometry" in node:
            yield from _iter_geometries(node["geometry"])
            return
        if node.get("type") in ("Polygon", "MultiPolygon") and "coordinates" in node:
            yield node
        return
    if isinstance(node, (list, tuple)):
        for child in node:
            yield from _iter_geometries(child)


def tile_bbox(
    bbox: BBox,
    *,
    plan: str = "hackathon",
    area_cap_km2: float | None = None,
    margin: float = 0.9,
) -> list[dict]:
    """Split a bounding box into AOI polygons that each fit under the area cap.

    Heatmap generation costs a flat 4,220 credits per call regardless of area, so
    the cheapest way to cover a region is the fewest, largest AOIs the plan allows.
    This picks a grid whose cells sit just under the cap (``margin`` leaves
    headroom for the approximation in :func:`bbox_area_km2`).

    Returns GeoJSON FeatureCollections ready to pass to ``create_heatmap``.
    """
    cap = (area_cap_km2 if area_cap_km2 is not None else PLAN_AREA_CAP_KM2.get(plan.lower(), 129.5)) * margin
    min_lon, min_lat, max_lon, max_lat = bbox
    total = bbox_area_km2(bbox)

    if total <= cap:
        cells = 1
    else:
        cells = math.ceil(total / cap)
    # Choose a near-square grid so cells stay compact.
    cols = max(1, math.ceil(math.sqrt(cells * (max_lon - min_lon) / max(max_lat - min_lat, 1e-9))))
    rows = max(1, math.ceil(cells / cols))

    # Grow the grid until every cell is under the cap.
    while bbox_area_km2((min_lon, min_lat, min_lon + (max_lon - min_lon) / cols, min_lat + (max_lat - min_lat) / rows)) > cap:
        if (max_lon - min_lon) / cols >= (max_lat - min_lat) / rows:
            cols += 1
        else:
            rows += 1

    dlon = (max_lon - min_lon) / cols
    dlat = (max_lat - min_lat) / rows

    tiles: list[dict] = []
    for i in range(cols):
        for j in range(rows):
            w = min_lon + i * dlon
            s = min_lat + j * dlat
            e = w + dlon
            n = s + dlat
            tiles.append(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {},
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [
                                    [[w, s], [e, s], [e, n], [w, n], [w, s]]
                                ],
                            },
                        }
                    ],
                }
            )
    return tiles


def canonical_aoi(polygon_aoi: dict, *, precision: int = 7) -> dict:
    """Return a minimal, deterministic form of an AOI.

    Cosmetic differences — a ``name`` property, a ``Feature`` wrapper, float noise
    in the 12th decimal place — must not change what the cache considers the same
    question. Without this, two identical footprints that differ only by a label
    each cost a full heatmap call. That was measured, not hypothesised: it wasted
    4,220 credits before this function existed.

    Properties are dropped and coordinates rounded to ``precision`` decimals
    (7 dp is roughly 1 cm, far below the 60-100 m tile size).
    """
    geometries = list(_iter_geometries(polygon_aoi))
    if not geometries:
        raise ValidationError(
            "AOI contains no Polygon or MultiPolygon geometry", field="polygon_aoi"
        )
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": geometry["type"],
                    "coordinates": _round_coords(geometry["coordinates"], precision),
                },
            }
            for geometry in geometries
        ],
    }


def validate_aoi(
    polygon_aoi: dict,
    *,
    plan: str = "hackathon",
    area_cap_km2: float | None = None,
) -> dict[str, Any]:
    """Validate an AOI is well-formed, inside US coverage, and within the area cap.

    Returns a small report (``bbox``, ``area_km2``, ``region``) that callers log
    to the audit trail, so every heatmap records the footprint it was run over.
    """
    if not isinstance(polygon_aoi, dict):
        raise ValidationError(
            f"polygon_aoi must be a GeoJSON dict, got {type(polygon_aoi).__name__}",
            field="polygon_aoi",
        )

    bbox = polygon_bbox(polygon_aoi)
    min_lon, min_lat, max_lon, max_lat = bbox

    if not (-180.0 <= min_lon and max_lon <= 180.0 and -90.0 <= min_lat and max_lat <= 90.0):
        raise ValidationError(
            f"AOI bbox {bbox} is not valid lon/lat — coordinates may be swapped "
            f"(GeoJSON order is [longitude, latitude])",
            field="polygon_aoi",
        )

    region = next(
        (
            name
            for name, (w, s, e, n) in US_BBOXES.items()
            if w <= min_lon and max_lon <= e and s <= min_lat and max_lat <= n
        ),
        None,
    )
    if region is None:
        raise ValidationError(
            f"AOI bbox {bbox} is not fully inside US coverage. FortyGuard returns "
            f"data for the United States only; non-US areas yield empty results.",
            field="polygon_aoi",
        )

    area = bbox_area_km2(bbox)
    cap = area_cap_km2 if area_cap_km2 is not None else PLAN_AREA_CAP_KM2.get(plan.lower(), 129.5)
    if area > cap:
        raise ValidationError(
            f"AOI bbox area {area:.1f} km² exceeds the {plan} heatmap cap of "
            f"{cap:.1f} km². Tile the AOI instead of widening it.",
            field="polygon_aoi",
        )

    return {"bbox": bbox, "area_km2": round(area, 3), "region": region}
