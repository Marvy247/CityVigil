"""Study-area registry.

Every AOI here is sized close to the ~129.5 km² plan cap on purpose. Heatmap
generation costs a flat 4,220 credits regardless of area (measured: 81 tiles and
10,177 tiles cost identically), so requesting a small footprint wastes credits by
a factor of 100 or more. One large AOI per city, always.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _bbox_aoi(name: str, west: float, south: float, east: float, north: float) -> dict:
    """Build a GeoJSON FeatureCollection from a bounding box."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": name},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [west, south],
                            [east, south],
                            [east, north],
                            [west, north],
                            [west, south],
                        ]
                    ],
                },
            }
        ],
    }


@dataclass(frozen=True)
class City:
    """A study area with a default danger threshold and a known heat episode."""

    key: str
    name: str
    aoi: dict
    #: Local timezone offset from UTC in hours, for reading ``time_of_measure``.
    utc_offset_h: int
    #: Default danger threshold in Fahrenheit, the unit US agencies operate in.
    danger_threshold_f: float
    #: A real historical heat episode inside the 2021-present archive.
    episode_start: str
    episode_end: str
    episode_note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "utc_offset_h": self.utc_offset_h,
            "danger_threshold_f": self.danger_threshold_f,
            "episode": {
                "start": self.episode_start,
                "end": self.episode_end,
                "note": self.episode_note,
            },
            "aoi": self.aoi,
        }


#: Central Phoenix, ~101.7 km². The primary study area: the most extreme
#: large-city heat regime in the United States, and the city FortyGuard's own
#: marketing uses as its example.
#:
#: Primary episode is August 2026, inside the current Heat Relief Network season,
#: so heat and cooling-site supply are contemporaneous and the coverage gap is
#: what the operating network actually left open rather than a counterfactual.
PHOENIX = City(
    key="phoenix",
    name="Phoenix, AZ",
    aoi=_bbox_aoi("Central Phoenix", -112.130, 33.400, -112.020, 33.490),
    utc_offset_h=-7,  # MST year-round; Arizona does not observe DST
    danger_threshold_f=100.0,
    episode_start="2026-08-01",
    episode_end="2026-08-07",
    episode_note=(
        "Early August 2026 heat episode, inside the operating Heat Relief Network "
        "season (1 May - 30 Sep 2026), so coverage gaps are contemporaneous rather "
        "than counterfactual. Verified live: 85.5-95.7 hours above 100 F across the "
        "week, about 13.1 per day. Note that persistence returns a saturated "
        "constant 8.0 h for every tile in 2026 windows, so the no-relief signal is "
        "uninformative here; see PHOENIX_2024."
    ),
)

#: The same footprint over a July 2024 episode, retained deliberately.
#:
#: Measured across three separate 2026 windows, ``persistence`` returns a flat 8.0 h
#: for every tile, which cannot be a real spatial field. The 2024 window returns
#: 6.79-8.27 h and varies sensibly. Since the distinction between *total* dangerous
#: hours and the *longest unbroken run* is central to how CityVigil ranks risk, that
#: claim is demonstrated on the window where the layer actually behaves, and the
#: saturation is reported as an API characteristic rather than hidden.
PHOENIX_2024 = City(
    key="phoenix-2024",
    name="Phoenix, AZ (July 2024 reference window)",
    aoi=_bbox_aoi("Central Phoenix", -112.130, 33.400, -112.020, 33.490),
    utc_offset_h=-7,
    danger_threshold_f=100.0,
    episode_start="2024-07-15",
    episode_end="2024-07-21",
    episode_note=(
        "July 2024 reference window. Kept because persistence varies here "
        "(6.79-8.27 h) while 2026 windows return a saturated constant, so this is "
        "where the total-hours versus unbroken-hours distinction can be shown. "
        "Cooling-site supply is NOT contemporaneous with this window, so coverage "
        "results against it are counterfactual."
    ),
)

CITIES: dict[str, City] = {c.key: c for c in (PHOENIX, PHOENIX_2024)}


def get_city(key: str) -> City:
    """Look up a study area by key."""
    try:
        return CITIES[key.strip().lower()]
    except KeyError:
        raise KeyError(f"unknown city {key!r}; available: {sorted(CITIES)}") from None
