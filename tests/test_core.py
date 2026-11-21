import json
import math

import pytest
import shapely
from pyproj import Geod
from shapely.geometry import Point, Polygon, shape

from hexgrid_maker import hex_grid
from hexgrid_maker.cli import main

# 1 km^2-ish box over central Paris (west, south, east, north)
PARIS = (2.29, 48.85, 2.31, 48.865)


def area(feature):
    return abs(Geod(ellps="WGS84").geometry_area_perimeter(shape(feature["geometry"]))[0])


@pytest.mark.parametrize("orientation", ["flat", "pointy"])
def test_cell_area_matches_regular_hexagon(orientation):
    s = 100
    grid = hex_grid(PARIS, s, orientation)
    expected = 3 * math.sqrt(3) / 2 * s * s
    for f in grid["features"]:
        assert area(f) == pytest.approx(expected, rel=0.005)  # UTM scale factor < 0.1 %
        assert f["properties"]["area_m2"] == pytest.approx(area(f), abs=0.1)


def test_eiffel_tower_in_exactly_one_cell_and_covers_bbox():
    grid = hex_grid(PARIS, 150)
    eiffel = Point(2.2945, 48.8584)  # lon, lat
    assert sum(shape(f["geometry"]).contains(eiffel) for f in grid["features"]) == 1
    corners = [Point(2.29, 48.85), Point(2.31, 48.865), Point(2.29, 48.865), Point(2.31, 48.85)]
    for c in corners:
        assert any(shape(f["geometry"]).intersects(c) for f in grid["features"])


def test_orientation_differs_and_flat_top_has_horizontal_edge():
    flat = shape(hex_grid(PARIS, 100, "flat")["features"][0]["geometry"])
    pointy = shape(hex_grid(PARIS, 100, "pointy")["features"][0]["geometry"])
    def top_vertices(poly):
        ys = [y for _, y in poly.exterior.coords[:-1]]
        return sum(abs(y - max(ys)) < 2e-5 for y in ys)  # 2e-5 deg is about 2 m; UTM grid north is rotated ~0.4 deg here

    assert top_vertices(flat) == 2  # horizontal top edge
    assert top_vertices(pointy) == 1  # apex


def test_rings_counter_clockwise_closed():
    for f in hex_grid(PARIS, 200)["features"]:
        ring = f["geometry"]["coordinates"][0]
        assert ring[0] == ring[-1] and len(ring) == 7
        assert shape(f["geometry"]).exterior.is_ccw


def test_polygon_with_hole_and_clip():
    outer = [(2.28, 48.84), (2.32, 48.84), (2.32, 48.88), (2.28, 48.88)]
    hole = [(2.29, 48.85), (2.29, 48.87), (2.31, 48.87), (2.31, 48.85)]
    poly = Polygon(outer, [hole])
    plain = hex_grid(poly, 300)
    clipped = hex_grid(poly, 300, clip=True)
    centre = Point(2.30, 48.86)
    assert not any(shape(f["geometry"]).contains(centre) for f in plain["features"])
    assert all(shape(f["geometry"]).within(poly.buffer(1e-4))  # straight edges in UTM vs lon/lat: well under 10 m
for f in clipped["features"])
    expected = abs(Geod(ellps="WGS84").geometry_area_perimeter(poly)[0])
    assert sum(map(area, clipped["features"])) == pytest.approx(expected, rel=0.01)


def test_southern_hemisphere_and_huge_count_rejected():
    sydney = hex_grid((151.20, -33.87, 151.22, -33.85), 200)  # southern UTM zone
    assert sydney["features"]
    with pytest.raises(ValueError):
        hex_grid(PARIS, 0.5, max_cells=1000)


@pytest.mark.parametrize("orientation", ["flat", "pointy"])
def test_max_cells_is_an_output_limit_not_a_candidate_limit(orientation):
    eiffel = Point(2.2945, 48.8584)
    one = hex_grid(eiffel, 100, orientation, max_cells=1)
    assert len(one["features"]) == 1
    assert shape(one["features"][0]["geometry"]).contains(eiffel)
    n = len(hex_grid(PARIS, 300, orientation)["features"])
    assert n > 1
    assert len(hex_grid(PARIS, 300, orientation, max_cells=n)["features"]) == n
    with pytest.raises(ValueError, match="more than"):
        hex_grid(PARIS, 300, orientation, max_cells=n - 1)


@pytest.mark.parametrize("bad", [(170, 0, -170, 10), (0, -95, 1, 0), (0, 0, 190, 1)])
def test_bad_bounds_rejected(bad):
    with pytest.raises(ValueError):
        hex_grid(bad, 1000)


def test_invalid_arguments():
    with pytest.raises(ValueError):
        hex_grid(PARIS, -5)
    with pytest.raises(ValueError):
        hex_grid(PARIS, 100, "square")
    with pytest.raises(ValueError):
        hex_grid(Polygon(), 100)


def test_cli_bbox_to_file(tmp_path, capsys):
    out = tmp_path / "g.geojson"
    code = main(["--bbox", *map(str, PARIS), "--size", "200", "-o", str(out)])
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["type"] == "FeatureCollection"
    assert main(["--bbox", "0", "0", "1", "1", "--size", "0"]) == 2


