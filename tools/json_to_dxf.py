"""Write the library oracle fixtures (JSON from export_library_oracle.ts) as real DXF files.

Each family's BASE geometry becomes an ordinary drawing — closed/open LWPOLYLINEs,
LINEs, CIRCLEs, HATCHes, TEXTs, LEADERs and linear DIMENSIONs on their own layers,
no parametric information at all. The perturbed variants stay as JSON: they are the
ground truth the prototype is scored against, never its input.

    uv run python tools/json_to_dxf.py fixtures/library
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

CENTRE_LAYERS = ("CENTRE", "CENTER", "CL")


def write_family(src: Path, out: Path) -> None:
    data = json.loads(src.read_text())
    g = data["base"]
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4  # millimetres
    msp = doc.modelspace()

    def layer(name: str) -> str:
        if name not in doc.layers:
            lt = "CENTER" if any(k in name.upper() for k in CENTRE_LAYERS) else "Continuous"
            doc.layers.add(name, linetype=lt)
        return name

    for p in g["polylines"]:
        msp.add_lwpolyline(p["pts"], close=p["closed"], dxfattribs={"layer": layer(p["layer"])})
    for ln in g["lines"]:
        msp.add_line(ln["a"], ln["b"], dxfattribs={"layer": layer(ln["layer"])})
    for c in g["circles"]:
        msp.add_circle(c["c"], c["r"], dxfattribs={"layer": layer(c["layer"])})
    for h in g["hatches"]:
        hatch = msp.add_hatch(dxfattribs={"layer": layer("HATCH")})
        hatch.set_pattern_fill("ANSI31", scale=10)
        hatch.paths.add_polyline_path(h["outer"], is_closed=True)
        for hole in h["holes"]:
            hatch.paths.add_polyline_path(hole, is_closed=True)
    for t in g["texts"]:
        msp.add_text(t["text"], height=t["h"], rotation=t["rot"], dxfattribs={"layer": layer("TEXT")}).set_placement(
            t["at"], align=TextEntityAlignment.MIDDLE_CENTER
        )
    for ld in g["leaders"]:
        msp.add_leader(ld["pts"], dxfattribs={"layer": layer("TEXT")})
        if ld["text"].strip():
            msp.add_text(ld["text"], height=ld["h"], dxfattribs={"layer": layer("TEXT")}).set_placement(
                ld["pts"][-1], align=TextEntityAlignment.BOTTOM_LEFT
            )
    for d in g["dims"]:
        (x1, y1), (x2, y2) = d["p1"], d["p2"]
        axis = d["axis"] or ("x" if abs(y2 - y1) < 1e-6 else "y" if abs(x2 - x1) < 1e-6 else None)
        if axis == "x":
            base = (x1, max(y1, y2) + abs(d["offset"]) + 500)
            msp.add_linear_dim(base=base, p1=(x1, y1), p2=(x2, y2), angle=0, dxfattribs={"layer": layer("DIM")}).render()
        elif axis == "y":
            base = (max(x1, x2) + abs(d["offset"]) + 500, y1)
            msp.add_linear_dim(base=base, p1=(x1, y1), p2=(x2, y2), angle=90, dxfattribs={"layer": layer("DIM")}).render()
        else:
            msp.add_aligned_dim(p1=(x1, y1), p2=(x2, y2), distance=500, dxfattribs={"layer": layer("DIM")}).render()
    doc.saveas(out)


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "fixtures/library")
    out_dir = root / "dxf"
    out_dir.mkdir(exist_ok=True)
    for src in sorted(root.glob("*.json")):
        if src.name == "index.json":
            continue
        out = out_dir / (src.stem + ".dxf")
        write_family(src, out)
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
