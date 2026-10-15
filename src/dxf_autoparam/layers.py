"""Layers, colours and existing / proposed work — read from the drawing's OWN evidence, never from a colour convention.

    layer_report(dr, layout)                         per layer: CAD properties, what is on it (types, roles, views,
                                                     words), its character (structure / construction / presentation /
                                                     furniture) and whether it takes part in the geometry analysis
    classify_status(dr, layout, annotations, accepted)
                                                     per entity: existing | proposed | removed | construction |
                                                     alternative | unclassified — with the evidence for each

Evidence, each with a weight (nothing is decided by one weak sign):
  layer name words      "EXIST", "PROP", "DISMANTLE" … in the layer's own name                                  0.6
  a status note         a note saying existing / proposed whose leader or place points at the entity            0.8
  a view title          "HALF SECTION OF PROP. BRIDGE": the view's structure                                     0.4
  the drawing's colours a colour the drawing ITSELF uses for status notes of (nearly) one kind only (learned per
                        drawing: no contrary note, or at least three with no more than 15% contrary)             0.35
  accepted              a person (or the agent, confirmed) said so — kept, with who and why                       1.0
A status needs a score of at least 0.5 and a clear lead over the next; otherwise the entity stays unclassified and
its candidates are listed. A red line is not "proposed" because it is red.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from .annotations import WORDS, text_states
from .ir import Drawing, Role

STATUS = ("existing", "proposed", "removed", "construction", "alternative")
LAYER_WORDS = {"existing": WORDS["status_existing"] + ["EXG", "EXT"], "proposed": WORDS["status_proposed"],
               "removed": WORDS["status_removed"] + ["DEMO"], "construction": ["CONST", "CONSTRUCTION", "REF", "GRID", "AXIS", "CL"],
               "alternative": WORDS["status_alternative"]}
ACI = {1: "#ff0000", 2: "#ffff00", 3: "#00ff00", 4: "#00ffff", 5: "#0000ff", 6: "#ff00ff", 7: "#ffffff", 8: "#808080", 9: "#c0c0c0"}


def _layer_status(name: str) -> tuple[str, str] | None:
    toks = [t for t in re.split(r"[^A-Z0-9]+", name.upper()) if t]
    for status, words in LAYER_WORDS.items():
        for w in words:
            wt = re.sub(r"[^A-Z0-9]", "", w.upper())
            if wt and any(t == wt or (len(wt) >= 4 and t.startswith(wt)) for t in toks):
                return status, w
    return None


def _colour_key(it) -> str:
    st = it.extra.get("style") or {}
    if st.get("fg"):
        return "foreground (ACI 7)"
    return st.get("color") or "?"


def layer_report(dr: Drawing, layout=None) -> list[dict]:
    """Every layer the drawing declares or uses: its CAD properties, what is on it, where, and what it is for."""
    declared = {ly["name"]: ly for ly in (dr.coverage or {}).get("layers", [])}
    by_layer: dict[str, list] = defaultdict(list)
    for it in dr.items:
        by_layer[it.layer].append(it)
    group_of = layout.item_group if layout is not None else {}
    out = []
    for name in sorted(set(declared) | set(by_layer)):
        its = by_layer.get(name, [])
        d = declared.get(name, {})
        types = Counter(it.dxftype for it in its)
        roles = Counter(it.role.value for it in its)
        views = Counter(group_of.get(it.index, "") for it in its)
        colours = Counter(_colour_key(it) for it in its)
        linetypes = Counter((it.extra.get("style") or {}).get("lt", "?") for it in its)
        words = Counter()
        for it in its:
            if it.dxftype in ("TEXT", "MTEXT", "ATTRIB") and it.text:
                for w in re.findall(r"[A-Za-z][A-Za-z.]{2,}", it.text.upper()):
                    words[w.strip(".")] += 1
        n = max(len(its), 1)
        presentation = sum(types.get(t, 0) for t in ("DIMENSION", "TEXT", "MTEXT", "LEADER", "MULTILEADER", "HATCH", "ATTRIB")) / n
        if not its:
            character = "empty"
        elif roles.get("fixed", 0) / n > 0.5:
            character = "furniture"
        elif roles.get("reference", 0) / n > 0.5 or any(k in ("CENTER", "DASHDOT", "PHANTOM", "DIVIDE") for k, v in linetypes.items() if v / n > 0.5):
            character = "construction"
        elif presentation > 0.5:
            character = "presentation"
        elif roles.get("structural", 0) / n > 0.3:
            character = "structure"
        else:
            character = "mixed"
        row = {"name": name, "on": d.get("on", True), "frozen": d.get("frozen", False), "locked": d.get("locked", False), "plot": d.get("plot", True),
               "color": ACI.get(abs(int(d.get("color", 7) or 7)), f"ACI {d.get('color')}"), "linetype": d.get("linetype", "?"),
               "lineweight": d.get("lineweight"), "entities": len(its), "types": dict(types.most_common(8)), "roles": dict(roles),
               "views": {k: v for k, v in views.most_common(10) if k}, "colours_used": dict(colours.most_common(4)),
               "linetypes_used": dict(linetypes.most_common(4)), "words": [w for w, _ in words.most_common(8)],
               "in_analysis": roles.get("structural", 0) + roles.get("reference", 0) > 0, "character": character}
        ls = _layer_status(name)
        if ls:
            row["name_says"] = ls[0]
        out.append(row)
    return out


def classify_status(dr: Drawing, layout=None, annotations: list[dict] | None = None, accepted: list[dict] | None = None) -> dict:
    """Existing / proposed / removed / construction / alternative per entity, from the drawing's own evidence.

    `annotations`: sheet-level annotation records (understanding.sheet_annotations): status notes and where they point.
    `accepted`: decisions kept on the sheet ({"by": "layer"|"colour"|"entities", "key" / "entities", "status", "who", "why"})."""
    scores: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    why: dict[int, list[str]] = defaultdict(list)
    learned: dict[str, dict] = {}

    def add(i: int, status: str, w: float, reason: str) -> None:
        scores[i][status] += w
        if len(why[i]) < 6:
            why[i].append(f"{status} +{w:g}: {reason}")

    # 1. layer names
    for it in dr.items:
        ls = _layer_status(it.layer)
        if ls:
            add(it.index, ls[0], 0.6, f"its layer {it.layer!r} says {ls[1]}")
    # 2. status notes, by what they point at
    colour_votes: dict[str, Counter] = defaultdict(Counter)
    colour_notes: dict[str, list[str]] = defaultdict(list)
    for a in annotations or []:
        st = (a.get("states") or {}).get("status") or text_states(a.get("text", "")).get("status")
        if not st or st not in STATUS:
            continue
        for t in (a.get("targets") or [])[:1]:
            if t.get("index") is not None and a.get("status") == "resolved":
                add(t["index"], st, 0.8, f"the note {a['text'][:50]!r} points at it")
        main = a["items"][0] if a.get("items") else None
        if main is not None and 0 <= main < len(dr.items):
            key = _colour_key(dr.items[main])
            colour_votes[key][st] += 1
            colour_notes[key].append(a["text"][:40])
    # 3. view titles
    if layout is not None:
        for g in layout.groups:
            if g.kind != "view" or not g.name:
                continue
            st = text_states(g.name).get("status")
            if st in STATUS:
                for i in g.items:
                    if dr.items[i].role in (Role.STRUCTURAL, Role.REFERENCE):
                        add(i, st, 0.4, f"its view is titled {g.name[:50]!r}")
    # 4. the drawing's own colour convention (learned, per drawing; foreground ACI 7 carries no convention)
    for key, votes in colour_votes.items():
        if key.startswith("foreground") or not votes:
            continue
        (best, n), *rest = votes.most_common()
        contrary = sum(v for _s, v in rest)
        if (contrary == 0 and n >= 1) or (n >= 3 and contrary <= 0.15 * (n + contrary)):
            learned[key] = {"status": best, "notes": colour_notes[key][:4], "count": n, "contrary": contrary}
    for it in dr.items:
        lk = learned.get(_colour_key(it))
        if lk and it.role in (Role.STRUCTURAL, Role.REFERENCE, Role.ANNOTATION):
            add(it.index, lk["status"], 0.35, f"drawn in {_colour_key(it)}, the colour this drawing writes {lk['status']} notes in ({lk['notes'][0]!r})")
    # 5. what a person accepted
    for dec in accepted or []:
        st = dec.get("status")
        if st not in STATUS:
            continue
        who = f"{dec.get('who', 'person')}: {dec.get('why', 'accepted')}"
        if dec.get("by") == "layer":
            targets = [it.index for it in dr.items if it.layer == dec.get("key")]
        elif dec.get("by") == "colour":
            targets = [it.index for it in dr.items if _colour_key(it) == dec.get("key")]
        else:
            targets = [int(i) for i in dec.get("entities", []) if 0 <= int(i) < len(dr.items)]
        for i in targets:
            add(i, st, 1.0, who)

    entities: dict[int, dict] = {}
    counts: Counter = Counter()
    for i in range(len(dr.items)):
        sc = scores.get(i)
        if not sc:
            counts["unclassified"] += 1
            continue
        ranked = sorted(sc.items(), key=lambda kv: -kv[1])
        best, v = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        if v >= 0.5 and v - second >= 0.2:
            entities[i] = {"status": best, "score": round(v, 2), "evidence": why[i]}
            counts[best] += 1
        else:
            entities[i] = {"status": "unclassified", "candidates": {k: round(s, 2) for k, s in ranked}, "evidence": why[i]}
            counts["unclassified"] += 1
    return {"counts": dict(counts), "entities": entities, "learned_colours": learned,
            "layers_by_name": {it.layer: _layer_status(it.layer)[0] for it in dr.items if _layer_status(it.layer)}}
