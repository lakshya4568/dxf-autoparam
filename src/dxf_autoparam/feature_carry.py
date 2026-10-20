"""Carrying a sheet's decisions over to its derived drawing (feature.py): the new revision keeps every NAME the old one had.

A parametrization names set-out lines, regions and equal sizes by ids that belong to ONE analysis (x12, R7, c3, g41). The derived drawing is
analysed afresh, so every id is re-found, not copied: each old entity maps to the entity that is now that one (the original, which stayed, moved or
was stretched) and, for a repeated instance, to its copy — and a line, a region or a size is found again through the entities it was made of.

    old datum   →  the new lines its points now lie on (the originals, and per copy the copy's)
    old gap     →  the new gaps between those lines that measure the same
    old region  →  the new region sharing most of its boundary entities (the copy, when it is the copy's)

A part, size or level that cannot be found again is a REFUSAL of the whole operation, said with its name; so is a decision that is written in
terms the engine cannot translate (formulas over lines, accepted plans, shared sizes). Nothing is guessed and nothing is half-kept.
"""

from __future__ import annotations

import copy
from collections import Counter, defaultdict

from .dxf_read import read_dxf
from .feature import AXIS, BAND, FIXED, LEFT, MAX_REFUSALS, PARTIAL, RIGHT, STRETCH, FeatureRefused, Operation, _classify, instances
from .regen import regenerate_program
from .topology import of as topology_of


class PlanBlock(str):
    """A refusal only a person can lift: accepted plans cannot be carried to another count, and may be dropped."""


def carry(sm, op: Operation, derived) -> tuple[object, list[str]]:
    """The sheet of the derived drawing with the old sheet's state carried over, validated — or FeatureRefused. Reads `sm`, builds a new model."""
    base = op.base
    new_dr, _ = read_dxf(derived.path)
    src = {it.src: it.index for it in new_dr.items}
    img: dict[int, int] = {}  # the sheet's entity → the entity it is now
    cps: dict[int, list[int]] = {}  # → its copies, in order
    problems: list[str] = []
    dead = set(derived.deleted)
    for it in base.dr.items:
        if it.index in dead or it.anchor in dead:
            continue
        k = src.get(it.src)
        if k is None:
            problems.append(f"{it.dxftype} {it.src} is not in the derived drawing")
            continue
        img[it.index] = k
    for b, handles in derived.copies.items():
        its = [base.dr.items[b]] + [o for o in base.dr.items if o.anchor == b]
        for j, h in enumerate(handles):
            for it in its:
                k = src.get(h + it.src[len(base.dr.items[b].handle):])
                if k is None:
                    problems.append(f"the copy of {it.dxftype} {it.src} is not in the derived drawing")
                    continue
                cps.setdefault(it.index, [None] * len(handles))[j] = k
    ncopy = sum(len(v) for v in cps.values())
    if problems or len(new_dr.items) != len(img) + ncopy:
        raise FeatureRefused((problems or [f"the derived drawing holds {len(new_dr.items)} entities, {len(img)} + {ncopy} were expected"])[:MAX_REFUSALS])
    if any(None in v for v in cps.values()):
        raise FeatureRefused("a copy could not be found again in the derived drawing")
    new, notes = _assemble(sm, new_dr, img, cps, op)
    _check_count(new, _unit_of(sm, new, op.uid, img), op)
    return new, notes


class Identity:
    """The operation that changes nothing: what carries a sheet whose values were changed over to the drawing they make."""

    mode, delta, shift, lo, hi, tol, ax, cut = "identity", 0, 0.0, 0.0, 0.0, 0.0, 0, "left"

    def __init__(self, request: dict):
        self.request = request


def bake(sm, work, request: dict) -> object:
    """The same sheet, its changed values written into the drawing: the regenerated drawing as a DXF, re-imported, the parametrization carried over by
    name. A new model, not adopted — the first half of a feature operation on a sheet whose values were changed."""
    path = str(work / "values.dxf")
    rep = sm.export(path)
    if rep.get("errors"):
        raise FeatureRefused([f"the drawing with its current values does not hold: {e}" for e in rep["errors"][:3]])
    if rep.get("dimension_render_failed") or rep.get("blocks_exploded") or rep.get("arrays_not_reshaped"):
        raise FeatureRefused("writing the current values out would reshape a block reference or a dimension it cannot re-draw: reset those values first")
    new_dr, _ = read_dxf(path)
    src = {it.src: it.index for it in new_dr.items}
    img = {}
    for it in sm.dr.items:
        k = src.get(it.src)
        if k is None:
            raise FeatureRefused(f"cannot trace {it.dxftype} {it.src} through the regenerated drawing: undo the value changes first")
        img[it.index] = k
    if len(img) != len(new_dr.items):
        raise FeatureRefused("the regenerated drawing holds other entities than the sheet")
    new, _notes = _assemble(sm, new_dr, img, {}, Identity(request))
    return new


