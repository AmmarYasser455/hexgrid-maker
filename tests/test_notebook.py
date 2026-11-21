import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_notebook_runs(monkeypatch):
    monkeypatch.chdir(ROOT)
    nb = json.loads((ROOT / "examples" / "demo.ipynb").read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    ns = {}
    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            assert cell["outputs"] == [] and cell["execution_count"] is None
            exec("".join(cell["source"]), ns)
    assert len(ns["grid"]["features"]) > 0
