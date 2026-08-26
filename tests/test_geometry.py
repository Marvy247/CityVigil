"""Geometry primitives: containment, holes, and the spatial index."""

from __future__ import annotations

import pytest

from cityvigil.geometry import (
    GridIndex,
    MultiPolygon,
    Polygon,
    bbox_contains,
    bbox_union,
    from_geojson_geometry,
    haversine_km,
    point_in_ring,
    ring_area_km2,
    ring_bbox,
)

SQUARE = ((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0), (0.0, 0.0))
HOLE = ((0.8, 0.8), (1.2, 0.8), (1.2, 1.2), (0.8, 1.2), (0.8, 0.8))


# ------------------------------------------------------------------ primitives


def test_ring_bbox():
    assert ring_bbox(SQUARE) == (0.0, 0.0, 2.0, 2.0)


def test_bbox_union():
    assert bbox_union([(0, 0, 1, 1), (2, 2, 3, 4)]) == (0, 0, 3, 4)


def test_bbox_union_rejects_empty():
    with pytest.raises(ValueError, match="empty set"):
        bbox_union([])


def test_bbox_contains_is_inclusive():
    assert bbox_contains((0, 0, 1, 1), (0.0, 0.0))
    assert bbox_contains((0, 0, 1, 1), (1.0, 1.0))
    assert not bbox_contains((0, 0, 1, 1), (1.001, 0.5))


def test_point_in_ring_basic():
    assert point_in_ring((1.0, 1.0), SQUARE)
    assert not point_in_ring((3.0, 1.0), SQUARE)
    assert not point_in_ring((-1.0, 1.0), SQUARE)


def test_point_in_ring_degenerate_ring():
    assert not point_in_ring((0.0, 0.0), ((0.0, 0.0), (1.0, 1.0)))


def test_point_in_ring_handles_concave_shape():
    """An L-shape: the notch must read as outside."""
    l_shape = (
        (0.0, 0.0),
        (3.0, 0.0),
        (3.0, 1.0),
        (1.0, 1.0),
        (1.0, 3.0),
        (0.0, 3.0),
        (0.0, 0.0),
    )
    assert point_in_ring((0.5, 2.5), l_shape)
    assert point_in_ring((2.5, 0.5), l_shape)
    assert not point_in_ring((2.5, 2.5), l_shape), "the notch is outside the L"


# -------------------------------------------------------------------- polygons


def test_polygon_contains():
    poly = Polygon(SQUARE)
    assert poly.contains((1.0, 1.0))
    assert not poly.contains((5.0, 5.0))


def test_hole_is_excluded():
    """A tract with an enclave must not claim points inside the enclave."""
    poly = Polygon(SQUARE, (HOLE,))
    assert poly.contains((0.2, 0.2)), "inside outer, outside hole"
    assert not poly.contains((1.0, 1.0)), "inside the hole is outside the polygon"


def test_multipolygon_contains_any_part():
    a = Polygon(SQUARE)
    b = Polygon(((10.0, 10.0), (11.0, 10.0), (11.0, 11.0), (10.0, 11.0), (10.0, 10.0)))
    mp = MultiPolygon((a, b))
    assert mp.contains((1.0, 1.0))
    assert mp.contains((10.5, 10.5))
    assert not mp.contains((5.0, 5.0))
    assert mp.bbox == (0.0, 0.0, 11.0, 11.0)


def test_multipolygon_centroid_is_within_bbox():
    mp = MultiPolygon((Polygon(SQUARE),))
    lon, lat = mp.centroid
    assert 0.0 <= lon <= 2.0 and 0.0 <= lat <= 2.0


# --------------------------------------------------------------------- geojson


def test_from_geojson_polygon_with_hole():
    geom = {
        "type": "Polygon",
        "coordinates": [[list(p) for p in SQUARE], [list(p) for p in HOLE]],
    }
    mp = from_geojson_geometry(geom)
    assert len(mp.polygons) == 1
    assert len(mp.polygons[0].holes) == 1
    assert mp.contains((0.2, 0.2))
    assert not mp.contains((1.0, 1.0))


def test_from_geojson_multipolygon():
    geom = {
        "type": "MultiPolygon",
        "coordinates": [
            [[list(p) for p in SQUARE]],
            [[[10.0, 10.0], [11.0, 10.0], [11.0, 11.0], [10.0, 10.0]]],
        ],
    }
    mp = from_geojson_geometry(geom)
    assert len(mp.polygons) == 2


def test_from_geojson_drops_z_ordinate():
    geom = {"type": "Polygon", "coordinates": [[[0, 0, 99], [2, 0, 99], [2, 2, 99], [0, 0, 99]]]}
    mp = from_geojson_geometry(geom)
    assert all(len(p) == 2 for p in mp.polygons[0].outer)


def test_from_geojson_rejects_points():
    with pytest.raises(ValueError, match="unsupported geometry type"):
        from_geojson_geometry({"type": "Point", "coordinates": [0, 0]})


def test_from_geojson_rejects_empty_polygon():
    with pytest.raises(ValueError, match="no rings"):
        from_geojson_geometry({"type": "Polygon", "coordinates": []})


