"""How the parts of a unit meet, measured on the drawing — and the contacts a change pulls apart.

The contacts are the engine's own observation (`assembly.interfaces`): two parts whose outlines run along the SAME set-out line over a common
stretch meet there (a face), or share a corner. Said from the outline's side of each: across a horizontal line the upper part is ON the lower
one (a slab on a wall, a course on a slab, a slab over an opening); across a vertical one they are BESIDE each other. A face stays met whatever
value moves its line — the joint is the line; it parts only when another line crosses it, which the validity check refuses.

What can come apart is a contact that is not a shared line: entities that touched as drawn — a sloping face against a wall, a detail drawn on a
member — set out from different lines. `torn` finds the ones a change separates (both structural, at least one of them moved, not by the
same offset), so an edit can say "this corner came apart". Generic: nothing here knows a kind of part.

For a part the library names (a component card), what such a part is known to meet (`connects` in the card: on / under / beside another card's
part) is compared with what was measured: met, or not found — a lead for the person or the agent, never a rule.
"""

from __future__ import annotations

from collections import defaultdict

HOW = {"y": "on", "x": "beside"}  # across a horizontal line the upper part is on the lower one; across a vertical one they are side by side


def _sides(prog, parts: dict) -> dict[tuple[str, str], float]:
    """(part, line) → which side of the line the part's material is on (sign), from its own outline as drawn: the edges that leave the corners of
    its edges along that line — not from the part's box (a part of two walls has a box across the whole structure)."""
    an = prog.analysis
    dv = {d.id: d.value for d in an.datums.values()}
    dv.update(prog.datum_values())
    out: dict[tuple[str, str], float] = defaultdict(float)
    for name, p in parts.items():
        nbr: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
        for c1, c2 in p.edges:
            nbr[c1].append(c2)
            nbr[c2].append(c1)
        for (xa, ya), (xb, yb) in p.edges:
            if ya == yb and xa != xb:
                k, line = 1, ya
            elif xa == xb and ya != yb:
                k, line = 0, xa
            else:
                continue
            ends = ((xa, ya), (xb, yb))
            if line in dv:
                out[(name, line)] += sum(dv[q[k]] - dv[line] for c in ends for q in nbr[c] if q not in ends and q[k] in dv)
    return out


def contacts(prog, parts: dict) -> list[dict]:
    """Every pair of leaf parts that meet, as the drawing shows them: across which line and how (`a` is on / beside `b`), or at a shared corner;
    and parts whose entities touch with no line or corner in common (`touches`)."""
    from .assembly import interfaces

    leaves = {n: p for n, p in parts.items() if not any(q.parent == n for q in parts.values())}
    side = _sides(prog, leaves)
    out = []
    for r in interfaces(prog, parts):
        a, b = r["parts"]
        if r["kind"] == "face":
            sa, sb = side.get((a, r["line"]), 0.0), side.get((b, r["line"]), 0.0)
            if sa * sb >= 0:
                continue  # not across the line (both on one side, or an outline that does not say): aligned, not met
            hi, lo = (a, b) if sa > 0 else (b, a)
            out.append({"a": hi, "b": lo, "how": HOW[r["axis"]], "line": r["line"], "mm": r.get("length_mm")})
        else:
            out.append({"a": a, "b": b, "how": "corner", "line": None, "at": r.get("at")})
    joined = {frozenset((r["a"], r["b"])) for r in out}
    try:
        from .coverage import _entity_parts
        from .topology import of

        eparts = _entity_parts(prog)
        touch: set[frozenset] = set()
        for i, js in of(prog.analysis).connections.items():
            for pa in eparts.get(i, ()):
                for j in js:
                    for pb in eparts.get(j, ()):
                        pair = frozenset((pa, pb))
                        if pa != pb and pa in leaves and pb in leaves and pair not in joined:
                            touch.add(pair)
        out += [{"a": a, "b": b, "how": "touches", "line": None} for a, b in (sorted(t) for t in touch)]
    except (KeyError, AttributeError) as exc:  # a unit whose topology cannot be read: the faces and corners are still said
        out.append({"a": None, "b": None, "how": "unread", "line": None, "why": f"{type(exc).__name__}: {exc}"[:120]})
    return sorted(out, key=lambda r: (r["a"] or "", r["b"] or "", r.get("line") or ""))


