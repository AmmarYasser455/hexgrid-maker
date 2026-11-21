import json
from pathlib import Path

from shapely.geometry import shape

from hexgrid_maker import hex_grid, load_geometry

ROOT = Path(__file__).resolve().parent.parent
PLACES = ROOT / "examples" / "paris_landmarks.geojson"


def test_each_landmark_is_in_a_cell_and_cells_are_500m_hexagons():
    grid = hex_grid(load_geometry(PLACES), 500)
    cells = [shape(f["geometry"]) for f in grid["features"]]
    data = json.loads(PLACES.read_text(encoding="utf-8"))
    for feat in data["features"]:
        pt = shape(feat["geometry"])
        assert any(c.intersects(pt) for c in cells), feat["properties"]["name"]
    # regular hexagon of edge 500 m: 3*sqrt(3)/2 * 500^2 = 649,519 m^2 (UTM scale error < 0.1 %)
    for f in grid["features"]:
        assert abs(f["properties"]["area_m2"] / 649519.05 - 1) < 0.005
    # Paris is in UTM zone 31N, so cells must sit around lon 2.3, lat 48.87 (not swapped)
    minx, miny, maxx, maxy = shape({"type": "GeometryCollection", "geometries": [c.__geo_interface__ for c in cells]}).bounds
    assert 2.2 < minx < maxx < 2.4 and 48.8 < miny < maxy < 48.95


def test_demo_geojson_is_current():
    expected = hex_grid(load_geometry(PLACES), 500)
    actual = json.loads((ROOT / "docs" / "demo.geojson").read_text(encoding="utf-8"))
    assert actual == json.loads(json.dumps(expected))
