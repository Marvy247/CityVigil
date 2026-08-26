"""Cooling-centre supply, and the gap between need and provision.

What this adds
--------------
Until now CityVigil produced a *demand* map: where dangerous heat lands on
vulnerable people. That says nothing about whether help is already there. This
module joins the real Maricopa Heat Relief Network — site locations, types and
per-weekday opening hours — so the output becomes an *unmet need* map.

The vintage problem, stated plainly
----------------------------------
The Heat Relief Network feature service publishes only the **current season**
(2026). It holds no historical snapshots. Our study episode is July 2024. So this
module cannot and does not claim to describe what was open in 2024.

What it can honestly answer is the counterfactual: *given the network Maricopa
County operates today, where would coverage gaps fall during a heat event like the
one that actually happened in July 2024?* Every result carries that framing.

The hours finding
----------------
Coverage is not a fixed property of a map pin. A cooling centre that closes at
17:00 provides nothing during the 16:00-19:00 stretch when Phoenix air temperature
peaks and stays peaked. Because the network publishes real opening and closing
times per weekday, coverage can be evaluated *at a given hour* — which is the
difference between counting pins and describing protection.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Literal

from .errors import CityVigilError
from .geometry import haversine_km
from .sources import DEFAULT_DATA_DIR, HEAT_RELIEF_NETWORK, fetch
from .tracts import Tract, TractCollection

#: Site categories that provide indoor cooled space a person can sit in.
#: Hydration stations hand out water and are genuinely useful, but they are not
#: refuge from heat, so they are counted separately and never as cooling capacity.
COOLING_TYPES: frozenset[str] = frozenset({"Cooling Center", "Respite Center"})

#: Straight-line radius treated as "walkable" for someone without a vehicle.
#: 800 m is a common planning standard for a 10-minute walk. Street-network
#: distance is longer, so coverage computed with this is optimistic.
WALKABLE_KM = 0.8

Weekday = Literal["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAYS: tuple[Weekday, ...] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)

_TIME_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?[Mm]\.?\s*$")


class SupplyDataError(CityVigilError):
    """Cooling-centre data could not be assembled."""


def parse_clock(value: object) -> float | None:
    """Parse ``'1:00 PM'`` into hours after midnight (``13.0``).

    The network's hours are hand-entered free text, so this is deliberately
    tolerant and returns ``None`` rather than guessing on anything unrecognised.
    A site whose hours cannot be parsed is treated as unknown, not as open.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "closed", "n/a", "na", "-"}:
        return None

    match = _TIME_RE.match(text)
    if match:
        hour = int(match.group(1)) % 12
        minute = int(match.group(2) or 0)
        if match.group(3).lower() == "p":
            hour += 12
        return hour + minute / 60.0

    # Bare 24-hour forms like "17:00" or "17".
    bare = re.match(r"^\s*(\d{1,2})(?::(\d{2}))?\s*$", text)
    if bare:
        hour = int(bare.group(1))
        minute = int(bare.group(2) or 0)
        if 0 <= hour <= 24 and 0 <= minute < 60:
            return hour + minute / 60.0
    return None


@dataclass(frozen=True)
class CoolingSite:
    """One Heat Relief Network site."""

    site_id: str
    name: str
    organization: str
    city: str
    address: str
    site_type: str
    lon: float
    lat: float
    #: ``{weekday: (open_hour, close_hour)}`` for days with parseable hours.
    hours: dict[str, tuple[float, float]]
    ada_accessible: bool | None
    allows_pets: bool | None
    season_start: str | None
    season_end: str | None

    @property
    def point(self) -> tuple[float, float]:
        return (self.lon, self.lat)

    @property
    def is_cooling(self) -> bool:
        """True for indoor cooled refuge, false for hydration-only sites."""
        return self.site_type in COOLING_TYPES

    def open_at(self, weekday: Weekday, hour: float) -> bool:
        """Whether the site is open at a given weekday and hour.

        Unknown hours count as closed. Overstating availability in a heat-safety
        tool is the more dangerous error.
        """
        window = self.hours.get(weekday)
        if window is None:
            return False
        start, end = window
        return start <= hour < end

    def closing_hour(self, weekday: Weekday) -> float | None:
        window = self.hours.get(weekday)
        return window[1] if window else None

    def to_dict(self) -> dict:
        return {
            "site_id": self.site_id,
            "name": self.name,
            "organization": self.organization,
            "city": self.city,
            "address": self.address,
            "site_type": self.site_type,
            "lon": self.lon,
            "lat": self.lat,
            "is_cooling": self.is_cooling,
            "ada_accessible": self.ada_accessible,
            "allows_pets": self.allows_pets,
            "hours": {d: list(w) for d, w in sorted(self.hours.items())},
        }


def _yes_no(value: object) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"yes", "y", "true"}:
        return True
    if text in {"no", "n", "false"}:
        return False
    return None