def _unit_of(sm, new, uid: str, img: dict[int, int]) -> str:
    votes = Counter(new.unit_of_view.get(new.layout.item_group.get(img[s])) for s in sm.units[uid].items if s in img)
    votes.pop(None, None)
    return votes.most_common(1)[0][0]


def _assemble(sm, new_dr, img: dict[int, int], cps: dict[int, list[int]], op) -> tuple[object, list[str]]:
    """The new model for `new_dr` (which `img` / `cps` relate entity by entity to the sheet's), with the sheet's state carried over."""
    from .crossview import SheetModel

    new = SheetModel(new_dr)
    notes: list[str] = []
    gmap = _match_views(sm, new, img)
    for og in sm.layout.groups:
        ng = next(g for g in new.layout.groups if g.id == gmap[og.id])
        ng.name, ng.view_type, ng.kind = og.name, og.view_type, og.kind
        ng.evidence = list(og.evidence)
    if sm.shared:
        raise FeatureRefused("the sheet shares sizes between views (" + ", ".join(p.name for p in sm.shared.values()) + "): carrying a shared size over "
                             "to a drawing with another count is not done — unshare it first")
    ident = all(a == b for a, b in gmap.items())
    if not ident and (sm.relations or sm.stated_plan or sm.questions):
        raise FeatureRefused("the views got other names in the derived drawing while the sheet holds relations or a stated plan about them")
    new.unlinked = {(gmap[a], gmap[b]) for a, b in sm.unlinked}
    new.accepted = {(gmap[a], gmap[b]) for a, b in sm.accepted}
    new.relations, new.stated_plan, new.questions = copy.deepcopy(sm.relations), copy.deepcopy(sm.stated_plan), list(sm.questions)
    new.prefs, new.runs, new.lineage = copy.deepcopy(sm.prefs), list(sm.runs), copy.deepcopy(sm.lineage)
    new._relayout()
    umap = _match_units(sm, new, gmap)

    maps: dict[str, UnitMap] = {}

    def unit_map(uid: str) -> UnitMap:
        if uid not in maps:
            maps[uid] = UnitMap(sm, uid, new, umap[uid], img, cps, op)
        return maps[uid]

    problems: list[str] = []
    for uid, u in sm.units.items():
        if not u.answer:
            continue
        ans, probs, nts = unit_map(uid).translate(u.answer)
        problems += [(PlanBlock if isinstance(p, PlanBlock) else str)(f"{uid}: {p}") for p in probs]
        notes += [f"{uid}: {n}" for n in nts]
        new.units[umap[uid]].answer = ans
        new.units[umap[uid]].prog = None
        if not probs:  # the unit at the new count has its design intent derived as the old one had: what is compared below is like with like
            try:
                new.units[umap[uid]].answer, _found = new._with_intent(umap[uid], ans)
                new.units[umap[uid]].prog = None
            except (KeyError, ValueError, ArithmeticError, AssertionError):
                new.units[umap[uid]].answer, new.units[umap[uid]].prog = ans, None
    if problems:
        blocks = [p for p in problems if isinstance(p, PlanBlock)]
        raise FeatureRefused(problems[:MAX_REFUSALS], question={
            "text": "Accepted plans cannot be carried over to a drawing with another count (their promises name the members of the drawing as it is). "
                    "Drop them — what they changed stays in the drawing — or leave the count?", "options": ["drop_plans", "leave the count"],
            "about": "plans"} if len(blocks) == len(problems) else None)
    for uid, u in sm.units.items():
        if not u.answer:
            continue
        nu = new.unit(umap[uid])
        named = {p["name"] for p in u.answer.get("parameters", [])} | {lv["name"] for lv in u.answer.get("levels", [])}  # the names someone gave
        lost = sorted(named - set(nu.prog.params) - unit_map(uid).dropped)
        problems += [f"{uid}: {m}" for m in _new_errors(u, nu)] + [f"{uid}: the value {n} is not a value of the derived drawing" for n in lost]
    if problems:
        raise FeatureRefused(problems[:MAX_REFUSALS])
    new.domain = [_carry_binding(b, op, unit_map, umap, notes) for b in sm.domain]
    new.values = {}
    r = new.regenerate(units={umap[uid] for uid in sm.units if sm.units[uid].answer} | {b["unit"] for b in new.domain})
    if r.errors:
        raise FeatureRefused([f"the derived drawing does not hold: {e}" for e in r.errors[:MAX_REFUSALS]])
    return new, notes


