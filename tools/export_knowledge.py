"""Compile the aagento-bridge engineering knowledge (read-only) into the compact pack the AI reads.

    uv run python tools/export_knowledge.py ../aagento-bridge/knowledge
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def pascal(s: str) -> str:
    return "".join(w.capitalize() for w in s.replace("-", "_").split("_") if w)


def main() -> None:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "../aagento-bridge/knowledge")
    concepts = json.loads((src / "concepts.json").read_text())["concepts"]
    families = json.loads((src / "families.json").read_text())["families"]
    formulas = json.loads((src / "formulas.json").read_text())["formulas"]
    pack = {
        "source": "aagento-bridge/knowledge (concepts, families, formulas) — compiled by tools/export_knowledge.py",
        "naming": "Parameter names are PascalCase forms of concept ids (clear_span → ClearSpan); levels end in Level and are metres.",
        "concepts": [
            {"name": pascal(c["id"]), "id": c["id"], "kind": c.get("kind"), "unit": c.get("unit"), "label": c.get("label"),
             "aliases": c.get("aliases", [])[:6], "definition": (c.get("definition") or "")[:160]}
            for c in concepts
        ],
        "families": [
            {"id": f["id"], "label": f.get("label"), "components": [x.get("concept") for x in f.get("components", [])]}
            for f in families
        ],
        "formulas": [
            {"output": pascal(f["output"]), "expression": f.get("expression"), "condition": (f.get("condition") or "")[:160],
             "families": f.get("families", []), "status": f.get("status")}
            for f in formulas if f.get("expression")
        ],
    }
    out = Path(__file__).resolve().parents[1] / "src" / "dxf_autoparam" / "knowledge" / "bridge.json"
    out.write_text(json.dumps(pack, indent=1))
    print(f"wrote {out}: {len(pack['concepts'])} concepts, {len(pack['families'])} families, {len(pack['formulas'])} formulas")


if __name__ == "__main__":
    main()
