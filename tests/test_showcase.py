import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("make_showcase", ROOT / "showcase" / "make_showcase.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_map_geojson_is_current(tmp_path):
    summary = _load().main(tmp_path, png=False)
    fresh = json.loads((tmp_path / "map.geojson").read_text(encoding="utf-8"))
    committed = json.loads((ROOT / "showcase" / "map.geojson").read_text(encoding="utf-8"))
    assert fresh == committed
    assert summary["cells"] == 26 and summary["cells_with_landmark"] == 5
    # Paris: lon about 2.3 (x), lat about 48.87 (y); a swapped axis would fail
    x, y = fresh["features"][0]["geometry"]["coordinates"][0][0]
    assert 2.2 < x < 2.4 and 48.8 < y < 48.95
    assert (tmp_path / "index.html").exists()


def test_png_is_produced(tmp_path):
    pytest.importorskip("matplotlib")
    _load().main(tmp_path)
    png = (tmp_path / "map.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_notebook_executes_with_inline_image(tmp_path):
    nbformat = pytest.importorskip("nbformat")
    nbclient = pytest.importorskip("nbclient")
    pytest.importorskip("matplotlib")
    pytest.importorskip("ipykernel")
    nb = nbformat.read(str(ROOT / "showcase" / "showcase.ipynb"), as_version=4)
    nbclient.NotebookClient(
        nb, timeout=300, kernel_name="python3",
        resources={"metadata": {"path": str(ROOT)}},
    ).execute()
    images = [
        o for c in nb.cells if c.cell_type == "code" for o in c.outputs
        if o.output_type in ("display_data", "execute_result") and "image/png" in o.get("data", {})
    ]
    assert images
    assert not [o for c in nb.cells if c.cell_type == "code"
                for o in c.outputs if o.output_type == "error"]
