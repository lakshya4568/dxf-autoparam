"""Views drawn in projection, each a local system of its own, linked by what they share — explicitly.

A plan under its elevation shows the same vertical planes; a section beside an elevation, the same levels (crossview.view_links finds them). On a
sheet of LOCAL SYSTEMS (`SheetModel.systems == "views"`, the default) every view is a unit of its own: its own set-out lines, dependency graph,
parameters and frame (frames.py). A change of one view regenerates that view and what is bound to it, and nothing else; the design intent of a view
is tried on that view. What the projection says becomes three explicit things where it used to be one set-out line both views were drawn on:

  FACES      which line of one view is which line of the other: the lines on the link's axis that stand at one sheet coordinate, to the precision
             the link was found with (`counterpart`).
  VALUES     a size one view names between two such faces, or a level on such a line, is the same quantity in the other view: ONE shared value
             bound in both (`SheetModel.share`, source "projection") — never two copies a person could set apart (`bind`).
  ALIGNMENT  after any change, the faces of a shared value stand where their counterparts stand (check PROJECTION, `misaligned`): one view cannot
             grow a span from its left while the other grows it about its centre. A side a person chooses for a shared value is chosen in every view
             drawn in projection with it (`SheetModel.anchor`), and the side the engine derives in one view is the first it tries in the other
             (`preferred`).

A saved sheet whose units were made joined (`systems == "joined"`, before local systems) keeps its units as they were: its work is read as it was made.
Nothing here knows a structure: faces are coordinates, values are what a view names."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .crossview import Binding, SharedParam, SheetModel


def precision(sm: SheetModel) -> float:
    """Two lines of views drawn in projection are one face when they stand this close (sheet units): the grid view_links counts faces on, and the
    step either way it allows."""
    frame = sm.layout.frame or sm.dr.extent
    return 1.5 * max(sm.dr.tol, 1e-4 * max(frame[2] - frame[0], frame[3] - frame[1]), 1e-9)


def links(sm: SheetModel, uid: str) -> list[tuple[dict, str]]:
    """The projection links taken between this unit's view(s) and another unit's: (the link, the other unit). Empty on a joined sheet, where a link
    made the two views one unit."""
    if getattr(sm, "systems", "views") != "views" or uid not in sm.units:
        return []
    u = sm.units[uid]
    out = []
    for lk in sm.links:
        if not sm.is_linked(lk):
            continue
        for mine, other in ((lk["a"], lk["b"]), (lk["b"], lk["a"])):
            ou = sm.unit_of_view.get(other)
            if mine in u.views and ou and ou != uid:
                out.append((lk, ou))
    return out


def described(sm: SheetModel, views: list[str] | None = None) -> list[dict]:
    """The projection links (touching these views, or all) as a model or a page reads them: which views, on which axis, how many faces, whether
    the link is taken, and what taking it means on this sheet — one unit (joined), or local systems whose shared values are bound and kept in line."""
    out = []
    for lk in sm.links:
        if views is not None and lk["a"] not in views and lk["b"] not in views:
            continue
        taken = sm.is_linked(lk)
        out.append({"views": [lk["a"], lk["b"]], "axis": lk["axis"], "shared_lines": lk["planes"], "taken": taken,
                    "one_unit": taken and sm.systems == "joined",
                    **({"how": "each view its own local system; a size named between faces both show is ONE shared value in both, and its faces "
                               "stay in line"} if taken and sm.systems == "views" else {})})
    return out


def note_for(sm: SheetModel, uid: str) -> str:
    """One sentence for a model opening this unit: what it is drawn in projection with, and what follows from it."""
    rows = [(lk, other) for lk, other in links(sm, uid)]
    if not rows:
        return ""
    with_ = "; ".join(f"{sm.units[o].views[0]} ({sm.layout.group(sm.units[o].views[0]).name or 'a view'}, {lk['axis']} faces)" for lk, o in rows)
    return (f" It is drawn in projection with {with_}: a size you name here between faces both views show, or a level on such a face, becomes ONE "
            "shared value bound there too, and the faces stay in line — name it once, with its engineering name.")


def link_between(sm: SheetModel, a: str, b: str, axis: str | None = None) -> dict | None:
    """The taken projection link between two units (on this axis), or None."""
    return next((lk for lk, other in links(sm, a) if other == b and (axis is None or lk["axis"] == axis)), None)


def _value(sm: SheetModel, uid: str, line: str) -> float | None:
    """Where a unit's line stands as drawn (sheet units): its analysis as built (a copy of a line split off for one structure stands where the line
    does), else as found."""
    u = sm.units[uid]
    an = sm.analysis(uid)
    d = an.datums.get(line) or (u.orig_datums or {}).get(line)
    return d.value if d is not None else None


def counterpart(sm: SheetModel, other: str, axis: str, at: float, axes: bool = False) -> str | None:
    """The line of another unit that stands at sheet coordinate `at` on `axis` (a face drawn in projection), or None. `axes`: an axis the engine
    found (the centre of a closed outline, a symmetry) counts too — for a centre a size grows about, never for a face."""
    u = sm.units[other]
    an = sm.analysis(other)
    lines = {**(u.orig_datums or {}), **an.datums} if axes else (u.orig_datums or an.datums)
    best = min(((abs(d.value - at), d.id) for d in lines.values() if d.axis == axis and (axes or not d.virtual)), default=None)
    return best[1] if best is not None and best[0] <= precision(sm) else None


def shared_of(sm: SheetModel, uid: str, local: str) -> SharedParam | None:
    return next((p for p in sm.shared.values() if any(b.unit == uid and b.param == local for b in p.bindings)), None)


def _level_line(answer: dict | None, name: str) -> str | None:
    row = next((lv for lv in (answer or {}).get("levels", []) if lv.get("name") == name), None)
    return (row.get("datum") or row.get("line")) if row else None


def ends(sm: SheetModel, b: Binding) -> tuple[str, list[tuple[str, float]]] | None:
    """What a binding sets in its unit, as faces: (axis, [(line, where it stands as drawn)]) — a size's two lines, or a level's one."""
    u = sm.unit(b.unit)
    assert u.prog is not None
    prm = u.prog.params.get(b.param)
    if prm is None:
        return None
    lines = list(prm.measures) if prm.measures else [d for d in [_level_line(u.answer, b.param)] if d] if prm.kind == "level" else []
    an = sm.analysis(b.unit)
    rows = [(d, v) for d in lines if (v := _value(sm, b.unit, d)) is not None]
    if not rows or rows[0][0] not in an.datums:
        return None
    return an.datums[rows[0][0]].axis, rows


def bind(sm: SheetModel, uid: str) -> list[dict]:
    """Every value this unit names on the axis of a projection link — a size between two faces, a level on a face — bound into the unit drawn in
    projection with it, as one shared value. Where the other view already names the size (or the level) it takes the shared name; where it does
    not, the size is bound by its two lines there. A view that cannot take it (the lines there are another size, a name it already uses for
    something else) is said, never forced. Returns what was bound and what was not, one row each."""
    from .crossview import EMPTY_ANSWER, SheetError

    lks = links(sm, uid)
    if not lks:
        return []
    u = sm.unit(uid)
    assert u.prog is not None
    answer = u.answer or {}
    named = {p.get("name") for p in answer.get("parameters", [])} | {lv.get("name") for lv in answer.get("levels", [])}
    out: list[dict] = []
    for name in sorted(n for n in u.prog.params if n in named):
        u = sm.unit(uid)  # each binding rebuilds the units it binds: this one's program is read again, as it is now
        assert u.prog is not None
        prm = u.prog.params.get(name)
        if prm is None or prm.kind not in ("length", "level"):
            continue
        here = ends(sm, _binding(uid, name))
        if here is None:
            continue
        axis, rows = here
        if prm.kind == "length" and len(rows) != 2:
            continue
        for lk, other in lks:
            if lk["axis"] != axis:
                continue
            shared = shared_of(sm, uid, name)
            if shared is not None and any(b.unit == other for b in shared.bindings):
                continue
            there = [counterpart(sm, other, axis, v) for _d, v in rows]
            if None in there or len(set(there)) != len(there):
                continue
            ou = sm.unit(other)
            assert ou.prog is not None
            key = shared.name if shared is not None else name
            row = {"value": key, "from": uid, "into": other, "lines": there, "axis": axis,
                   "why": f"{lk['a']} and {lk['b']} are drawn in projection ({lk['planes']} common {'vertical' if axis == 'x' else 'horizontal'} faces)"}
            try:
                if prm.kind == "level":
                    target = _level_target(sm, other, key, there[0], answer, name, EMPTY_ANSWER)
                else:
                    own = _own_size(sm, other, there)
                    target = (other, own) if own else (other, there[0], there[1])
                    if own and own != key:
                        row["as"] = own
                sm.share(key, ([] if shared is not None else [(uid, name)]) + [target], label=key, evidence=[row["why"]], source="projection")
                row["bound"] = True
            except SheetError as exc:
                row.update(bound=False, why_not=str(exc)[:300])
            out.append(row)
    return out


def _binding(uid: str, name: str) -> Binding:
    from .crossview import Binding

    return Binding(unit=uid, param=name)


def _own_size(sm: SheetModel, other: str, lines: list[str | None]) -> str | None:
    """The name the other unit already gives the size between these lines, if any."""
    ou = sm.unit(other)
    assert ou.prog is not None
    want = sorted(v for v in (_value(sm, other, d) for d in lines if d) if v is not None)
    if len(want) != 2:
        return None
    tol = max(2 * sm.dr.tol, 1e-9)  # the very lines (a copy split off for one structure stands where its line does), never a neighbour
    for n, q in sorted(ou.prog.params.items()):
        if q.kind == "length" and q.measures:
            got = sorted(v for v in (_value(sm, other, d) for d in q.measures) if v is not None)
            if len(got) == 2 and abs(got[0] - want[0]) <= tol and abs(got[1] - want[1]) <= tol:
                return n
    return None


def _level_target(sm: SheetModel, other: str, key: str, line: str | None, answer: dict, name: str, empty: dict) -> tuple[str, str]:
    """A level drawn on a face of both views: the other view's level on that line takes the shared name, or the level is written there (same role)."""
    import copy

    from .crossview import rename_in_answer

    ou = sm.unit(other)
    ans = copy.deepcopy(ou.answer) if ou.answer else copy.deepcopy(empty)
    had = next((lv for lv in ans.get("levels", []) if (lv.get("datum") or lv.get("line")) == line), None)
    role = next((lv.get("role") for lv in answer.get("levels", []) if lv.get("name") == name), "site_input")
    if had is not None and had.get("name") != key:
        ans = rename_in_answer(ans, had["name"], key)
    elif had is None:
        ans.setdefault("levels", []).append({"datum": line, "name": key, "role": role, "reason": "the same level, drawn in projection"})
    if ans != (ou.answer or {}):
        sm.commit_answer(other, ans, intent=False)
    return (other, key)