def load_sites(
    *, data_dir: Path = DEFAULT_DATA_DIR, download: bool = True
) -> list[CoolingSite]:
    """Load Heat Relief Network sites from the cached GeoJSON."""
    path = HEAT_RELIEF_NETWORK.path(data_dir)
    if not path.is_file():
        if not download:
            raise SupplyDataError(
                f"{HEAT_RELIEF_NETWORK.key} is not present at {path} and "
                f"download=False. Run: python3 scripts/fetch_data.py"
            )
        path = fetch(HEAT_RELIEF_NETWORK, data_dir=data_dir)

    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features") or []
    if not features:
        raise SupplyDataError(f"{path} contains no Heat Relief Network sites")

    sites: list[CoolingSite] = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates")
        if geometry.get("type") != "Point" or not coords or len(coords) < 2:
            continue  # a site with no location cannot be used for coverage

        props = feature.get("properties") or {}
        hours: dict[str, tuple[float, float]] = {}
        for day in WEEKDAYS:
            start = parse_clock(props.get(f"{day}Open"))
            end = parse_clock(props.get(f"{day}Close"))
            if start is not None and end is not None and end > start:
                hours[day] = (start, end)

        sites.append(
            CoolingSite(
                site_id=str(props.get("OBJECTID") or props.get("globalid") or len(sites)),
                name=str(props.get("Location") or props.get("Organization") or "unnamed"),
                organization=str(props.get("Organization") or ""),
                city=str(props.get("City") or ""),
                address=str(props.get("Address") or ""),
                site_type=str(props.get("HeatRelief_Type") or "Unspecified"),
                lon=float(coords[0]),
                lat=float(coords[1]),
                hours=hours,
                ada_accessible=_yes_no(props.get("ADA_accessible")),
                allows_pets=_yes_no(props.get("Pets")),
                season_start=props.get("Start_Date"),
                season_end=props.get("End_Date"),
            )
        )

    if not sites:
        raise SupplyDataError(f"{path} yielded no sites with usable point geometry")
    return sites


# ------------------------------------------------------------------- coverage


@dataclass(frozen=True)
class TractCoverage:
    """Cooling-centre access for one tract, evaluated at a specific hour."""

    geoid: str
    #: Straight-line km from the tract centroid to the nearest open cooling site.
    nearest_open_km: float | None
    nearest_open_name: str | None
    #: Cooling sites within the walkable radius and open at the evaluated hour.
    open_within_walk: int
    #: Cooling sites within the walkable radius regardless of hours.
    sites_within_walk: int
    hydration_within_walk: int

    @property
    def walkable_cover(self) -> bool:
        """True when at least one open cooling site is within walking distance."""
        return self.open_within_walk > 0

    def to_dict(self) -> dict:
        return {
            "geoid": self.geoid,
            "nearest_open_km": (
                None if self.nearest_open_km is None else round(self.nearest_open_km, 3)
            ),
            "nearest_open_name": self.nearest_open_name,
            "open_within_walk": self.open_within_walk,
            "sites_within_walk": self.sites_within_walk,
            "hydration_within_walk": self.hydration_within_walk,
            "walkable_cover": self.walkable_cover,
        }


def coverage_for_tracts(
    tracts: Iterable[Tract],
    sites: list[CoolingSite],
    *,
    weekday: Weekday = "Wednesday",
    hour: float = 17.0,
    walkable_km: float = WALKABLE_KM,
) -> dict[str, TractCoverage]:
    """Evaluate cooling access per tract at a given weekday and hour.

    Distance is measured from the tract's representative centre to each site.
    That is coarse — a large tract can have its centre far from a site while its
    edge is next door — so results are most meaningful for the compact urban
    tracts that dominate central Phoenix.
    """
    cooling = [s for s in sites if s.is_cooling]
    hydration = [s for s in sites if not s.is_cooling]
    open_now = [s for s in cooling if s.open_at(weekday, hour)]

    out: dict[str, TractCoverage] = {}
    for tract in tracts:
        centre = tract.geometry.centroid

        nearest_km: float | None = None
        nearest_name: str | None = None
        for site in open_now:
            distance = haversine_km(centre, site.point)
            if nearest_km is None or distance < nearest_km:
                nearest_km, nearest_name = distance, site.name

        out[tract.geoid] = TractCoverage(
            geoid=tract.geoid,
            nearest_open_km=nearest_km,
            nearest_open_name=nearest_name,
            open_within_walk=sum(
                1 for s in open_now if haversine_km(centre, s.point) <= walkable_km
            ),
            sites_within_walk=sum(
                1 for s in cooling if haversine_km(centre, s.point) <= walkable_km
            ),
            hydration_within_walk=sum(
                1 for s in hydration if haversine_km(centre, s.point) <= walkable_km
            ),
        )
    return out


def open_site_count_by_hour(
    sites: list[CoolingSite], *, weekday: Weekday = "Wednesday"
) -> dict[int, int]:
    """How many cooling sites are open at each hour of a given weekday.

    This is the headline supply finding: plotted against the afternoon temperature
    peak it shows whether provision is aligned with when people actually need it.
    """
    cooling = [s for s in sites if s.is_cooling]
    return {hour: sum(1 for s in cooling if s.open_at(weekday, hour)) for hour in range(24)}


def supply_summary(sites: list[CoolingSite]) -> dict:
    """Composition and hours coverage of the network, for reporting."""
    cooling = [s for s in sites if s.is_cooling]
    by_type: dict[str, int] = {}
    for site in sites:
        by_type[site.site_type] = by_type.get(site.site_type, 0) + 1

    closing = [
        s.closing_hour("Wednesday")
        for s in cooling
        if s.closing_hour("Wednesday") is not None
    ]
    return {
        "n_sites": len(sites),
        "n_cooling_sites": len(cooling),
        "by_type": dict(sorted(by_type.items())),
        "with_parseable_weekday_hours": sum(1 for s in cooling if s.hours),
        "ada_accessible": sum(1 for s in cooling if s.ada_accessible is True),
        "median_weekday_closing_hour": (
            sorted(closing)[len(closing) // 2] if closing else None
        ),
        "season": {
            "start": sites[0].season_start if sites else None,
            "end": sites[0].season_end if sites else None,
        },
        "vintage_caveat": (
            "The Heat Relief Network service publishes only the current season. "
            "These sites describe today's network, not what was open during any "
            "past heat event."
        ),
    }
