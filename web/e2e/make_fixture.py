"""The e2e's drawing: a generated two-cell RCC box GAD with its known parametrization committed (no model call), saved as a
DXF and a project file that `dxf-autoparam serve DXF --project PROJECT` opens.

    uv run python web/e2e/make_fixture.py OUT_DIR   → prints the DXF and project paths as JSON
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dxf_autoparam.plan_bench import Box
from dxf_autoparam.production.bench import _sheet


def main(out: str) -> None:
    d = Path(out)
    d.mkdir(parents=True, exist_ok=True)
    sm, us, _up, g = _sheet(Box(cells=2), d, "e2e_box")
    proj = d / "e2e_box.autoparam.json"
    sm.save(str(proj))
    print(json.dumps({"dxf": g["path"], "project": str(proj), "unit": us}))


if __name__ == "__main__":
    main(sys.argv[1])
