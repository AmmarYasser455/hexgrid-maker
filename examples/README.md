# Examples

`paris_landmarks.geojson` – five well-known Paris landmarks (Eiffel Tower, Arc de
Triomphe, Louvre, Notre-Dame, Sacré-Cœur) as WGS 84 points (lon, lat), rounded to
4 decimals (about 10 m). Coordinates are public geographic facts, taken from the
landmarks' published locations (e.g. OpenStreetMap, © OpenStreetMap contributors,
ODbL); they are approximate and meant for demonstration.

`demo.ipynb` walks through the Python API on this file. The demo grid
(`docs/demo.geojson`) is 500 m flat-top cells over the convex hull of the points,
produced by `hexgrid-maker --input examples/paris_landmarks.geojson --size 500`.
