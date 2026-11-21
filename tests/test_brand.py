import re
import xml.etree.ElementTree as ET
from pathlib import Path

BRAND = Path(__file__).resolve().parent.parent / "assets" / "brand"
ORANGE = "#F2552C"
FILES = {"logo.svg": "#121417", "logo-dark.svg": "#F3EEE4"}


def test_logos():
    for name, ink in FILES.items():
        path = BRAND / name
        assert path.exists()
        root = ET.parse(path).getroot()
        assert root.get("viewBox") == "0 0 100 100"
        assert root.get("width") == "100" and root.get("height") == "100"
        colours = set(re.findall(r"#[0-9A-Fa-f]{6}\b", path.read_text(encoding="utf-8")))
        assert {c.upper() for c in colours} == {ink.upper(), ORANGE}