def meets_of(rows: list[dict], part: str) -> list[dict]:
    """What one part meets, said from its side: `on` B, `under` B (B is on it), `beside` B, at a `corner` of B, `touches` B."""
    out = []
    for r in rows:
        if part not in (r.get("a"), r.get("b")):
            continue
        other = r["b"] if r["a"] == part else r["a"]
        how = "under" if r["how"] == "on" and r["b"] == part else r["how"]
        out.append({"part": other, "how": how, **({"line": r["line"]} if r.get("line") else {}), **({"mm": r["mm"]} if r.get("mm") else {})})
    return out


def expected(meets: list[dict], wants: list[dict], card_of: dict[str, str]) -> list[dict]:
    """A card's `connects` (how a part of its kind meets another kind) against what this part meets: met (with whom), or not found."""
    out = []
    for w in wants:
        hits = [m for m in meets if card_of.get(m["part"]) == w["to"] and m["how"] in (w["how"], "corner", "touches")]
        out.append({"how": w["how"], "to": w["to"], **({"says": w["says"]} if w.get("says") else {}),
                    **({"met": [m["part"] for m in hits][:4]} if hits else {"met": None, "check": "not measured: is that part drawn and defined here, "
                                                                                                   "and does this view show both?"})})
    return out


def dismantled(prog) -> set[int]:
    """The entities of work to be dismantled (a part of type dismantled: the sheet's legend, or a person's choice)."""
    from .assembly import DISMANTLED_TYPE

    return {i for p in (prog.intent.get("parts") or {}).values() if p.type == DISMANTLED_TYPE for i in p.entities}


def torn(prog, pts_after: dict[int, list], limit: int = 6) -> list[dict]:
    """Structural entities of different parts (or of a part and no part) that touched as drawn and do not touch at the regenerated points:
    the corners a change pulled apart. Entities that moved by the same offset, or did not move, are not looked at again."""
    from .coverage import _entity_parts
    from .plan import _touch
    from .topology import of

    an = prog.analysis
    items = an.drawing.items
    tol = an.drawing.tol * 2

    def offset(i: int) -> tuple[float, float] | None:
        """How entity i moved, if it moved rigidly (None: reshaped)."""
        p1, p0 = pts_after.get(i), items[i].pts
        if p1 is None or not p0:
            return (0.0, 0.0)
        if len(p1) != len(p0):
            return None
        dx, dy = p1[0][0] - p0[0][0], p1[0][1] - p0[0][1]
        return (dx, dy) if all(abs(a[0] - b[0] - dx) <= 1e-9 and abs(a[1] - b[1] - dy) <= 1e-9 for a, b in zip(p1, p0, strict=False)) else None

    owner = _entity_parts(prog)
    gone = dismantled(prog)  # work to be dismantled: what it touched as drawn may part from it
    out, seen = [], set()
    for i, js in of(an).connections.items():
        if items[i].role.value != "structural" or i in gone:
            continue
        for j in js:
            if (min(i, j), max(i, j)) in seen or items[j].role.value != "structural" or not (owner.get(i) or owner.get(j)) or j in gone:
                continue
            seen.add((min(i, j), max(i, j)))
            if owner.get(i) and owner.get(j) and owner[i] & owner[j]:
                continue  # one part's own entities: its outline is the validity checks' to answer for
            oi, oj = offset(i), offset(j)
            if oi is not None and oj is not None and abs(oi[0] - oj[0]) <= 1e-9 and abs(oi[1] - oj[1]) <= 1e-9:
                continue  # moved together, or neither moved: they touch as they did
            if not _touch(items[i], pts_after.get(i, items[i].pts), items[j], pts_after.get(j, items[j].pts), tol):
                out.append({"entities": [i, j], "parts": [sorted(owner.get(i, ())) or None, sorted(owner.get(j, ())) or None]})
                if len(out) >= limit:
                    return out
    return out