def _check_count(new, nuid: str, op: Operation) -> None:
    """The derived drawing shows what was asked: the lattice, at the new count."""
    want = int(op.request["count"])
    got = instances(new.pristine_analysis(nuid), op.rep)
    if got != want:
        raise FeatureRefused(f"the derived drawing shows {got} instance(s) of the repeated unit, not {want}")


def _new_errors(old_unit, new_unit) -> list[str]:
    old = {(e["code"], e["item"]) for e in (old_unit.report.errors() if old_unit.report else [])}
    return [f"{e['item']}: {e['message']}" for e in (new_unit.report.errors() if new_unit.report else []) if (e["code"], e["item"]) not in old][:4]


# ── views and units ──────────────────────────────────────────────────────────────


def _match_views(sm, new, img: dict[int, int]) -> dict[str, str]:
    gmap: dict[str, str] = {}
    for og in sm.layout.groups:
        votes = Counter(new.layout.item_group.get(img[s]) for s in og.items if s in img)
        votes.pop(None, None)
        if not votes:
            raise FeatureRefused(f"view {og.id} has nothing left in the derived drawing")
        gid, n = votes.most_common(1)[0]
        if n < 0.9 * sum(votes.values()):
            raise FeatureRefused(f"view {og.id} would be split by the derived drawing's own reading of the sheet")
        gmap[og.id] = gid
    unmatched = [g for g in new.layout.groups if g.id not in set(gmap.values())]
    if len(set(gmap.values())) != len(gmap) or unmatched:
        raise FeatureRefused("the derived drawing reads as other views than the original (a view merged, split or appeared: "
                             + (", ".join(f"{g.kind} {g.id} of {len(g.items)} entit(ies)" for g in unmatched[:3]) or "two views became one") + ")")
    return gmap


def _match_units(sm, new, gmap: dict[str, str]) -> dict[str, str]:
    umap: dict[str, str] = {}
    for uid, u in sm.units.items():
        mine = {new.unit_of_view.get(gmap[v]) for v in u.views}
        if len(mine) != 1 or None in mine:
            raise FeatureRefused(f"the views of {uid} are no longer one unit in the derived drawing")
        umap[uid] = mine.pop()
    if len(set(umap.values())) != len(umap):
        raise FeatureRefused("two units of the sheet became one in the derived drawing")
    return umap


# ── one unit's ids, found again ──────────────────────────────────────────────────


