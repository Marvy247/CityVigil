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
PHOENIX = City(
    key="phoenix",
    name="Phoenix, AZ",
    aoi=_bbox_aoi("Central Phoenix", -112.130, 33.400, -112.020, 33.490),
    utc_offset_h=-7,  # MST year-round; Arizona does not observe DST
    danger_threshold_f=100.0,
    episode_start="2024-07-15",
    episode_end="2024-07-21",
    episode_note=(
        "July 2024 Phoenix heat episode. Verified live: central Phoenix tiles "
        "spent 89-91 hours above 100 F across this week, with a longest unbroken "
        "run of 7.1-8.1 hours."
    ),
)

CITIES: dict[str, City] = {PHOENIX.key: PHOENIX}


def get_city(key: str) -> City:
    """Look up a study area by key."""
    try:
        return CITIES[key.strip().lower()]
    except KeyError:
        raise KeyError(f"unknown city {key!r}; available: {sorted(CITIES)}") from None
