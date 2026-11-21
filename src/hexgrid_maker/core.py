"""Hexagonal grid generation.

Input and output coordinates are EPSG:4326 in GeoJSON order (x=longitude,
y=latitude). The grid itself is laid out in metres in a local UTM zone.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import shapely
from pyproj import CRS, Geod, Transformer
from pyproj.aoi import AreaOfInterest
from pyproj.exceptions import ProjError
from pyproj.database import query_utm_crs_info
from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

WGS84 = CRS.from_epsg(4326)
GEOD = Geod(ellps="WGS84")
MAX_CELLS = 200_000
# Safeguard on candidate cells examined (bounding-box lattice), separate from the
# output limit so that small grids are never rejected by a low ``max_cells``.
MAX_CANDIDATES = 4 * MAX_CELLS
# Input edges are straight lines in lon/lat (RFC 7946); they are split into pieces
# of at most this many degrees (about 110 m) before projection so curved
# projected boundaries are followed rather than replaced by chords.
DENSIFY_DEG = 0.001
ORIENTATIONS = ("flat", "pointy")


def utm_crs_for(geom) -> CRS:
    """Return the WGS 84 / UTM CRS whose area of use contains the geometry's centre.

    One zone is used for the whole input; its hemisphere comes from the centre, so
    inputs crossing the equator are allowed as long as their whole latitude
    extent lies inside the combined UTM coverage (north and south zones).
    """
    west, south, east, north = geom.bounds
    lon, lat = (west + east) / 2, (south + north) / 2
    infos = query_utm_crs_info(datum_name="WGS 84", area_of_interest=AreaOfInterest(lon, lat, lon, lat))
    if not infos:
        raise ValueError(f"no UTM zone covers lon={lon:.4f}, lat={lat:.4f} (poles are unsupported)")
    crs = CRS.from_authority(infos[0].auth_name, infos[0].code)
    column = query_utm_crs_info(datum_name="WGS 84", area_of_interest=AreaOfInterest(lon, south, lon, north))
    lo = min(i.area_of_use.south for i in column)
    hi = max(i.area_of_use.north for i in column)
    if south < lo or north > hi:
        raise ValueError(
            f"latitudes {south}..{north} extend outside UTM coverage ({lo}..{hi}); poles are unsupported"
        )
    return crs


def _check_crs(data):
    """Reject a GeoJSON (2008) ``crs`` member unless it names WGS 84 lon/lat."""
    if "crs" not in data:
        return
    member = data["crs"]
    try:
        name = member["properties"]["name"] if member["type"] == "name" else None
        ok = name is not None and CRS.from_user_input(name).equals(WGS84, ignore_axis_order=True)
    except Exception:
        ok = False
    if not ok:
        raise ValueError(f"unsupported GeoJSON crs {member!r}: input must be WGS 84 longitude/latitude "
                         "(reproject it first)")


def _check_geometry_crs(obj):
    """Check ``crs`` on a geometry mapping and, recursively, on GeometryCollection members."""
    if not isinstance(obj, dict) or not isinstance(obj.get("type"), str):
        raise ValueError(f"not a GeoJSON geometry: {obj!r:.80}")
    _check_crs(obj)
    if obj["type"] == "GeometryCollection":
        members = obj.get("geometries")
        if not isinstance(members, list):
            raise ValueError("GeometryCollection 'geometries' must be a list")
        for member in members:
            _check_geometry_crs(member)


def _shape(obj):
    """GeoJSON geometry mapping -> shapely geometry with finite coordinates, or ValueError."""
    _check_geometry_crs(obj)
    try:
        g = shape(obj)
    except Exception as exc:
        raise ValueError(f"bad GeoJSON geometry: {exc}") from exc
    return _finite(g)


def _finite(g):
    """Return ``g`` after checking all its coordinates are finite."""
    if not np.isfinite(shapely.get_coordinates(g)).all():
        raise ValueError("geometry has non-finite (NaN or infinite) coordinates")
    return g


def _atoms(g):
    """Recursively flatten multipart geometries and (nested) collections into single parts."""
    if g.is_empty:
        return []
    if g.geom_type in ("Point", "LineString", "LinearRing", "Polygon"):
        return [g]
    return [a for p in shapely.get_parts(g) for a in _atoms(p)]


def from_geojson(data):
    """GeoJSON mapping (Feature, FeatureCollection or geometry, WGS 84 lon/lat) -> one shapely geometry.

    Polygonal input is unioned; other types (points, lines) are replaced by their
    convex hull so a set of places gives an area to cover.
    """
    if not isinstance(data, dict):
        raise ValueError("GeoJSON must be a JSON object")
    _check_crs(data)
    kind = data.get("type")
    if kind == "FeatureCollection":
        feats = data.get("features")
        if not isinstance(feats, list):
            raise ValueError("FeatureCollection 'features' must be a list")
    elif kind == "Feature":
        feats = [data]
    else:
        feats = [{"type": "Feature", "geometry": data}]
    geoms = []
    for f in feats:
        if not isinstance(f, dict) or f.get("type") != "Feature":
            raise ValueError(f"not a GeoJSON Feature: {f!r:.80}")
        _check_crs(f)
        if f.get("geometry") is not None:
            geoms.append(_shape(f["geometry"]))
    out = _normalize(geoms)
    if out.is_empty:
        raise ValueError("input contains no geometry")
    return out


def _normalize(geoms):
    """Shared path for every input type: list of shapely geometries -> one area to cover.

    Inputs are flattened recursively (multipart and nested collections). Polygons
    are repaired with shapely.make_valid and unioned, keeping holes and
    concavities. All points and lines are replaced by the convex hull of their
    original vertices (taken before any union), which is then added to the
    polygons. Equivalent inputs therefore give the same result regardless of
    representation.
    """
    polys, others = [], []
    for atom in (a for g in geoms for a in _atoms(g)):
        if atom.geom_type != "Polygon":
            others.append(atom)
        elif atom.is_valid:
            polys.append(atom)
        else:
            fixed = _atoms(shapely.make_valid(atom))
            areas = [p for p in fixed if p.geom_type == "Polygon"]
            # A collapsed polygon (no area left) still marks a place: treat it like a line.
            if areas:
                polys.extend(areas)
            else:
                others.extend(fixed)
    parts = list(polys)
    if others:
        parts.append(shapely.GeometryCollection(others).convex_hull)
    if not parts:
        return shapely.GeometryCollection()
    try:
        return unary_union(parts)
    except Exception as exc:
        raise ValueError(f"cannot combine input geometries: {exc}") from exc


def load_geometry(path):
    """Read a UTF-8 GeoJSON file into one shapely geometry (see :func:`from_geojson`)."""
    return from_geojson(json.loads(Path(path).read_text(encoding="utf-8")))


def _number(x, what):
    if isinstance(x, bool) or not isinstance(x, (int, float, np.integer, np.floating)) or not math.isfinite(x):
        raise ValueError(f"{what} must be a finite number, got {x!r}")
    return float(x)


def _as_geometry(geom):
    """Accept a bbox sequence, a GeoJSON mapping or a shapely geometry; return a shapely geometry."""
    if isinstance(geom, (tuple, list)):
        if len(geom) != 4:
            raise ValueError("bbox must be (west, south, east, north)")
        west, south, east, north = (_number(v, "bbox value") for v in geom)
        _check_bounds(west, south, east, north)
        return box(west, south, east, north)
    if isinstance(geom, dict):
        return from_geojson(geom)
    if isinstance(geom, BaseGeometry):
        return _normalize([_finite(geom)])
    raise ValueError(f"geometry must be a bbox, GeoJSON mapping or shapely geometry, got {type(geom).__name__}")


def _reproject(geom, func, densify=None):
    """Apply a pyproj ``Transformer.transform`` (always_xy) to every vertex.

    With ``densify`` (in the source units) edges are first split with
    shapely.segmentize so the transformed boundary follows the curved image of
    each straight source edge.
    """
    if densify:
        geom = shapely.segmentize(geom, densify)
    return shapely.transform(geom, lambda c: np.column_stack(func(c[:, 0], c[:, 1])))


def _cell(cx, cy, s, flat):
    """Hexagon with centre (cx, cy) and edge length s (= centre-to-vertex)."""
    start = 0 if flat else 30
    pts = [
        (cx + s * math.cos(math.radians(start + 60 * i)), cy + s * math.sin(math.radians(start + 60 * i)))
        for i in range(6)
    ]
    return Polygon(pts)


def _check_bounds(west, south, east, north):
    if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
        raise ValueError("bounds must satisfy -180<=west<=east<=180 and -90<=south<=north<=90 "
                         "(antimeridian crossings are not supported)")


def _polygonal(geom):
    """Keep only the polygonal parts of a geometry (None if there is no area)."""
    polys = [p for p in shapely.get_parts(geom) if p.geom_type == "Polygon" and not p.is_empty]
    if not polys:
        return None
    return polys[0] if len(polys) == 1 else MultiPolygon(polys)


def hex_grid(geom, size_m, orientation="flat", clip=False, max_cells=MAX_CELLS):
    """Build a hexagonal grid over a lon/lat geometry, GeoJSON mapping or ``(west, south, east, north)``.

    ``size_m`` is the hexagon edge length in metres (equal to the distance from
    centre to vertex). Cells that intersect the geometry are kept; with
    ``clip=True`` they are cut to it. Returns a GeoJSON FeatureCollection dict
    (RFC 7946: exterior rings counter-clockwise) with ``id``, ``col``, ``row``
    and geodesic ``area_m2`` properties.
    """
    if not isinstance(orientation, str) or orientation not in ORIENTATIONS:
        raise ValueError(f"orientation must be one of {ORIENTATIONS}")
    size_m = _number(size_m, "size_m")
    if size_m <= 0:
        raise ValueError("size_m must be a positive number of metres")
    if not isinstance(clip, bool):
        raise ValueError("clip must be True or False")
    if isinstance(max_cells, bool) or not isinstance(max_cells, int) or max_cells <= 0:
        raise ValueError("max_cells must be a positive integer")
    geom = _as_geometry(geom)
    if geom.is_empty:
        raise ValueError("geometry is empty")
    _check_bounds(*geom.bounds)

    crs = utm_crs_for(geom)
    fwd = Transformer.from_crs(WGS84, crs, always_xy=True).transform
    inv = Transformer.from_crs(crs, WGS84, always_xy=True).transform
    try:
        area = _reproject(geom, fwd, DENSIFY_DEG)
    except ProjError as exc:
        raise ValueError(f"cannot project geometry into {crs.name}: {exc}") from exc
    if not np.isfinite(shapely.get_coordinates(area)).all() or not np.isfinite(area.bounds).all():
        raise ValueError(f"geometry extends outside the usable domain of {crs.name}; "
                         "use a narrower extent (about 6 degrees of longitude)")
    minx, miny, maxx, maxy = area.bounds

    flat = orientation == "flat"
    s = float(size_m)
    h = math.sqrt(3) * s
    # Neighbouring centres: flat-top -> columns 1.5 s apart, rows h apart, odd columns
    # shifted by h/2; pointy-top is the same lattice with x and y swapped.
    along, across = (1.5 * s, h) if flat else (h, 1.5 * s)
    n_col = int((maxx - minx) / along) + 3
    n_row = int((maxy - miny) / across) + 3
    n_candidates = (n_col + 1) * (n_row + 1)
    if n_candidates > max(MAX_CANDIDATES, 4 * max_cells):
        raise ValueError(f"cell size too small: about {n_candidates} candidate cells; "
                         "raise size_m or max_cells")
    shapely.prepare(area)

    features = []
    for col in range(-1, n_col):
        for row in range(-1, n_row):
            if flat:
                cx = minx + col * 1.5 * s
                cy = miny + row * h + (h / 2 if col % 2 else 0)
            else:
                cx = minx + col * h + (h / 2 if row % 2 else 0)
                cy = miny + row * 1.5 * s
            cell = _cell(cx, cy, s, flat)
            if not cell.intersects(area):
                continue
            if clip:
                cell = _polygonal(cell.intersection(area))
                if cell is None:
                    continue
            if len(features) >= max_cells:
                raise ValueError(f"more than {max_cells} cells; raise size_m or max_cells")
            ll = _reproject(cell, inv)
            ll = (MultiPolygon([orient(p, 1.0) for p in ll.geoms]) if ll.geom_type == "MultiPolygon"
                  else orient(ll, 1.0))
            if ll.bounds[2] - ll.bounds[0] > 180 or not -180 <= ll.bounds[0] <= ll.bounds[2] <= 180:
                raise ValueError("grid cells would cross the antimeridian (lon 180); "
                                 "keep the input at least one cell away from it")
            features.append({
                "type": "Feature",
                "id": len(features),
                "properties": {
                    "id": len(features),
                    "col": col,
                    "row": row,
                    "area_m2": round(abs(GEOD.geometry_area_perimeter(ll)[0]), 1),
                },
                "geometry": mapping(ll),
            })
    return {"type": "FeatureCollection", "features": features}
