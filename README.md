<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/logo-dark.svg">
    <img src="assets/brand/logo.svg" alt="hexgrid-maker logo" width="112">
  </picture>
</p>

# hexgrid-maker

hexgrid-maker is part of [OpenTerra](https://github.com/AmmarYasser455), a family of open GIS tools. It generates a flat- or pointy-top hexagonal grid over a bounding box or polygon, with the cell size in metres, and writes it as GeoJSON.

Hexagons have equal distance to all six neighbours, which makes them a good choice for binning points and for density maps. Most tools build hex grids in degrees, which gives cells that are stretched away from the equator. Here the grid is laid out in the local WGS 84 / UTM zone (chosen with `pyproj`), so cell sizes are real metres, and each output cell is reprojected to EPSG:4326 and its area measured on the ellipsoid with `pyproj.Geod`.

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/AmmarYasser455/hexgrid-maker/blob/main/examples/demo.ipynb)
· [Demo map](https://ammaryasser455.github.io/hexgrid-maker/)

## Install

```
pip install git+https://github.com/AmmarYasser455/hexgrid-maker
```

Requires Python >= 3.10; dependencies are `pyproj` and `shapely`.

## Command line

Coordinates are EPSG:4326, GeoJSON order: **longitude, latitude**. `--size` is the hexagon edge length in metres (also centre-to-vertex distance).

```
hexgrid-maker --input examples/paris_landmarks.geojson --size 500 -o docs/demo.geojson
# wrote 26 cells to docs/demo.geojson

hexgrid-maker --bbox WEST SOUTH EAST NORTH --size 300 --orientation pointy --clip
```

Options: `--bbox` or `--input FILE` (GeoJSON; polygons are used as they are, points and lines are replaced by their convex hull), `--size`, `--orientation flat|pointy`, `--clip` (cut edge cells to the polygon), `--max-cells`, `-o FILE` (default stdout). `python -m hexgrid_maker` works too.

## Python

```python
from hexgrid_maker import hex_grid, load_geometry

hull = load_geometry("examples/paris_landmarks.geojson")
grid = hex_grid(hull, 500, orientation="flat")
len(grid["features"])          # 26
grid["features"][0]["properties"]
# {'id': 0, 'col': 0, 'row': 1, 'area_m2': 649996.2}

hex_grid((2.29, 48.85, 2.31, 48.865), 100)   # (west, south, east, north) tuple also works
```

`hex_grid` also accepts a GeoJSON mapping (geometry, Feature or FeatureCollection); `from_geojson` turns such a mapping into one shapely geometry. Bad input (wrong type, NaN or infinite numbers, malformed GeoJSON, a non-WGS 84 `crs` member) raises `ValueError`; the CLI reports it and exits with status 2.

A regular hexagon with 500 m edges has an area of 649,519 m²; the geodesic area above differs by under 0.1 % because of the UTM scale factor.

Each feature has `id`, `col`, `row` and `area_m2` (geodesic, WGS 84). Exterior rings are counter-clockwise as in RFC 7946.

## Example data

`examples/paris_landmarks.geojson` holds five real Paris landmarks, see [examples/README.md](examples/README.md). `docs/demo.geojson` is the tool's output for it and is checked by a test.

## Tests

```
pip install -e ".[test]"
pytest
```

## Limitations

- Output is EPSG:4326 only. Cell edges are straight in UTM and stored as straight lon/lat segments between the six projected vertices (a few centimetres of difference at city scale, more for multi-kilometre cells).
- Input edges are treated as straight in lon/lat (RFC 7946) and split into pieces of at most 0.001° before projection, so a bounding box keeps following its parallels and meridians in UTM; very large inputs therefore gain many vertices.
- Input must be WGS 84 longitude/latitude. A legacy GeoJSON `crs` member is accepted only if it names WGS 84 (e.g. `urn:ogc:def:crs:OGC:1.3:CRS84` or `EPSG:4326`); any other declared CRS (such as NAD27, EPSG:4267) on the collection, a Feature, a geometry or a nested GeometryCollection member is rejected, not reprojected.
- Invalid input polygons (e.g. self-intersecting) are repaired with shapely's `make_valid` before use, which may change their intended shape.
- One UTM zone is used, chosen from the centre of the input (inputs crossing the equator use the hemisphere of their centre). Very wide inputs (many degrees across) are distorted at the edges and cell areas drift from the nominal value.
- Inputs crossing the antimeridian (west > east) or outside lon ±180 / lat ±90 are rejected; inputs whose latitude extent leaves the UTM range (80°S–84°N) are rejected, as are inputs so close to lon ±180 that a cell would cross it.
- With `--clip`, cells cut into several pieces by concave or disconnected input are kept as MultiPolygons (area is the sum of the pieces).
- Without `--clip`, cells that merely touch the polygon are included, and the grid origin is the lower-left of the input's bounding box (grids from different inputs do not align).
- Output cell count is capped by `--max-cells` / `max_cells` (default 200,000); separately, the bounding-box lattice examined is capped at 800,000 candidate cells (or 4 × `max_cells` if larger), so very thin diagonal shapes with tiny cells can be rejected early. The whole grid is held in memory.
- Mixed input is flattened (multipart geometries and nested GeometryCollections alike): polygons are kept with their holes, and all points and lines together are replaced by one convex hull of their vertices, which is added to the polygons. A single point or a collinear set gives a point or line hull, which yields cells only where it falls (and none with `--clip`). `--clip` drops line or point fragments where a cell only touches the polygon.

MIT licensed, see [LICENSE](LICENSE).