def faces(sm: SheetModel, ua: str, ub: str, axis: str) -> list[tuple[str, str]]:
    """The faces two units drawn in projection have in common on the link's axis: (line of ua, line of ub) standing at one sheet coordinate —
    each line drawn (not an axis the engine found), once. Kept while neither unit's analysis changes."""
    a_an, b_an = sm.analysis(ua), sm.analysis(ub)
    key = (ua, ub, axis, id(a_an), id(b_an))
    memo = sm.__dict__.setdefault("_projection_faces", {})
    if key not in memo:
        tol = precision(sm)
        mine = sorted((d.value, d.id) for d in (sm.units[ua].orig_datums or a_an.datums).values() if d.axis == axis and not d.virtual)
        theirs = sorted((d.value, d.id) for d in (sm.units[ub].orig_datums or b_an.datums).values() if d.axis == axis and not d.virtual)
        out, j, used = [], 0, set()
        for v, d in mine:  # both sorted along the axis: a merge, not every line against every line
            while j < len(theirs) and theirs[j][0] < v - tol:
                j += 1
            k = j
            best = None
            while k < len(theirs) and theirs[k][0] <= v + tol:
                if theirs[k][1] not in used and (best is None or abs(theirs[k][0] - v) < abs(best[0] - v)):
                    best = theirs[k]
                k += 1
            if best is not None:
                used.add(best[1])
                out.append((d, best[1]))
        memo[key] = out
    return memo[key]


