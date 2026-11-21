import pytest
from shapely.geometry import (GeometryCollection, LineString, MultiPoint, MultiPolygon, Point, Polygon,
                              mapping, shape)
from shapely.ops import unary_union

from hexgrid_maker import hex_grid
from hexgrid_maker.core import from_geojson

SQUARE = [(2.29, 48.85), (2.31, 48.85), (2.31, 48.87), (2.29, 48.87), (2.29, 48.85)]
HOLE = [(2.295, 48.855), (2.295, 48.865), (2.305, 48.865), (2.305, 48.855), (2.295, 48.855)]
LANDMARKS = [(2.2945, 48.8584), (2.3376, 48.8606), (2.3522, 48.8566)]


def ids(grid):
    return {(f["properties"]["col"], f["properties"]["row"]) for f in grid["features"]}


def test_hole_not_filled_by_point_inside_hole():
    g = {"type": "GeometryCollection", "geometries": [
        mapping(Polygon(SQUARE, [HOLE])), mapping(Point(2.3, 48.86))]}
    out = from_geojson(g)
    assert not out.contains(Point(2.298, 48.86))  # hole stays empty
    assert out.contains(Point(2.292, 48.86))


@pytest.mark.parametrize("geom", [
    MultiPoint(LANDMARKS),
    LineString(LANDMARKS),
])
def test_shapely_and_geojson_inputs_cover_same_area(geom):
    a = hex_grid(geom, 200)
    b = hex_grid(mapping(geom), 200)
    assert ids(a) == ids(b)
    assert len(a["features"]) > 3  # hull area, not only cells around the points


def test_wide_bbox_is_input_error_not_crash():
    with pytest.raises(ValueError):
        hex_grid((-100, -1, 100, 1), 50_000)


@pytest.mark.parametrize("bad", [
    None, "", "bbox", 5, [], [1, 2, 3], (1, 2, 3, 4, 5), (0, 0, float("nan"), 1),
    (0, 0, "1", 1), (0, 0, None, 1), {}, {"type": "Feature"}, {"type": "FeatureCollection", "features": None},
    {"type": "FeatureCollection", "features": []}, {"type": "Point", "coordinates": []},
    {"type": "Polygon", "coordinates": "x"}, Polygon(), (10, 0, 5, 1), (0, 0, 1, 95),
    GeometryCollection(), GeometryCollection([GeometryCollection([Polygon()])]),
    {"type": "GeometryCollection", "geometries": []}, {"type": "GeometryCollection", "geometries": None},
    {"type": "Point", "coordinates": [float("nan"), 1.0]}, Point(float("inf"), 1),
    {"type": "Feature", "geometry": None, "properties": {}},
])
def test_bad_geometry_inputs_raise_value_error(bad):
    with pytest.raises(ValueError):
        hex_grid(bad, 100)


@pytest.mark.parametrize("size", [0, -5, None, "100", float("nan"), float("inf"), True, [100]])
def test_bad_size_raises_value_error(size):
    with pytest.raises(ValueError):
        hex_grid((2.29, 48.85, 2.30, 48.86), size)


@pytest.mark.parametrize("kw", [
    {"orientation": "hex"}, {"orientation": None}, {"clip": "yes"}, {"clip": None},
    {"max_cells": 0}, {"max_cells": 1.5}, {"max_cells": None},
])
def test_bad_options_raise_value_error(kw):
    with pytest.raises(ValueError):
        hex_grid((2.29, 48.85, 2.30, 48.86), 100, **kw)


SQ2 = [(2.32, 48.85), (2.34, 48.85), (2.34, 48.87), (2.32, 48.87), (2.32, 48.85)]
TRIANGLE = [(2.30, 48.86), (2.36, 48.80), (2.36, 48.90)]  # first point lies inside SQUARE


@pytest.mark.parametrize("geom, expected", [
    # MultiPolygon nested inside a collection with a point keeps both squares.
    (GeometryCollection([MultiPolygon([Polygon(SQUARE), Polygon(SQ2)]), Point(2.40, 48.86)]),
     unary_union([Polygon(SQUARE), Polygon(SQ2)])),
    # Nested collection: the hole stays a hole, not convex-hulled away.
    (GeometryCollection([GeometryCollection([Polygon(SQUARE, [HOLE])]), Point(2.30, 48.86)]),
     Polygon(SQUARE, [HOLE])),
    # Point inside a polygon still counts for the hull of the points.
    (GeometryCollection([Polygon(SQUARE), MultiPoint(TRIANGLE)]),
     unary_union([Polygon(SQUARE), Polygon(TRIANGLE)])),
    # Invalid bow-tie next to a point: repaired polygon and the point both kept.
    (GeometryCollection([Polygon([(2.29, 48.85), (2.31, 48.87), (2.31, 48.85), (2.29, 48.87)]),
                         Point(2.40, 48.86)]),
     None),
])
def test_mixed_inputs_same_result_for_every_representation(geom, expected):
    from hexgrid_maker.core import _as_geometry
    as_shapely = _as_geometry(geom)
    as_geojson = from_geojson(mapping(geom))
    as_features = from_geojson({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": mapping(p)} for p in geom.geoms]})
    for out in (as_geojson, as_features):
        assert out.symmetric_difference(as_shapely).area < 1e-12
    if expected is not None:
        assert as_shapely.symmetric_difference(expected).area < 1e-12
    else:
        assert as_shapely.area > 0 and as_shapely.intersects(Point(2.40, 48.86))
    assert ids(hex_grid(geom, 300)) == ids(hex_grid(mapping(geom), 300))


def test_shape_roundtrip_polygon_unchanged():
    p = Polygon(SQUARE, [HOLE])
    assert shape(mapping(from_geojson(mapping(p)))).equals(p)
