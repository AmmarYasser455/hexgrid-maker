"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .core import MAX_CELLS, ORIENTATIONS, hex_grid, load_geometry


def build_parser():
    p = argparse.ArgumentParser(
        prog="hexgrid-maker",
        description="Hexagonal grid (GeoJSON, EPSG:4326, lon/lat order) over a bbox or polygon.",
    )
    p.add_argument("--version", action="version", version=f"hexgrid-maker {__version__}")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--bbox", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"),
                     help="bounding box in degrees")
    src.add_argument("--input", metavar="FILE", help="GeoJSON file (non-polygons use their convex hull)")
    p.add_argument("--size", type=float, required=True, help="hexagon edge length in metres")
    p.add_argument("--orientation", choices=ORIENTATIONS, default="flat")
    p.add_argument("--clip", action="store_true", help="cut edge cells to the polygon")
    p.add_argument("--max-cells", type=int, default=MAX_CELLS)
    p.add_argument("-o", "--output", metavar="FILE", help="output file (default: stdout)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        geom = tuple(args.bbox) if args.bbox else load_geometry(args.input)
        grid = hex_grid(geom, args.size, args.orientation, args.clip, args.max_cells)
    except (ValueError, OSError) as exc:
        print(f"hexgrid-maker: error: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(grid)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {len(grid['features'])} cells to {args.output}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