def misaligned(sm: SheetModel, after: dict[str, dict[str, float]]) -> list[dict]:
    """The faces of views drawn in projection that a change no longer keeps in line — one failure per link, naming its first faces and the shared
    values drawn on them. `after`: unit → where its lines stand after the change (sheet units), for the units regenerated; the others stand as
    drawn. A line that stays where it is drawn in either view (a held part, dismantled work, a boundary) is no face of the structure here."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for ua in sorted(after):
        for lk, ub in links(sm, ua):
            key = tuple(sorted((ua, ub)))
            if key in seen or not sm.units[ub].built:
                continue
            seen.add(key)
            a, b = key
            pa, pb = sm.unit(a).prog, sm.unit(b).prog
            assert pa is not None and pb is not None
            um = sm.units[a].sub.units_mm or 1.0
            tol = max(0.5 / um, 2 * sm.dr.tol)
            bad = []
            for la, lb in faces(sm, a, b, lk["axis"]):
                if pa.origin.get(la) == "held" or pb.origin.get(lb) == "held":
                    continue
                va, vb = _value(sm, a, la), _value(sm, b, lb)
                if va is None or vb is None:
                    continue
                na, nb = after.get(a, {}).get(la, va), after.get(b, {}).get(lb, vb)
                if abs((na - va) - (nb - vb)) > tol:  # how far each moves: as drawn they coincide only to the drawing's precision
                    bad.append((la, lb, (na - va) * um, (nb - vb) * um))
            if not bad:
                continue
            va_, vb_ = sm.units[a].views[0], sm.units[b].views[0]
            lines = {x for la, lb, _m1, _m2 in bad for x in ((a, la), (b, lb))}
            values = sorted({p.name for p in sm.shared.values() for bd in p.bindings if (bd.unit, bd.param) in {(u, n) for u, n in _params_on(sm, lines)}})
            shown = "; ".join(f"{va_}'s {la} {m1:+.0f} mm, {vb_}'s {lb} {m2:+.0f} mm" for la, lb, m1, m2 in bad[:3])
            out.append({"check": "PROJECTION", "unit": b, "value": values[0] if values else "", "values": values, "lines": [bad[0][0], bad[0][1]],
                        "units": [a, b], "faces": len(bad), "moves_mm": [round(bad[0][2], 1), round(bad[0][3], 1)],
                        "message": f"{va_} and {vb_} are drawn in projection, and the change no longer keeps {len(bad)} of their common faces in line "
                                   f"({shown}{' …' if len(bad) > 3 else ''}): the two views take it differently"
                                   + (f" — one side for {', '.join(values[:3])} in both" if values else " — what moves in one view must move in the other")})
    return out


def _params_on(sm: SheetModel, lines: set[tuple[str, str]]) -> list[tuple[str, str]]:
    """(unit, value) of the values measured on any of these (unit, line) faces."""
    out = []
    for uid in {u for u, _l in lines}:
        prog = sm.unit(uid).prog
        assert prog is not None
        mine = {ln for u, ln in lines if u == uid}
        out += [(uid, n) for n, q in prog.params.items() if q.measures and set(q.measures) & mine]
    return out


def preferred(sm: SheetModel, uid: str) -> dict[str, dict[str, Any]]:
    """For the design intent of this unit: the side each value it shares by projection already has in the other view — a plan there, a person's or
    the engine's — mapped to this view's lines ({local name: {policy, centre, view, members}}), with the faces that view moves with it (`members`:
    their counterparts here, which the side tried here moves too). Tried first here: drawn in projection, the views grow alike."""
    from . import design_intent
    from .assembly import MID, rates

    out: dict[str, dict[str, Any]] = {}
    for p in sm.shared.values():
        mine = next((b for b in p.bindings if b.unit == uid), None)
        if mine is None:
            continue
        for b in p.bindings:
            if b.unit == uid or link_between(sm, uid, b.unit) is None:
                continue
            ou = sm.units.get(b.unit)
            if ou is None or not ou.answer:
                continue
            here = ends(sm, b)
            if here is None or sm.unit(b.unit).prog is None:
                continue
            moving = rates(sm.unit(b.unit).prog, b.param)
            plan = next((x for x in ou.answer.get("plans", []) if x.get("status") == "accepted" and (x.get("driver") or {}).get("parameter") == b.param
                         and (x.get("anchor") or {}).get("policy") in ("start_fixed", "end_fixed", "centered")), None)
            if plan is not None:
                policy, centre, person = plan["anchor"]["policy"], plan["anchor"].get("centre"), not design_intent.derived(plan)
            else:  # no plan there (its side undecided): the side its own set-out gives it, read off how its two lines move
                (la, _va), (lb, _vb) = sorted(here[1], key=lambda r: r[1]) if len(here[1]) == 2 else (here[1][0], here[1][0])
                ra, rb = moving.get(la, 0.0), moving.get(lb, 0.0)
                policy = ("start_fixed" if abs(ra) < 1e-9 and abs(rb - 1) < 1e-6 else "end_fixed" if abs(rb) < 1e-9 and abs(ra + 1) < 1e-6
                          else "centered" if abs(ra + 0.5) < 1e-6 and abs(rb - 0.5) < 1e-6 else None)
                if policy is None:
                    continue
                centre, person = (MID if policy == "centered" else None), False
            if centre and centre != MID:
                at = _value(sm, b.unit, centre)
                axis = sm.analysis(b.unit).datums[centre].axis if centre in sm.analysis(b.unit).datums else None
                centre = counterpart(sm, uid, axis, at, axes=True) if at is not None and axis else None
                if centre is None:
                    continue  # its centre line has no counterpart here: this view decides for itself
            members = sorted({mine_line for theirs, mine_line in faces(sm, b.unit, uid, here[0]) if abs(moving.get(theirs, 0.0)) > 1e-9})
            out[mine.param] = {"policy": policy, "centre": centre, "view": ou.views[0], "person": person, "members": members}
    return out