# ----------------------------------------------------------------------- index


def _grid() -> GridIndex:
    a = MultiPolygon((Polygon(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0))),))
    b = MultiPolygon((Polygon(((1.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0), (1.0, 0.0))),))
    return GridIndex([("A", a), ("B", b)], cell_size=0.25)


def test_index_finds_containing_geometry():
    idx = _grid()
    assert idx.find((0.5, 0.5)) == "A"
    assert idx.find((1.5, 0.5)) == "B"


def test_index_returns_none_outside_everything():
    assert _grid().find((9.0, 9.0)) is None


def test_index_reports_size_and_keys():
    idx = _grid()
    assert len(idx) == 2
    assert sorted(idx.keys) == ["A", "B"]


def test_candidates_narrow_the_search():
    """The index must not offer every geometry for every point."""
    idx = _grid()
    assert idx.candidates((0.1, 0.1)) == ["A"]
    assert idx.candidates((1.9, 0.9)) == ["B"]


def test_index_rejects_bad_cell_size():
    with pytest.raises(ValueError, match="cell_size must be positive"):
        GridIndex([], cell_size=0)


def test_index_handles_geometry_spanning_many_cells():
    """A geometry far larger than one cell must still be found anywhere inside."""
    big = MultiPolygon((Polygon(((0.0, 0.0), (5.0, 0.0), (5.0, 5.0), (0.0, 5.0), (0.0, 0.0))),))
    idx = GridIndex([("BIG", big)], cell_size=0.1)
    for pt in [(0.05, 0.05), (2.5, 2.5), (4.95, 4.95)]:
        assert idx.find(pt) == "BIG", f"{pt} should be inside"


def test_index_geometry_accessor():
    idx = _grid()
    assert idx.geometry("A").contains((0.5, 0.5))


# ------------------------------------------------------------------------ area


def test_ring_area_of_one_degree_square_at_equator():
    """One degree square at the equator is roughly 12,300 km²."""
    ring = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0))
    assert ring_area_km2(ring) == pytest.approx(12310, rel=0.02)


def test_ring_area_shrinks_with_latitude():
    """The same degree box covers less ground nearer the pole."""
    at_equator = ring_area_km2(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)))
    at_phoenix = ring_area_km2(
        ((0.0, 33.0), (1.0, 33.0), (1.0, 34.0), (0.0, 34.0), (0.0, 33.0))
    )
    assert at_phoenix < at_equator
    # cos(33.5 deg) is about 0.834.
    assert at_phoenix / at_equator == pytest.approx(0.834, rel=0.02)


def test_ring_area_is_orientation_independent():
    clockwise = ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0))
    counter = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0))
    assert ring_area_km2(clockwise) == pytest.approx(ring_area_km2(counter))


def test_degenerate_ring_has_no_area():
    assert ring_area_km2(((0.0, 0.0), (1.0, 1.0))) == 0.0


def test_polygon_area_subtracts_holes():
    outer = Polygon(SQUARE)
    with_hole = Polygon(SQUARE, (HOLE,))
    assert with_hole.area_km2 < outer.area_km2
    assert with_hole.area_km2 == pytest.approx(
        outer.area_km2 - ring_area_km2(HOLE), rel=1e-6
    )


def test_polygon_area_never_negative_when_holes_overrun():
    """Malformed input must not produce a negative area."""
    huge_hole = ((-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0), (-10.0, -10.0))
    assert Polygon(SQUARE, (huge_hole,)).area_km2 == 0.0


def test_multipolygon_area_sums_parts():
    a = Polygon(SQUARE)
    b = Polygon(((10.0, 0.0), (11.0, 0.0), (11.0, 1.0), (10.0, 1.0), (10.0, 0.0)))
    assert MultiPolygon((a, b)).area_km2 == pytest.approx(a.area_km2 + b.area_km2)


# -------------------------------------------------------------------- distance


def test_haversine_zero_for_same_point():
    assert haversine_km((-112.07, 33.45), (-112.07, 33.45)) == pytest.approx(0.0)


def test_haversine_one_degree_latitude():
    """One degree of latitude is about 111.2 km anywhere on Earth."""
    assert haversine_km((0.0, 0.0), (0.0, 1.0)) == pytest.approx(111.19, rel=0.01)


def test_haversine_is_symmetric():
    a, b = (-112.07, 33.45), (-112.10, 33.50)
    assert haversine_km(a, b) == pytest.approx(haversine_km(b, a))


def test_haversine_known_city_distance():
    """Phoenix to Tucson is about 171 km great-circle.

    Not the ~187 km road distance along I-10 — this function returns straight-line
    distance, and conflating the two is exactly the error a coverage claim must
    avoid.
    """
    phoenix = (-112.0740, 33.4484)
    tucson = (-110.9747, 32.2226)
    assert haversine_km(phoenix, tucson) == pytest.approx(170.7, rel=0.01)


def test_haversine_short_urban_distance():
    """A 0.01 degree latitude step in Phoenix is about 1.11 km."""
    assert haversine_km((-112.07, 33.45), (-112.07, 33.46)) == pytest.approx(1.11, rel=0.02)
