"""Build the hexgrid-maker showcase from showcase/data/ (offline).

Question: how many 500 m hexagons cover the area spanned by five Paris
landmarks, and which cells hold a landmark?

Run from the repository root:  python showcase/make_showcase.py
Writes map.geojson, map.png and index.html (next to this file by default).
"""

import json
import math
import sys
from pathlib import Path

from pyproj import Geod
from shapely.geometry import shape

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from hexgrid_maker import hex_grid, load_geometry  # noqa: E402

DATA = HERE / "data" / "paris_landmarks.geojson"
SIZE_M = 500
CREDIT = "Landmark positions: OpenStreetMap contributors (ODbL). Grid: hexgrid-maker"
REPO = "https://github.com/AmmarYasser455/hexgrid-maker"
TITLE = "500 m hexagons over five Paris landmarks"


def compute(data_path=DATA, size=SIZE_M):
    """Return (grid FeatureCollection with landmark properties, landmarks list, hull)."""
    hull = load_geometry(data_path)
    grid = hex_grid(hull, size, orientation="flat")
    landmarks = json.loads(Path(data_path).read_text(encoding="utf-8"))["features"]
    points = [(f["properties"]["name"], shape(f["geometry"])) for f in landmarks]
    for feat in grid["features"]:
        cell = shape(feat["geometry"])
        names = [n for n, p in points if cell.covers(p)]
        feat["properties"]["landmarks"] = ", ".join(names)
        feat["properties"]["n_landmarks"] = len(names)
    return grid, points, hull


def summary(grid, hull):
    feats = grid["features"]
    geod = Geod(ellps="WGS84")
    hull_km2 = abs(geod.geometry_area_perimeter(hull)[0]) / 1e6
    return {
        "cells": len(feats),
        "cells_with_landmark": sum(1 for f in feats if f["properties"]["n_landmarks"]),
        "grid_km2": sum(f["properties"]["area_m2"] for f in feats) / 1e6,
        "hull_km2": hull_km2,
    }


def write_png(grid, points, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch, Polygon

    fig, ax = plt.subplots(figsize=(8, 8.4), dpi=150)  # 1200 x 1260 px
    for f in grid["features"]:
        ring = f["geometry"]["coordinates"][0]
        hit = f["properties"]["n_landmarks"] > 0
        ax.add_patch(Polygon(ring, closed=True, fc="#e8833a" if hit else "#dbe9f4",
                             ec="#3b6a8f", lw=0.8, alpha=0.9))
    for name, p in points:
        ax.plot(p.x, p.y, "o", color="#1a1a1a", ms=5)
        ax.annotate(name, (p.x, p.y), xytext=(6, 6), textcoords="offset points", fontsize=9)
    ax.autoscale_view()
    ax.set_aspect(1 / math.cos(math.radians(48.86)))  # display only: 1 deg lon is shorter than 1 deg lat
    ax.set_xlabel("Longitude (deg E, EPSG:4326)")
    ax.set_ylabel("Latitude (deg N, EPSG:4326)")
    ax.set_title(f"{TITLE}\nflat-top cells, {SIZE_M} m edge, grid laid out in UTM 31N", fontsize=12)
    ax.legend(handles=[Patch(fc="#e8833a", ec="#3b6a8f", label="cell with a landmark"),
                       Patch(fc="#dbe9f4", ec="#3b6a8f", label="cell without a landmark")],
              loc="upper left", fontsize=9)
    ax.text(0.99, 0.01, "N ↑ north-up   " + CREDIT, transform=ax.transAxes,
            ha="right", va="bottom", fontsize=6.5, color="#333",
            bbox={"fc": "white", "ec": "none", "alpha": 0.8})
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  body { margin: 0; font-family: system-ui, sans-serif; }
  header { padding: 8px 14px; }
  h1 { font-size: 1.2rem; margin: 0 0 4px; }
  p { margin: 0; font-size: .9rem; }
  #map { height: calc(100vh - 100px); }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <p>Flat-top hexagons of 500 m edge cover the convex hull of the Eiffel Tower, Arc de Triomphe, Louvre, Notre-Dame and Sacre-Coeur. Orange cells hold a landmark; click a cell for its properties.</p>
  <p>Made with <a href="__REPO__">hexgrid-maker</a>. Landmark positions &copy; OpenStreetMap contributors (ODbL).</p>
</header>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var map = L.map('map');
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);
fetch('map.geojson').then(function (r) { return r.json(); }).then(function (data) {
  var layer = L.geoJSON(data, {
    style: function (f) {
      var hit = f.properties.n_landmarks > 0;
      return { color: '#3b6a8f', weight: 1, fillColor: hit ? '#e8833a' : '#dbe9f4', fillOpacity: hit ? 0.7 : 0.4 };
    },
    onEachFeature: function (f, l) {
      var p = f.properties, rows = [];
      for (var k in p) { rows.push('<b>' + k + '</b>: ' + p[k]); }
      l.bindPopup(rows.join('<br>'));
    }
  }).addTo(map);
  map.fitBounds(layer.getBounds());
});
</script>
</body>
</html>
"""


def main(outdir=HERE, png=True):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    grid, points, hull = compute()
    (outdir / "map.geojson").write_text(json.dumps(grid, indent=1) + "\n", encoding="utf-8")
    (outdir / "index.html").write_text(
        HTML.replace("__TITLE__", TITLE).replace("__REPO__", REPO), encoding="utf-8")
    if png:
        write_png(grid, points, outdir / "map.png")
    s = summary(grid, hull)
    print(f"{s['cells']} cells, {s['cells_with_landmark']} with a landmark, "
          f"grid {s['grid_km2']:.2f} km2, hull {s['hull_km2']:.2f} km2")
    return s


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else HERE)
