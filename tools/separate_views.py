"""Make a project saved with joined units (a section and its plan analysed as one unit, before local systems) into local systems, each view its own
unit, its work carried over (src/dxf_autoparam/separate.py). Reads a COPY of the project and writes a NEW one; the joined project is never written.

    uv run python -I tools/separate_views.py "<drawing>.dxf" <copy of the project> --out <new project> [--report report.json] [--domain bridge]

Read the report before opening the new project: what each view took, what was refused and why, what was shared again, what was not carried.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dxf")
    ap.add_argument("project", help="a COPY of the joined project (never the autosave a server is using)")
    ap.add_argument("--out", required=True, help="the new project to write (must not exist)")
    ap.add_argument("--report", default=None)
    ap.add_argument("--domain", default=None, help="the domain pack the replay's tool calls see (bridge), as a run with the library on")
    a = ap.parse_args(argv)
    from dxf_autoparam.crossview import SheetModel
    from dxf_autoparam.separate import separate

    out = Path(a.out)
    if out.exists():
        print(f"{out} exists: choose a new file", file=sys.stderr)
        return 2
    t = time.time()
    old = SheetModel.load(a.project, dxf=a.dxf)
    pack = None
    if a.domain:
        from dxf_autoparam.ai import domain as D

        pack = D.active(a.domain)
    new, report = separate(old, pack)
    new.save(str(out))
    report["seconds"] = round(time.time() - t, 1)
    text = json.dumps(report, indent=1, default=str)
    if a.report:
        Path(a.report).write_text(text)
    print(text[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
