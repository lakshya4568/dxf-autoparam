"""What the drawing itself calls a part — the labels whose leader points at its own outline — and where the part's name says something else.

A part is the model's hypothesis about what some geometry IS. The drawing often says so in words: a note with its leader on the outline
("HEIGHT GAUGE (AS PER DWG. NO. …)"). When the model's name and every such label have nothing in common, the hypothesis is contradicted by the
drawing's own text — a real run called two height-gauge frames "ToeWalls" with the label readable on the picture it had, and nothing said so.

Only labels whose leader the engine resolved onto an entity count (annotations.py), and the entity is the part's by the engine's own rule for which
part an outline belongs to (assembly.part_entities): text that merely sits inside a region — a name written in an empty cell, pointing elsewhere —
says nothing about that region. Words are compared as words (case, plurals and drafting filler set aside); nothing here knows what any structure is
called."""

from __future__ import annotations

import re

LABEL_KINDS = ("component_label", "construction_note", "material")
# drafting filler and units: words a label carries that say nothing about what the thing is
FILLER = {"the", "of", "as", "per", "and", "for", "with", "to", "be", "by", "on", "in", "at", "or", "is", "are", "all", "any", "see", "refer", "note",
          "notes", "detail", "details", "typ", "typical", "dwg", "drg", "drawing", "no", "nos", "mm", "cm", "m", "thk", "thick", "thickness", "dia",
          "provided", "provide", "suitable", "requirement", "requirements", "site", "required", "existing", "exist", "exg", "proposed", "prop", "new"}
WORD_RE = re.compile(r"[A-Za-z]{3,}")


def words(text: str) -> set[str]:
    """The content words of a label or a name: CamelCase and snake_case split, lower case, plurals as their singular, filler dropped."""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])|_", " ", text or "")
    out = set()
    for w in WORD_RE.findall(spaced):
        w = w.lower()
        if len(w) > 4 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        if w not in FILLER:
            out.add(w)
    return out


def pointed_labels(an) -> dict[int, list[dict]]:
    """entity index → the labels whose leader's tip the engine resolved onto it: [{id, text}]."""
    model = an.cache.get("annotations")
    out: dict[int, list[dict]] = {}
    for a in (model.annotations if model is not None else []):
        if a.kind not in LABEL_KINDS or a.status != "resolved" or not words(a.text or ""):
            continue
        for t in a.targets[:3]:
            if t.kind == "entity" and t.index is not None and t.score >= 0.5:
                out.setdefault(t.index, []).append({"id": a.id, "text": " ".join(a.text.split())[:90]})
    return out


def part_labels(prog, parts: dict, name: str, pointed: dict[int, list[dict]] | None = None) -> list[dict]:
    """The labels pointing at the part's own outline (not its children's)."""
    from ..assembly import part_entities

    pointed = pointed if pointed is not None else pointed_labels(prog.analysis)
    if name not in parts or not pointed:
        return []
    mine = part_entities(prog, {**parts, name: parts[name]}, name)
    for child, p in parts.items():  # a child's outline is the child's
        if p.parent == name and child != name:
            mine -= part_entities(prog, parts, child)
    out, seen = [], set()
    for i in sorted(mine):
        for lab in pointed.get(i, []):
            if lab["id"] not in seen:
                seen.add(lab["id"])
                out.append(lab)
    return out


def conflict(component: dict, labels: list[dict]) -> dict | None:
    """The labels a part's own words share nothing with — None when there is no label, when one agrees, or when the model said why the drawing's
    word does not name it (`label_checked`)."""
    if not labels or (component.get("label_checked") or "").strip():
        return None
    mine = words(component.get("name", "")) | words(component.get("type", "")) | words(component.get("description", ""))
    if not mine or any(words(lab["text"]) & mine for lab in labels):
        return None
    return {"part": component.get("name"), "labels": labels[:3]}


def conflicts(prog, components: list[dict]) -> list[dict]:
    """Every leaf part of a program whose own outline the drawing labels as something its name does not say."""
    parts = prog.intent.get("parts") or {}
    pointed = pointed_labels(prog.analysis)
    if not pointed:
        return []
    out = []
    for c in components or []:
        n = c.get("name")
        if n not in parts or c.get("level") == "assembly" or any(p.parent == n for p in parts.values()):
            continue
        got = conflict(c, part_labels(prog, parts, n, pointed))
        if got:
            out.append(got)
    return out


def sentence(c: dict, uid: str | None = None) -> str:
    labs = "; ".join(f"'{lab['text']}' ({lab['id']})" for lab in c["labels"])
    return (f"{(uid + ' ') if uid else ''}{c['part']}: the drawing's label on its outline says {labs} — not what the part is called. Look closer "
            f"(zoom_view), rename or redefine the part, or keep it with label_checked: why the label does not name it")
