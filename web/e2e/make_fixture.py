"""The e2e's drawing: a generated two-cell RCC box GAD with its known parametrization committed (no model call), saved as a
DXF and a project file that `dxf-autoparam serve DXF --project PROJECT` opens.

    uv run python web/e2e/make_fixture.py OUT_DIR   → prints the DXF and project paths as JSON
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from dxf_autoparam.plan_bench import Box
from dxf_autoparam.production.bench import _sheet


def keep_foundation_as_built(sm, uid: str, g: dict) -> None:
    """The existing foundation is kept as built, and a size is named on it: a reading of existing work, not an input (the page offers to unlock it)."""
    pts = next(it.pts for it in sm.dr.items if it.handle == g["handles"]["Foundation"])
    an, um = sm.unit(uid).an, sm.unit(uid).sub.units_mm
    x0, x1 = min(p[0] for p in pts) * um, max(p[0] for p in pts) * um

    def line(mm: float) -> str:
        return min((d for d in an.datums.values() if d.axis == "x"), key=lambda d: abs(d.value * um - mm)).id

    answer = copy.deepcopy(sm.units[uid].answer)
    for c in answer["components"]:
        if c["name"] == "Foundation":
            c["existing"], c["parametrize"] = True, False
    answer["parameters"].append({"name": "FoundationWidth", "label": "Foundation width", "component": "Foundation", "kind": "length", "from_datum": line(x0),
                                 "to_datum": line(x1), "value": abs(x1 - x0), "recommended": False})
    sm.commit_answer(uid, answer)


def main(out: str) -> None:
    d = Path(out)
    d.mkdir(parents=True, exist_ok=True)
    sm, us, _up, g = _sheet(Box(cells=2), d, "e2e_box")
    keep_foundation_as_built(sm, us, g)
    proj = d / "e2e_box.autoparam.json"
    sm.save(str(proj))
    print(json.dumps({"dxf": g["path"], "project": str(proj), "unit": us}))


if __name__ == "__main__":
    main(sys.argv[1])
