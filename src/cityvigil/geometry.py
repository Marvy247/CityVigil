"""Dependency-free planar geometry for spatial joins.

Why not shapely or geopandas
----------------------------
The only spatial operation CityVigil needs is "which census tract contains this
tile centroid", repeated a few tens of thousands of times. That is a ray-casting
point-in-polygon test plus a spatial index, roughly 150 lines. Pulling in
geopandas would add a compiled GDAL/PROJ toolchain to a project whose whole
credibility argument rests on a judge being able to clone it and run it. The
trade is deliberate: a little arithmetic here in exchange for
``pip install -r requirements.txt`` never failing.

Coordinates are treated as planar lon/lat degrees. Over a single county that is
accurate enough for containment tests — tract boundaries are hundreds of metres
apart and tiles are 60-100 m, so no projection is needed to decide which tract a
point falls in. Area and distance calculations would need a projection, and this
module deliberately does not offer them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence

Point = tuple[float, float]
Ring = Sequence[Point]
BBox = tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat)


# ------------------------------------------------------------------ primitives


def ring_bbox(ring: Ring) -> BBox:
    """Bounding box of a coordinate ring."""
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return (min(lons), min(lats), max(lons), max(lats))


def bbox_union(boxes: Iterable[BBox]) -> BBox:
    """Smallest box containing every input box."""
    boxes = list(boxes)
    if not boxes:
        raise ValueError("cannot union an empty set of boxes")
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def bbox_contains(box: BBox, point: Point) -> bool:
    """Inclusive point-in-box test."""
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def point_in_ring(point: Point, ring: Ring) -> bool:
    """Ray-casting containment test for a single closed ring.

    Counts crossings of a ray cast in the +longitude direction. Points exactly on
    an edge are not guaranteed either way, which is acceptable here: tile centroids
    landing precisely on a tract boundary are vanishingly rare and either
    assignment is defensible.
    """
    x, y = point
    inside = False
    n = len(ring)
    if n < 3:
        return False

    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        # Does the edge straddle the horizontal line through y?
        if (yi > y) != (yj > y):
            # Longitude where the edge crosses that line.
            t = (y - yi) / (yj - yi)
            if x < xi + t * (xj - xi):
                inside = not inside
        j = i
    return inside


# -------------------------------------------------------------------- polygons


@dataclass(frozen=True)
class Polygon:
    """A polygon with an outer ring and zero or more holes."""

    outer: tuple[Point, ...]
    holes: tuple[tuple[Point, ...], ...] = ()

    @property
    def bbox(self) -> BBox:
        return ring_bbox(self.outer)

    def contains(self, point: Point) -> bool:
        """True when the point is inside the outer ring and not inside a hole."""
        if not bbox_contains(self.bbox, point):
            return False
        if not point_in_ring(point, self.outer):
            return False
        return not any(point_in_ring(point, hole) for hole in self.holes)

    @property
    def area_km2(self) -> float:
        """Outer-ring area less the area of every hole."""
        return max(
            ring_area_km2(self.outer) - sum(ring_area_km2(h) for h in self.holes), 0.0
        )


@dataclass(frozen=True)
class MultiPolygon:
    """One or more polygons treated as a single feature."""

    polygons: tuple[Polygon, ...]

    @property
    def bbox(self) -> BBox:
        return bbox_union(p.bbox for p in self.polygons)

    def contains(self, point: Point) -> bool:
        return any(p.contains(point) for p in self.polygons)

    @property
    def area_km2(self) -> float:
        """Total area across every part, in km²."""
        return sum(p.area_km2 for p in self.polygons)

    @property
    def centroid(self) -> Point:
        """Vertex-average centre of the outer rings.

        Not the true area centroid, and not used for anything that needs one — it
        exists only to label a tract with a representative location.
        """
        pts = [pt for poly in self.polygons for pt in poly.outer]
        if not pts:
            raise ValueError("cannot take the centroid of an empty geometry")
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _clean_ring(coords: Sequence[Sequence[float]]) -> tuple[Point, ...]:
    """Coerce a GeoJSON ring to a tuple of 2-tuples, dropping any Z ordinate."""
    return tuple((float(c[0]), float(c[1])) for c in coords if len(c) >= 2)


def ring_area_km2(ring: Ring) -> float:
    """Absolute area of a ring in km², via a local equal-area approximation.

    Longitude and latitude are scaled to kilometres about the ring's mean latitude
    and the shoelace formula applied. Over a census tract — at most a few km across
    — the error from ignoring Earth's curvature is well under a percent, which is
    far tighter than the census population counts this area is used to normalise.

    This is deliberately the only area function in the module. Anything demanding
    real accuracy should reproject properly rather than lean on this.
    """
    if len(ring) < 3:
        return 0.0

    mean_lat = sum(p[1] for p in ring) / len(ring)
    km_per_deg_lat = 110.574
    km_per_deg_lon = 111.320 * math.cos(math.radians(mean_lat))

    xs = [p[0] * km_per_deg_lon for p in ring]
    ys = [p[1] * km_per_deg_lat for p in ring]

    total = 0.0
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        total += xs[i] * ys[j] - xs[j] * ys[i]
    return abs(total) / 2.0


#: Mean Earth radius in kilometres (WGS-84 mean).
EARTH_RADIUS_KM = 6371.0088


def haversine_km(a: Point, b: Point) -> float:
    """Great-circle distance between two ``(lon, lat)`` points, in kilometres.

    Straight-line distance, not street-network distance. Real walking distance is
    always longer — typically 20-40% even in a gridded city like Phoenix — so any
    coverage claim built on this is optimistic and must say so.
    """
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    h = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def from_geojson_geometry(geometry: dict) -> MultiPolygon:
    """Build a :class:`MultiPolygon` from a GeoJSON Polygon or MultiPolygon.

    :raises ValueError: for any other geometry type.
    """
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []

    if gtype == "Polygon":
        rings = [_clean_ring(r) for r in coords]
        if not rings:
            raise ValueError("Polygon has no rings")
        return MultiPolygon((Polygon(rings[0], tuple(rings[1:])),))

    if gtype == "MultiPolygon":
        polys = []
        for part in coords:
            rings = [_clean_ring(r) for r in part]
            if rings:
                polys.append(Polygon(rings[0], tuple(rings[1:])))
        if not polys:
            raise ValueError("MultiPolygon has no polygons")
        return MultiPolygon(tuple(polys))

    raise ValueError(f"unsupported geometry type {gtype!r}; expected Polygon or MultiPolygon")


# ----------------------------------------------------------------------- index


class GridIndex:
    """Uniform-grid spatial index over labelled geometries.

    Each geometry is registered in every grid cell its bounding box overlaps.
    A lookup tests only the geometries sharing the query point's cell, which turns
    an O(tracts) scan per point into a handful of candidate tests. For ~1,000
    tracts and ~10,000 points that is the difference between minutes and
    milliseconds.
    """

    def __init__(self, items: Iterable[tuple[str, MultiPolygon]], cell_size: float = 0.02) -> None:
        """
        Parameters
        ----------
        items:
            ``(key, geometry)`` pairs.
        cell_size:
            Grid cell edge in degrees. 0.02 deg is roughly 2 km, a few times the
            typical urban tract, which keeps candidate lists short without
            producing a huge sparse grid.
        """
        if cell_size <= 0:
            raise ValueError("cell_size must be positive")
        self.cell_size = cell_size
        self._geoms: dict[str, MultiPolygon] = {}
        self._cells: dict[tuple[int, int], list[str]] = {}

        for key, geom in items:
            self._geoms[key] = geom
            for cell in self._cells_for_bbox(geom.bbox):
                self._cells.setdefault(cell, []).append(key)

    def _cell_of(self, lon: float, lat: float) -> tuple[int, int]:
        return (math.floor(lon / self.cell_size), math.floor(lat / self.cell_size))

    def _cells_for_bbox(self, box: BBox) -> Iterator[tuple[int, int]]:
        min_x, min_y = self._cell_of(box[0], box[1])
        max_x, max_y = self._cell_of(box[2], box[3])
        for gx in range(min_x, max_x + 1):
            for gy in range(min_y, max_y + 1):
                yield (gx, gy)

    def __len__(self) -> int:
        return len(self._geoms)

    @property
    def keys(self) -> list[str]:
        return list(self._geoms)

    def candidates(self, point: Point) -> list[str]:
        """Keys whose bounding box cell contains the point. Cheap, approximate."""
        return list(self._cells.get(self._cell_of(point[0], point[1]), ()))

    def find(self, point: Point) -> str | None:
        """Key of the first geometry actually containing the point, else ``None``.

        Tracts do not overlap, so "first match" is unambiguous in practice.
        """
        for key in self.candidates(point):
            if self._geoms[key].contains(point):
                return key
        return None

    def geometry(self, key: str) -> MultiPolygon:
        return self._geoms[key]