class UnitMap:
    """Old ids of one unit → new ids, through the entities they were made of."""

    def __init__(self, sm, uid: str, new, nuid: str, img: dict[int, int], cps: dict[int, list[int]], op):
        self.uid, self.nuid, self.op = uid, nuid, op
        uo = self.uo = sm.unit(uid)
        self.un = new.unit(nuid)
        self.ao, self.an = sm.pristine_analysis(uid), new.pristine_analysis(nuid)
        self.um = uo.sub.units_mm
        self.tol_mm = max(0.5, 2 * self.ao.drawing.tol * self.um)
        self.img, self.cps = img, cps
        self.new_local = {s: k for k, s in enumerate(self.un.back)}
        self.ncopy = op.delta if op.mode == "insert" else 0
        self.slots_of: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
        for (i, k, a), (d, _off) in self.ao.slot_datum.items():
            self.slots_of[d].append((i, k, a))
        self.cur = regenerate_program(uo.prog, sm._values_for(uo, {}), check=False).datum  # the lines where they stand NOW (values changed or not)
        self.pair_gaps: dict[frozenset, list[str]] = defaultdict(list)
        for gid, g in self.an.gaps.items():
            self.pair_gaps[frozenset((g.a, g.b))].append(gid)
        self.dropped: set[str] = set()
        self._votes: dict[tuple, Counter] = {}

    # lines

    def votes(self, d: str, j: int | None = None) -> Counter:
        key = (d, j)
        if key in self._votes:
            return self._votes[key]
        out: Counter = Counter()
        for i, k, a in self.slots_of.get(d, ()):
            s = self.uo.back[i]
            if j is None:
                t = self.img.get(s)
            else:
                t = self.cps[s][j] if s in self.cps else None
            li = self.new_local.get(t) if t is not None else None
            sd = self.an.slot_datum.get((li, k, a)) if li is not None else None
            if sd:
                out[sd[0]] += 1
        self._votes[key] = out
        return out

    def line(self, d: str) -> str | None:
        v = self.votes(d)
        return v.most_common(1)[0][0] if v else None

    def pair(self, a: str, b: str, value_now: float) -> tuple[str, str] | None:
        """The two new lines a size between (a, b) is measured between now: the originals' images whose distance is the old one — or the old one
        grown by the operation (an overall size)."""
        A, B = self.votes(a), self.votes(b)
        best, score = None, None
        want = [value_now, value_now + self.op.shift]  # unchanged — or grown (shrunk) by what the operation inserted (removed) across it
        for a2, na in A.items():
            for b2, nb in B.items():
                if self.an.datums[a2].axis != self.an.datums[b2].axis or a2 == b2:
                    continue
                v = abs(self.an.datums[b2].value - self.an.datums[a2].value)
                s = (min(abs(v - w) for w in want), -(na * nb))
                if score is None or s < score:
                    best, score = (a2, b2), s
        if best is None or score[0] > self.tol_mm / self.um:
            return None
        return best

    # sizes

    def gap_images(self, g, j: int | None) -> list[str]:
        v_now = abs(self.cur[g.b] - self.cur[g.a])
        out = []
        for a2 in self.votes(g.a, j):
            for b2 in self.votes(g.b, j):
                for gid in self.pair_gaps.get(frozenset((a2, b2)), ()):
                    ng = self.an.gaps[gid]
                    if ng.kind == g.kind and abs(ng.value - v_now) * self.um <= self.tol_mm:
                        out.append(gid)
        return list(dict.fromkeys(out))

    # regions

    def region_images(self, rid: str) -> tuple[str | None, list[str | None]]:
        """The region a region is now (None: it is gone) and, per copy, its copy. By the boundary entities where they say it exactly, else by where
        the operation puts its box."""
        ro = {r.id: r for r in topology_of(self.ao).regions}[rid]
        new_regions = topology_of(self.an).regions

        def local(s: int | None) -> int | None:
            return self.new_local.get(s) if s is not None else None

        def exact(target: set[int]) -> str | None:
            hit = [r.id for r in new_regions if r.items == target]
            return hit[0] if len(hit) == 1 else None

        def near(where: tuple[float, float, float, float], target: set[int]) -> str | None:
            t = 2 * self.ao.drawing.tol
            hit = [r for r in new_regions if all(abs(a - b) <= t for a, b in zip(r.bbox, where, strict=True))]
            if len(hit) > 1:
                top = sorted(hit, key=lambda r: -len(r.items & target))
                if len(top[0].items & target) == len(top[1].items & target):
                    raise FeatureRefused(f"region {rid} is found again as more than one region of the derived drawing")
                hit = top[:1]
            return hit[0].id if hit else None

        orig_t = {local(self.img.get(self.uo.back[i])) for i in ro.items}
        orig = exact(orig_t - {None}) if None not in orig_t else None
        none: list[str | None] = [None] * self.ncopy
        copies: list[str | None] = []
        op = self.op
        if op.mode == "identity":
            return orig, none
        a, b = ro.bbox[op.ax], ro.bbox[op.ax + 2]
        kind = _classify(a, b, op.lo, op.hi, op.tol)
        if kind == PARTIAL:
            raise FeatureRefused(f"region {rid} lies across the edge of the repeated unit")

        def placed(d: float, grow: float = 0.0) -> tuple[float, float, float, float]:
            x0, y0, x1, y1 = ro.bbox
            return (x0 + d, y0, x1 + d + grow, y1) if op.ax == 0 else (x0, y0 + d, x1, y1 + d + grow)

        P = op.rep.pitch
        if kind == LEFT:
            return orig or near(placed(0), orig_t - {None}), none
        if kind == RIGHT:
            return orig or near(placed(op.shift), orig_t - {None}), none
        if kind == STRETCH:
            return orig or near(placed(0, op.shift), orig_t - {None}), none
        if op.mode == "remove":
            return None, none
        own = op.shift if op.cut == "left" else 0.0
        orig = orig or near(placed(own), orig_t - {None})
        for j in range(op.delta):
            copies.append(near(placed((0 if op.cut == "left" else P) + j * P), set()))
        return orig, copies

    # the answer

    def translate(self, answer: dict) -> tuple[dict, list[str], list[str]]:
        from .design_intent import strip

        # the plans the engine derived (design intent) are not promises anybody made: the new count gets its own, derived again when the answer
        # is committed — only a person's plans stand in the way of a change of count
        answer = strip(answer)
        out = copy.deepcopy(answer)
        probs: list[str] = []
        notes: list[str] = []
        for key, why in (("datum_formulas", "formulas over set-out lines"), ("constraints", "constraints over set-out lines")):
            if answer.get(key):
                probs.append(f"the parametrization holds {why}, written for the old count: remove them, or leave the count")
        if answer.get("plans"):
            ids = ", ".join(p.get("id", "?") for p in answer["plans"])
            if self.op.request.get("drop_plans"):
                out["plans"] = []
                notes.append(f"accepted plan(s) {ids} are dropped: their promises name the members of the drawing at the old count (what they changed stays in the drawing)")
            else:
                probs.append(PlanBlock(f"accepted plan(s) {ids} hold promises about the members and lines of the drawing at the old count"))
        if probs:
            return out, probs, notes
        names_gone: set[str] = set()
        # parts
        comps, copied = [], defaultdict(dict)  # j → old name → new name
        found: dict[str, list] = {}
        for c in answer.get("components", []):
            if c.get("entities") or c.get("outlines") or c.get("datums"):
                probs.append(f"part {c['name']} is made of entities or lines by id, not by region: it cannot be found again")
                continue
            if not c.get("regions"):
                comps.append(c)
                continue
            imgs = found[c["name"]] = [self.region_images(r) for r in c["regions"]]
            keep = [o for o, _cs in imgs if o]
            if not keep:
                names_gone.add(c["name"])
                notes.append(f"part {c['name']} is gone with the removed instance")
                continue
            if len(keep) != len(imgs):
                probs.append(f"part {c['name']} loses some of its regions in the derived drawing: it would change meaning")
                continue
            comps.append({**c, "regions": keep})
            for j in range(self.ncopy):
                cs = [cs_[j] for _o, cs_ in imgs]
                if all(cs):
                    copied[j][c["name"]] = f"{c['name']}Copy{j + 1}"
        for j in range(self.ncopy):
            for c in answer.get("components", []):
                if c["name"] in copied[j]:
                    regions = [cs_[j] for _o, cs_ in found[c["name"]]]
                    comps.append({**c, "name": copied[j][c["name"]], "regions": regions, "parent": copied[j].get(c.get("parent"), c.get("parent")),
                                  "description": (c.get("description") or "") + " (added by a change of count)"})
        for c in comps:
            if c.get("parent") in names_gone:
                c["parent"] = None
        out["components"] = comps
        # sizes
        params, copies_of_param = [], []
        for p in answer.get("parameters", []):
            q, why = self._param(p)
            if why:
                probs.append(why)
            elif q is None:
                self.dropped.add(p["name"])
                notes.append(f"{p['name']} measured only what was removed: it is dropped")
            else:
                params.append(q)
                copies_of_param.append(p["name"])
        out["parameters"] = params
        # levels, line roles, relations
        levels = []
        for lv in answer.get("levels", []):
            d = self.line(lv["datum"])
            if d is None:
                probs.append(f"level {lv['name']}: its line is not found again")
            else:
                levels.append({**lv, "datum": d})
        out["levels"] = levels
        roles = []
        for lr in answer.get("line_roles", []):
            d = self.line(lr["datum"])
            if d is not None and lr.get("component") not in names_gone:
                roles.append({**lr, "datum": d})
        out["line_roles"] = roles
        rels = []
        for r in answer.get("relations", []):
            r2 = dict(r)
            if r.get("from_datum") and r.get("to_datum"):
                pr = self.pair(r["from_datum"], r["to_datum"], abs(self.cur[r["to_datum"]] - self.cur[r["from_datum"]]))
                if pr is None:
                    probs.append(f"relation {r['name']}: its lines are not found again")
                    continue
                r2["from_datum"], r2["to_datum"] = pr
            rels.append(r2)
        out["relations"] = rels
        gone = self.dropped | names_gone
        if gone:
            import re

            word = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(map(re.escape, gone)) + r")(?![A-Za-z0-9_])")
            for r in rels:
                if word.search(r.get("expr", "")):
                    probs.append(f"relation {r['name']} uses {word.search(r['expr']).group(1)}, which the change removes")
            for b in answer.get("behaviours", []):
                b["effects"] = [e for e in b.get("effects", []) if e.get("target") not in gone]
            out["behaviours"] = [b for b in answer.get("behaviours", []) if b.get("parameter") not in gone and b.get("effects")]
        return out, probs[:MAX_REFUSALS], notes

    def _param(self, p: dict) -> tuple[dict | None, str]:
        name = p["name"]
        if p.get("candidate"):
            c = self.ao.clusters.get(p["candidate"])
            if c is None:
                return None, f"{name}: candidate {p['candidate']} is not in the analysis"
            occ = c.gaps if p.get("occurrences") in (None, "all") else list(p["occurrences"])
            new_ids: list[str] = []
            for gid in occ:
                g = self.ao.gaps[gid]
                new_ids += self.gap_images(g, None)
                for j in range(self.ncopy):
                    new_ids += self.gap_images(g, j)
            new_ids = list(dict.fromkeys(new_ids))
            if not new_ids:
                return (None, "") if self.op.mode == "remove" else (None, f"{name}: none of its sizes is found again in the derived drawing")
            clusters = {self.an.gaps[g].cluster for g in new_ids}
            if len(clusters) != 1 or None in clusters:
                return None, f"{name}: its equal sizes are no longer one value in the derived drawing ({sorted(map(str, clusters))})"
            cid = clusters.pop()
            cl = self.an.clusters[cid]
            every = set(new_ids) == set(cl.gaps)
            return {**p, "candidate": cid, "occurrences": "all" if every else new_ids, "value": cl.value * self.um}, ""
        a, b = p.get("from_datum"), p.get("to_datum")
        if not (a and b):
            return None, f"{name}: measured between no lines"
        pr = self.pair(a, b, abs(self.cur[b] - self.cur[a]))
        if pr is None:
            return (None, "") if self.op.mode == "remove" and not self.votes(a) or not self.votes(b) else (None, f"{name}: the lines {a}–{b} are not found again")
        v = abs(self.an.datums[pr[1]].value - self.an.datums[pr[0]].value) * self.um
        return {**p, "from_datum": pr[0], "to_datum": pr[1], "value": v}, ""