def test_reversed_bbox_gives_bounds_error():
    with pytest.raises(ValueError, match="antimeridian"):
        hex_grid((170, 0, -170, 10), 100000)


def test_partly_polar_input_rejected():
    with pytest.raises(ValueError, match="UTM coverage"):
        hex_grid((10, 82, 11, 85), 5000)


def test_near_antimeridian_rejected_not_wrapped():
    with pytest.raises(ValueError, match="antimeridian"):
        hex_grid((179.99, 10, 180, 10.01), 2000)


def test_clip_keeps_multipart_cells():
    from shapely.geometry import MultiPolygon

    # two ~75 x 110 m squares 220 m apart, both inside the one 2 km cell centred on the first
    a = Polygon([(2.300, 48.860), (2.301, 48.860), (2.301, 48.861), (2.300, 48.861)])
    b = Polygon([(2.304, 48.860), (2.305, 48.860), (2.305, 48.861), (2.304, 48.861)])
    feats = hex_grid(MultiPolygon([a, b]), 2000, clip=True)["features"]
    multi = [f for f in feats if f["geometry"]["type"] == "MultiPolygon"]
    assert len(multi) == 1
    cell = shape(multi[0]["geometry"])
    assert len(cell.geoms) == 2
    assert cell.intersects(a.centroid) and cell.intersects(b.centroid)
    geod = Geod(ellps="WGS84")
    want = abs(geod.geometry_area_perimeter(a)[0]) + abs(geod.geometry_area_perimeter(b)[0])
    assert sum(f["properties"]["area_m2"] for f in feats) == pytest.approx(want, rel=0.005)


def test_equator_crossing_bbox_near_nairobi():
    feats = hex_grid((36.9, -0.01, 37.0, 0.02), 500)["features"]
    on_equator = Point(36.95, 0.0)
    assert sum(shape(f["geometry"]).contains(on_equator) for f in feats) == 1


def write(tmp_path, data):
    path = tmp_path / "in.geojson"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


TRIANGLE = {"type": "Polygon", "coordinates": [[[2.29, 48.85], [2.31, 48.85], [2.31, 48.865], [2.29, 48.85]]]}


@pytest.mark.parametrize("name, ok", [
    ("urn:ogc:def:crs:OGC:1.3:CRS84", True),
    ("EPSG:4326", True),
    ("EPSG:4267", False),  # NAD27: same-looking lon/lat on another datum
    ("EPSG:3857", False),
    ("not a crs", False),
])
def test_declared_geojson_crs(tmp_path, name, ok):
    data = {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": name}},
            "features": [{"type": "Feature", "properties": {}, "geometry": TRIANGLE}]}
    path = write(tmp_path, data)
    assert main(["--input", path, "--size", "300", "-o", str(tmp_path / "o.json")]) == (0 if ok else 2)


