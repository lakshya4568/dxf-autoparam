"""The domain pack a run may be given: a vocabulary for ONE kind of structure — concept names, structure families with their parts, documented
formulas — and the drafting guide that goes with it. It is OFF by default.

Without a pack the model names parts, values and levels the way a designer of THIS drawing would, from what it sees: nothing in the engine, the
prompts or the tools asks for a particular name, a family or a structure type. A pack is a person's choice for a run (`options.domain`) or for the
process (`AUTOPARAM_DOMAIN`); it only offers names and guidance, the engine never depends on it.

    pack = active("bridge")      # the pack's content, or None when no pack is on
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from importlib import resources

NOT_PACKS = {"drafting"}  # knowledge files that are drafting conventions of any sheet, not a domain


def available() -> list[str]:
    return sorted(p.name[:-5] for p in resources.files("dxf_autoparam.knowledge").iterdir() if p.name.endswith(".json") and p.name[:-5] not in NOT_PACKS)


def name_of(name: str | None = None) -> str | None:
    """The pack asked for (an explicit name, else the process's), if it exists."""
    name = (name or os.environ.get("AUTOPARAM_DOMAIN") or "").strip().lower()
    return name if name in available() else None


@lru_cache(maxsize=8)
def _load(name: str) -> dict:
    return json.loads(resources.files("dxf_autoparam.knowledge").joinpath(f"{name}.json").read_text())


def active(name: str | None = None) -> dict | None:
    n = name_of(name)
    return {**_load(n), "name": n} if n else None


def concept_names(pack: dict | None) -> str:
    return ", ".join(sorted({c["name"] for c in pack["concepts"]})) if pack else ""


def families(pack: dict | None) -> list:
    return [[f["id"], f["label"], [x for x in f["components"] if x]] for f in pack["families"]] if pack else []


def search(pack: dict | None, queries: list[str] | str | None, query: str = "") -> list[str]:
    """The pack's concepts, formulas and families matching the words — what the model's `knowledge` tool answers when a pack is on."""
    if pack is None:
        return ["no domain pack is on for this run: name things the way a designer of this drawing would, from what it shows (PascalCase)"]
    if isinstance(queries, str):
        queries = [queries]
    words = [w for w in re.findall(r"[a-z]+", " ".join([*(queries or []), query]).lower()) if len(w) > 2]
    hits = []
    for c in pack["concepts"]:
        hay = " ".join([c["name"], c["label"], *c.get("aliases", [])]).lower()
        if any(w in hay for w in words):
            hits.append(f"{c['name']} ({c['unit'] or '-'}): {c['label']}")
    for f in pack["formulas"]:
        if any(w in f["output"].lower() or w in f["expression"].lower() for w in words):
            hits.append(f"formula {f['output']} = {f['expression']}")
    for f in pack["families"]:
        if any(w in (f["id"] + " " + f["label"]).lower() for w in words):
            hits.append(f"family {f['id']}: components {', '.join(x for x in f['components'] if x)}")
    return list(dict.fromkeys(hits))[:30] or ["nothing matches; use a clear PascalCase name"]


def guide(pack: dict | None) -> str:
    """The pack's drafting guide for the model's system prompt (empty without a pack)."""
    if not pack or not pack.get("guide"):
        return ""
    return ("DOMAIN PACK (on for this run: " + pack["name"] + ") — names and guidance for one kind of structure. They are offered, not required: use a name "
            "when it is what the drawing shows, otherwise name the thing the way its designer would.\n" + pack["guide"] + "\n"
            "The OVERVIEW lists the pack's concept names and structure families with their parts; `knowledge` searches them.\n")


def knowledge_text(pack: dict | None) -> str:
    """The pack as the one-shot prompt's KNOWLEDGE block (without a pack: a line that says so)."""
    if pack is None:
        return "KNOWLEDGE: no domain pack is on for this run — name parts, values and levels the way a designer of this drawing would, from what it shows."
    concepts = [f"{c['name']} ({c['kind']}, {c['unit'] or '-'}): {c['label']}" + (f" — aka {', '.join(c['aliases'][:3])}" if c["aliases"] else "")
                for c in pack["concepts"]]
    fams = [f"{f['id']}: {f['label']} — components {', '.join(x for x in f['components'] if x)}" for f in pack["families"]]
    formulas = [f"{f['output']} = {f['expression']}" + (f"   [when {f['condition']}]" if f["condition"] else "") for f in pack["formulas"]]
    return ("KNOWLEDGE — concept names (offered, not required):\n" + "\n".join(concepts) + "\n\nFamilies:\n" + "\n".join(fams)
            + "\n\nDocumented formulas (concept ids):\n" + "\n".join(formulas))