# ── production bindings ──────────────────────────────────────────────────────────


def _carry_binding(b: dict, op, unit_map, umap: dict[str, str], notes: list[str]) -> dict:
    out = copy.deepcopy(b)
    uid = b["unit"]
    if uid not in umap:
        raise FeatureRefused(f"production binding {b.get('id')} reads unit {uid}, which the derived drawing does not have")
    out["unit"] = umap[uid]
    for section in ("inputs", "outputs"):
        for field, ref in b.get(section, {}).items():
            if not isinstance(ref, dict):
                continue
            ru = ref.get("unit", uid)
            if ru not in umap:
                raise FeatureRefused(f"production binding {b.get('id')}: {field} reads unit {ru}, which the derived drawing does not have")
            um = unit_map(ru)
            new = dict(ref)
            if "unit" in ref:
                new["unit"] = umap[ru]
            if "lines" in ref:
                a, c = ref["lines"]
                pr = um.pair(a, c, abs(um.cur[c] - um.cur[a]))
                if pr is None:
                    raise FeatureRefused(f"production binding {b.get('id')}: {field} is measured between {a} and {c}, which are not found again")
                new["lines"] = list(pr)
            if "line" in ref:
                d = um.line(str(ref["line"]))
                if d is None:
                    raise FeatureRefused(f"production binding {b.get('id')}: {field} is the line {ref['line']}, which is not found again")
                new["line"] = d
            out[section][field] = new
    req = op.request
    if req.get("binding") == b.get("id") and req.get("field"):
        cfg = out.setdefault("config", {})
        if req["field"] not in cfg:
            raise FeatureRefused(f"production binding {b.get('id')} does not state {req['field']}: the count the drawing shows cannot be tied to a field of it")
        n, m = op.rep.count, int(req["count"])
        cfg[req["field"]] = {"value": m, "basis": f"{m} instance(s) drawn after the change of count {n} → {m} (a feature operation on {op.rep.id}, pitch {op.rep.pitch:g})"}
        notes.append(f"{b.get('id')}: {req['field']} is now {m}")
    return out


__all__ = ["AXIS", "BAND", "FIXED", "UnitMap", "carry"]