def test_invalid_polygons_repaired_through_cli(tmp_path):
    bowtie = {"type": "Polygon", "coordinates": [[[2.29, 48.85], [2.31, 48.865], [2.31, 48.85],
                                                 [2.29, 48.865], [2.29, 48.85]]]}
    feats = [{"type": "Feature", "properties": {}, "geometry": g} for g in (bowtie, TRIANGLE)]
    out = tmp_path / "o.json"
    assert main(["--input", write(tmp_path, {"type": "FeatureCollection", "features": feats}),
                 "--size", "300", "--clip", "-o", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["features"]


NAN = float("nan")
BAD_INPUTS = [  # (geometry, size_m, extra keyword arguments)
    (None, 100, {}),
    ("2.29,48.85,2.31,48.865", 100, {}),
    (42, 100, {}),
    ((), 100, {}),
    ((2.29, 48.85, 2.31), 100, {}),
    ((2.29, NAN, 2.31, 48.865), 100, {}),
    ((2.29, 48.85, float("inf"), 48.865), 100, {}),
    (("2.29", 48.85, 2.31, 48.865), 100, {}),
    ((True, 48.85, 2.31, 48.865), 100, {}),
    ((None, 48.85, 2.31, 48.865), 100, {}),
    ({}, 100, {}),
    ({"type": "Polygon"}, 100, {}),
    ({"type": "Polygon", "coordinates": "x"}, 100, {}),
    ({"type": "Feature", "geometry": None}, 100, {}),
    ({"type": "FeatureCollection", "features": []}, 100, {}),
    ({"type": "FeatureCollection", "features": None}, 100, {}),
    ({"type": "FeatureCollection", "features": [1]}, 100, {}),
    ({"type": "Point", "coordinates": [NAN, 48.86]}, 100, {}),
    (Polygon(), 100, {}),
    (Point(NAN, 48.86), 100, {}),
    (PARIS, None, {}),
    (PARIS, "100", {}),
    (PARIS, NAN, {}),
    (PARIS, float("inf"), {}),
    (PARIS, True, {}),
    (PARIS, 0, {}),
    (PARIS, 100, {"orientation": None}),
    (PARIS, 100, {"orientation": ["flat"]}),
    (PARIS, 100, {"clip": "yes"}),
    (PARIS, 100, {"max_cells": 0}),
    (PARIS, 100, {"max_cells": 10.5}),
    (PARIS, 100, {"max_cells": True}),
]


@pytest.mark.parametrize("geom, size, kwargs", BAD_INPUTS)
def test_bad_inputs_raise_value_error(geom, size, kwargs):
    with pytest.raises(ValueError):
        hex_grid(geom, size, **kwargs)


@pytest.mark.parametrize("text", ["", "[]", "null", '"text"', "{not json", '{"type": "Feature"}'])
def test_bad_files_give_cli_error(tmp_path, text):
    path = tmp_path / "bad.geojson"
    path.write_text(text, encoding="utf-8")
    assert main(["--input", str(path), "--size", "100"]) == 2
    assert main(["--input", str(tmp_path / "missing.geojson"), "--size", "100"]) == 2


def test_mapping_input_matches_shapely_input():
    assert hex_grid(TRIANGLE, 300) == hex_grid(shape(TRIANGLE), 300)


def test_bbox_edges_densified_before_projection():
    # Parallels bow in UTM; with corner-only projection a 50 m grid misses the middle of the south edge.
    grid = hex_grid((2.5, 48.8, 3.5, 48.82), 50)
    cells = shapely.union_all([shape(f["geometry"]) for f in grid["features"]])
    edge = [Point(2.5 + i / 200, lat) for i in range(201) for lat in (48.8, 48.82)]
    assert all(cells.covers(p) for p in edge)


def _named(name):
    return {"type": "name", "properties": {"name": name}}


NAD27 = _named("EPSG:4267")
NESTED_CRS = [  # every place a legacy crs member can appear
    {"type": "Feature", "properties": {}, "geometry": dict(TRIANGLE, crs=NAD27)},
    dict(TRIANGLE, crs=NAD27),
    {"type": "GeometryCollection", "crs": NAD27, "geometries": [TRIANGLE]},
    {"type": "GeometryCollection", "geometries": [dict(TRIANGLE, crs=NAD27)]},
    {"type": "GeometryCollection", "geometries": [{"type": "GeometryCollection",
                                                   "geometries": [dict(TRIANGLE, crs=NAD27)]}]},
    {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {
            "type": "GeometryCollection", "geometries": [dict(TRIANGLE, crs=_named("EPSG:3857"))]}}]},
    {"type": "GeometryCollection", "geometries": None},
    {"type": "GeometryCollection", "geometries": [None]},
]


@pytest.mark.parametrize("data", NESTED_CRS)
def test_non_wgs84_crs_rejected_at_every_level(data):
    with pytest.raises(ValueError):
        hex_grid(data, 300)


def test_wgs84_crs_on_nested_geometry_accepted():
    gc = {"type": "GeometryCollection", "geometries": [dict(TRIANGLE, crs=_named("EPSG:4326"))]}
    assert hex_grid({"type": "Feature", "properties": {}, "geometry": gc}, 300) == hex_grid(TRIANGLE, 300)


def test_cli_version_flag(capsys):
    from hexgrid_maker import __version__
    from hexgrid_maker.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"hexgrid-maker {__version__}"


def test_cli_stdout_is_one_feature_collection(capsys):
    import json
    from hexgrid_maker.cli import main

    # Eiffel Tower area (lon, lat order)
    assert main(["--bbox", "2.29", "48.85", "2.30", "48.86", "--size", "300"]) == 0
    out = capsys.readouterr()
    data = json.loads(out.out)
    assert data["type"] == "FeatureCollection" and data["features"]
    assert out.err == ""


@pytest.mark.parametrize("orientation", ["flat", "pointy"])
def test_cells_tile_without_overlap_and_neighbours_are_equidistant(orientation):
    """Interior cells have six neighbours sqrt(3)*s (geodesic) away and do not overlap them."""
    s = 200
    grid = hex_grid((2.28, 48.84, 2.32, 48.87), s, orientation)  # central Paris, lon/lat
    polys = [shape(f["geometry"]) for f in grid["features"]]
    centres = [p.centroid for p in polys]
    geod = Geod(ellps="WGS84")
    step = math.sqrt(3) * s
    interior = 0
    for i, p in enumerate(polys):
        # Vertices are projected independently, so shared edges only match to ~1e-10 degrees:
        # find neighbours by centre distance rather than by intersection.
        near = []
        for j, c in enumerate(centres):
            if j != i and geod.inv(centres[i].x, centres[i].y, c.x, c.y)[2] < 1.2 * step:
                near.append(j)
        if len(near) < 6:
            continue  # edge of the grid
        assert len(near) == 6
        interior += 1
        for j in near:
            dist = geod.inv(centres[i].x, centres[i].y, centres[j].x, centres[j].y)[2]
            assert dist == pytest.approx(step, rel=0.005)
            overlap = geod.geometry_area_perimeter(p.intersection(polys[j]))[0]
            assert abs(overlap) < 1.0  # m^2, against a cell of about 104,000 m^2
    assert interior > 10
