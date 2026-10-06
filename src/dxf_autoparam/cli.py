"""Command line.

    dxf-autoparam analyse  drawing.dxf [--domain bridge] [--view N | --region x0,y0,x1,y1] [--json model.json]
    dxf-autoparam regen    drawing.dxf --set OpenX1=4000 [--set ...] -o out.dxf [--domain bridge]
    dxf-autoparam views    drawing.dxf
    dxf-autoparam bench    [fixtures/library] [--domain bridge]
    dxf-autoparam serve    [drawing.dxf] [--domain bridge] [--port 8765]

Sizes on the command line are millimetres; levels are metres.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import describe
from .dxf_read import read_dxf
from .dxf_write import audit, write_dxf
from .pipeline import autoparametrize, save_model, validate
from .regen import regenerate
from .views import detect_views


def _region(s: str | None):
    return tuple(float(v) for v in s.split(",")) if s else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dxf-autoparam", description="Existing DXF → parametric model → regenerated DXF")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("analyse", "regen"):
        p = sub.add_parser(name)
        p.add_argument("dxf")
        p.add_argument("--domain", choices=["bridge"], default=None)
        p.add_argument("--view", type=int, default=None)
        p.add_argument("--region", default=None)
        if name == "analyse":
            p.add_argument("--json", default=None, help="write the parametric IR here")
            p.add_argument("--validate", action="store_true")
        else:
            p.add_argument("--set", action="append", default=[], help="NAME=VALUE (mm, levels in m)")
            p.add_argument("-o", "--out", required=True)
    p = sub.add_parser("views")
    p.add_argument("dxf")
    p = sub.add_parser("bench")
    p.add_argument("fixtures", nargs="?", default="fixtures/library")
    p.add_argument("--domain", choices=["bridge"], default=None)
    p = sub.add_parser("serve")
    p.add_argument("dxf", nargs="?")
    p.add_argument("--domain", choices=["bridge"], default=None)
    p.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)

    if a.cmd == "views":
        dr, _ = read_dxf(a.dxf)
        for v in detect_views(dr):
            print(f"view {v['id']}: {v['entities']} entities, bbox {', '.join(f'{c:.0f}' for c in v['bbox'])}")
        return 0
    if a.cmd == "bench":
        from .bench import run

        run(Path(a.fixtures), domain=a.domain)
        return 0
    if a.cmd == "serve":
        from .server import serve

        serve(a.dxf, a.domain, port=a.port)
        return 0

    model = autoparametrize(a.dxf, domain=a.domain, view=a.view, region=_region(a.region))
    if a.cmd == "analyse":
        print(describe(model))
        if a.validate:
            v = validate(model)
            print(f"VALIDATION: identity {v['identity_max_error']:.1e}; {v['regenerate_ok']}/{v['parameters']} values regenerate validly at ±10%")
            for r in v["per_parameter"]:
                if not r["ok"]:
                    print(f"  {r['name']}: {r['issues'][0]}")
        if a.json:
            save_model(model, a.json)
            print(f"wrote {a.json}")
        return 0
    # regen
    u = model.analysis.drawing.units_mm
    values: dict[str, float] = {}
    for s in a.set:
        name, _, raw = s.partition("=")
        if name not in model.parameters:
            print(f"no value called {name}; values: {', '.join(model.parameters)}", file=sys.stderr)
            return 2
        p = model.parameters[name]
        values[name] = float(raw) if p.kind in ("level", "position") else float(raw) / u
    reg = regenerate(model, values)
    if reg.issues:
        print("REFUSED — the drawing would break:", *reg.issues, sep="\n  ", file=sys.stderr)
        return 1
    rep = write_dxf(model, reg, a.out)
    print(json.dumps({"written": a.out, **rep, "audit": audit(a.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
