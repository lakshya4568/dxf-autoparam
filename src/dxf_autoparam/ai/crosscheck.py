"""What the sheet's views state side by side, and arithmetic over what it states — the read tools that let an agent say, with evidence, whether
two views show the same thing, and where they disagree.

    search_drawing(sm, words, numbers, kinds, limit)   where words and numbers are stated on the whole sheet: notes, dimensions, levels, titles, and the
                                                       parts and values already named
    compare_views(sm, units, focus)                    what several views state alike (a level, a size, the same words), what they state differently,
                                                       and which dimensions run between two stated levels
    calculate(expression, lookup)                      arithmetic over named values and levels, in mm, by the engine's own safe evaluator

Everything is read from the engine's own reading of the sheet (`understanding.sheet_annotations`, each unit's stated levels): nothing here decides that
two things are one. It is the evidence a model weighs, and says — equal numbers alone are not proof of one size (a sheet states 400 for several members),
the same words with two numbers are a finding to report, and a size that equals the difference of two stated levels is a relation to look at.
Words are the drawing's own, weighted by how sparingly the sheet uses them: no vocabulary is built in. A dimension that a named value of its unit already
measures says so (`value`, and `shared_as` when a shared value binds it): the evidence names what `share_sizes` takes as a target.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

from ..program import ExprError, evaluate, names_in

WORD = re.compile(r"[A-Za-z]{3,}")
LEVEL_TOL_M = 0.0006  # a level is stated to the millimetre
SIMILAR = 0.85  # how alike (in order, weighted) the words of two notes must be to count as about the same thing
NOTE_KINDS = ("material", "construction_note", "component_label", "general_note")
CAPS = {"levels": 14, "levels_differ": 10, "sizes": 20, "sizes_differ": 10, "between_levels": 16}
MAX_COMPARED = 500  # statements of one kind compared word by word (pairwise): a sheet that prints more is narrowed with `units` / `focus`, and told so


# ── words ──────────────────────────────────────────────────────────────────────────


def words_of(text: str) -> list[str]:
    """The drawing's own words in a note: three letters or more, upper case, in order, once each."""
    return list(dict.fromkeys(w.upper() for w in WORD.findall(text or "")))


def same_word(a: str, b: str) -> bool:
    """Two printed words are one word: equal, or one is the clipped form of the other (BOT / BOTT / BOTTOM)."""
    return a == b or (min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a)))


def weights(texts: list[str]) -> dict[str, float]:
    """How much a word says: the sheet's rarer words count for more than the ones it prints everywhere (inverse document frequency)."""
    docs = [set(words_of(t)) for t in texts if t]
    df: dict[str, int] = defaultdict(int)
    for d in docs:
        for w in d:
            df[w] += 1
    n = len(docs)
    return {w: math.log((n + 1) / (c + 1)) + 1.0 for w, c in df.items()}


def similarity(a: list[str], b: list[str], weight: dict[str, float]) -> float:
    """How alike two notes' words are, in order (0 when either has none): twice the weight of their longest common run of words over the weight of both.
    Order matters — "TOP OF BOTTOM SLAB" and "BOTTOM OF TOP SLAB" share every word and name two different faces."""
    if not a or not b:
        return 0.0
    w = lambda x: weight.get(x, 1.0)
    best = [[0.0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, x in enumerate(a, 1):
        for j, y in enumerate(b, 1):
            best[i][j] = max(best[i - 1][j], best[i][j - 1], best[i - 1][j - 1] + (w(x) if same_word(x, y) else -1.0))
    total = sum(w(x) for x in a) + sum(w(y) for y in b)
    return 2 * best[-1][-1] / total if total else 0.0


def _cluster(items: list[dict], weight: dict[str, float]) -> list[list[dict]]:
    """Statements about the same thing in different units: those whose words are alike enough, joined transitively."""
    items = items[:MAX_COMPARED]
    parent = list(range(len(items)))

    def find(k: int) -> int:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for i, a in enumerate(items):
        for j in range(i + 1, len(items)):
            b = items[j]
            if a["unit"] != b["unit"] and similarity(a["words"], b["words"], weight) >= SIMILAR:
                parent[find(i)] = find(j)
    groups: dict[int, list[dict]] = defaultdict(list)
    for k, it in enumerate(items):
        groups[find(k)].append(it)
    return [g for g in groups.values() if len({s["unit"] for s in g}) > 1]


# ── what the sheet states ──────────────────────────────────────────────────────────


def _where(s: dict) -> dict:
    return {k: s[k] for k in ("unit", "view", "id", "text", "value", "shared_as") if s.get(k)}


def _named_values(sm) -> tuple[dict, dict]:
    """The sizes already named on the sheet, so that evidence can be acted on: (unit, the two lines a named length measures) → its name, and
    (unit, name) → the shared value that binds it. Only units already built are read (reading the sheet never builds one); a name the analysis
    made up (GapY3, Thk2) is no name."""
    from ..generic import is_generated

    names: dict = {}
    for uid, u in sm.units.items():
        if not u.built:
            continue
        for n, p in u.prog.params.items():
            if p.kind == "length" and p.measures and not is_generated(n):
                names[(uid, frozenset(p.measures))] = n
    shared = {(b.unit, b.param): sp.name for sp in sm.shared.values() for b in sp.bindings}
    return names, shared


def statements(sm, units: list[str] | None = None, focus: str = "") -> dict:
    """Every level, size in a note and dimension the sheet states, as the engine read them: {levels, sizes, dims, weight}. `units` keeps those units
    (and the loose notes of the sheet); `focus` keeps the words and numbers it names."""
    from ..understanding import sheet_annotations

    rows = sheet_annotations(sm)
    weight = weights([r.get("text", "") for r in rows])
    fwords = [w for w in words_of(focus)]
    fnums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", focus or "")]
    levels, sizes, dims = [], [], []
    names, shared = _named_values(sm)
    for r in rows:
        unit = r.get("unit") or "sheet"
        if units and unit not in units and unit != "sheet":
            continue
        st, q = r.get("states") or {}, r.get("quantity") or {}
        base = {"unit": unit, "view": r.get("view") or "", "id": r["id"], "text": " ".join((r.get("text") or "").split())[:80]}
        if r["kind"] == "level" and st.get("level_m") is not None:
            levels.append({**base, "level_m": float(st["level_m"]), "words": words_of(r.get("text", ""))})
        elif r["kind"].startswith("dimension") and q.get("measured_mm") is not None:
            between = list(q.get("between") or [])
            named = names.get((unit, frozenset(between))) if len(between) == 2 else None
            dims.append({**base, "mm": float(q["measured_mm"]), "axis": q.get("axis"), "between": between, "words": [],
                         **({"value": named} if named else {}), **({"shared_as": shared[(unit, named)]} if named and (unit, named) in shared else {})})
        elif r["kind"] in NOTE_KINDS and "slope_h_per_v" not in st:
            nums = {round(float(x), 3) for x in st.get("numbers") or []}
            value = st.get("thickness_mm")
            if value is None and len(nums) == 1:
                value = next(iter(nums))
            ws = words_of(r.get("text", ""))
            if value is not None and ws:
                sizes.append({**base, "mm": float(value), "words": ws})

    def kept(s: dict, value: float | None) -> bool:
        if not fwords and not fnums:
            return True
        by_word = any(same_word(w, f) for w in s["words"] for f in fwords)
        by_number = value is not None and any(abs(value - x) <= max(0.0006 if s.get("level_m") is not None else 0.5, 1e-3 * abs(x)) for x in fnums)
        return by_word or by_number

    return {"levels": [s for s in levels if kept(s, s["level_m"])], "sizes": [s for s in sizes if kept(s, s["mm"])],
            "dims": [s for s in dims if kept(s, s["mm"])], "all_dims": dims, "all_levels": levels, "weight": weight}


def _distinct(values: list[float], tol) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if not out or abs(v - out[-1]) > tol(v):
            out.append(v)
    return out


def _group_by_value(items: list[dict], key: str, tol) -> list[tuple[float, list[dict]]]:
    out: list[tuple[float, list[dict]]] = []
    for v in _distinct([s[key] for s in items], tol):
        out.append((v, [s for s in items if abs(s[key] - v) <= tol(v)]))
    return out


def _size_tol(v: float) -> float:
    return max(0.5, 1e-3 * abs(v))


def _named(stated: list[dict], texts: int = 8, places: int = 4) -> list[dict]:
    """The same words said in several places, once, with where (what is left out is counted)."""
    by: dict[str, list[str]] = defaultdict(list)
    for s in stated:
        by[s["text"]].append(f"{s['unit']}{'/' + s['view'] if s.get('view') else ''} {s['id']}")
    rows = [{"text": t, "at": at[:places] + ([f"… {len(at) - places} more"] if len(at) > places else [])} for t, at in by.items()]
    return rows[:texts] + ([{"text": f"… {len(rows) - texts} more wordings"}] if len(rows) > texts else [])


def _between_levels(sm, st: dict) -> list[dict]:
    """Vertical dimensions whose two end lines stand at levels the sheet states (in this or another view): a size that IS the difference of two
    stated levels, measured from the dimension's own lines — the strong form of the relation, not an arithmetic coincidence."""
    levels = st["all_levels"]
    if not levels:
        return []
    tol = LEVEL_TOL_M

    def named(rl: float) -> list[dict]:
        return [s for s in levels if abs(s["level_m"] - rl) <= tol]

    groups: dict[tuple[float, float], dict] = {}
    for d in st["dims"]:
        if d["axis"] != "y" or len(d["between"]) != 2 or d["unit"] not in sm.units:
            continue
        an = sm.analysis(d["unit"])
        if not an.stated_levels or any(b not in an.datums for b in d["between"]):
            continue
        um = sm.unit(d["unit"]).sub.units_mm
        rl = sorted((an.datums[b].value * um + an.level_offset_mm) / 1000 for b in d["between"])
        lo, hi = named(rl[0]), named(rl[1])
        if not lo and not hi:
            continue
        g = groups.setdefault((round(rl[0], 3), round(rl[1], 3)), {"mm": round(d["mm"], 3), "lower": {"level_m": round(rl[0], 3), "stated": lo},
                                                                    "upper": {"level_m": round(rl[1], 3), "stated": hi}, "dimensions": []})
        g["dimensions"].append({k: d[k] for k in ("unit", "view", "id", "value", "shared_as") if d.get(k)})
    rows = sorted(groups.values(), key=lambda g: (-(bool(g["lower"]["stated"]) + bool(g["upper"]["stated"])), -len(g["dimensions"]), -g["mm"]))
    return [{"mm": g["mm"], "dimensions": g["dimensions"],
             "lower": {"level_m": g["lower"]["level_m"], "stated_as": _named(g["lower"]["stated"]) or "not stated anywhere"},
             "upper": {"level_m": g["upper"]["level_m"], "stated_as": _named(g["upper"]["stated"]) or "not stated anywhere"}} for g in rows]


def compare_views(sm, units: list[str] | None = None, focus: str = "") -> dict:
    """What the views state alike, what they state differently, and which sizes run between stated levels. Bounded; what is left out is counted."""
    st = statements(sm, units, focus)
    weight = st["weight"]
    out: dict = {"read_this_way": "evidence, not a verdict: equal numbers are not one size, the same words with two numbers are for the person, and "
                                  "nothing here has been bound — share_sizes / set_relation / state_plan do that, after you have looked at the pictures"}
    cut: dict[str, int] = {}

    def cap(name: str, rows: list) -> list:
        if len(rows) > CAPS[name]:
            cut[name] = len(rows) - CAPS[name]
        return rows[: CAPS[name]]

    # levels: one value stated in several views (whatever the words), and the same words stated at different values
    by_level = [(v, g) for v, g in _group_by_value(st["levels"], "level_m", lambda v: LEVEL_TOL_M) if len({s["unit"] for s in g}) > 1]
    out["levels_stated_in_several_views"] = cap("levels", [{"level_m": v, "named": _named(g)} for v, g in
                                                           sorted(by_level, key=lambda x: -len({s['unit'] for s in x[1]}))])
    differing = []
    for g in _cluster(st["levels"], weight):
        vals = _distinct([s["level_m"] for s in g], lambda v: LEVEL_TOL_M)
        if len(vals) > 1:
            differing.append({"as": " / ".join(dict.fromkeys(s["text"] for s in g))[:120],
                              "values_m": [{"level_m": v, "stated": [_where(s) for s in g if abs(s["level_m"] - v) <= LEVEL_TOL_M]} for v in vals]})
    out["levels_stated_differently"] = cap("levels_differ", differing)
    # sizes: dimensions and notes that state the same number in several views, and notes with the same words and different numbers
    pool = [*st["dims"], *st["sizes"]]
    alike = []
    for v, g in _group_by_value(pool, "mm", _size_tol):
        if len({s["unit"] for s in g}) < 2:
            continue
        notes = [s for s in g if s["words"]]
        common = [w for w in (notes[0]["words"] if notes else []) if all(any(same_word(w, x) for x in n["words"]) for n in notes)] if len(notes) > 1 else []
        alike.append({"mm": round(v, 3), "stated_in": sorted({s["unit"] for s in g}), "times": len(g), "words_in_common": common,
                      "as": [_where(s) for s in g[:6]] + ([f"… {len(g) - 6} more"] if len(g) > 6 else [])})
    alike.sort(key=lambda a: (-len(a["words_in_common"]), -len(a["stated_in"]), -a["mm"]))
    out["sizes_stated_in_several_views"] = cap("sizes", alike)
    differing = []
    for g in _cluster(st["sizes"], weight):
        vals = _distinct([s["mm"] for s in g], _size_tol)
        if len(vals) > 1:
            differing.append({"as": " / ".join(dict.fromkeys(s["text"] for s in g))[:120],
                              "values_mm": [{"mm": v, "stated": [_where(s) for s in g if abs(s["mm"] - v) <= _size_tol(v)]} for v in vals]})
    out["sizes_stated_differently"] = cap("sizes_differ", differing)
    out["dimensions_between_stated_levels"] = cap("between_levels", _between_levels(sm, st))
    if cut:
        out["left_out"] = {k: f"{n} more (narrow it with units / focus)" for k, n in cut.items()}
    for kind in ("levels", "sizes"):
        if len(st[kind]) > MAX_COMPARED:
            out.setdefault("left_out", {})[f"{kind}_compared_by_words"] = f"only the first {MAX_COMPARED} of {len(st[kind])} were compared word by word (narrow it with units / focus)"
    out["counted"] = {"levels": len(st["levels"]), "sizes_in_notes": len(st["sizes"]), "dimensions": len(st["dims"])}
    return out


# ── search ─────────────────────────────────────────────────────────────────────────


def _camel_words(name: str) -> list[str]:
    return words_of(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name or "").replace("_", " "))


def search_drawing(sm, words: list[str] | None = None, numbers: list[float] | None = None, kinds: list[str] | None = None, limit: int = 40) -> dict:
    """Where words and numbers are stated on the whole sheet — the notes, dimensions, levels and titles the engine read, the views' names, and the parts
    and values already named — each hit with the unit, the view and the id every other tool takes. A hit matches when it has any of the words (or the
    number); the ones matching most come first."""
    from ..understanding import sheet_annotations

    want = [w for w in (str(x).upper().strip() for x in words or []) if w]
    nums = [float(n) for n in numbers or []]
    if not want and not nums:
        return {"error": "give words and / or numbers to look for", "total": 0, "hits": []}
    kinds_ok = set(kinds or [])

    def score(ws: list[str], value: float | None, tol: float) -> int:
        hit = sum(1 for w in want if any(same_word(w, x) for x in ws))
        hit += sum(1 for n in nums if value is not None and abs(value - n) <= max(tol, 1e-3 * abs(n)))
        return hit

    hits: list[tuple[int, dict]] = []

    def add(kind: str, s: int, row: dict) -> None:
        if s and (not kinds_ok or kind in kinds_ok):
            hits.append((s, {"kind": kind, **row}))

    for r in sheet_annotations(sm):
        st, q = r.get("states") or {}, r.get("quantity") or {}
        text = " ".join((r.get("text") or "").split())
        unit, view = r.get("unit") or "sheet", r.get("view") or ""
        base = {"unit": unit, "view": view, "id": r["id"]}
        if r["kind"].startswith("dimension"):
            if q.get("measured_mm") is not None:
                add("dimension", score([], float(q["measured_mm"]), 0.5), {**base, "mm": round(float(q["measured_mm"]), 3), "axis": q.get("axis")})
            continue
        ws = words_of(text)
        if r["kind"] == "level" and st.get("level_m") is not None:
            add("level", score(ws, float(st["level_m"]), 0.0006), {**base, "text": text[:80], "level_m": float(st["level_m"])})
            continue
        vals = [float(x) for x in st.get("numbers") or []]
        s = score(ws, None, 0.5) + sum(1 for n in nums if any(abs(v - n) <= max(0.5, 1e-3 * abs(n)) for v in vals))
        add("title" if r["kind"] == "view_title" else "note", s, {**base, "text": text[:80], "noted_as": r["kind"]})
    for g in sm.layout.groups:
        if g.kind == "view":
            add("view", score(words_of(g.name), None, 0.5), {"view": g.id, "unit": sm.unit_of_view.get(g.id), "text": g.name[:80]})
    for uid, u in sm.units.items():
        ans = u.answer or {}
        for c in ans.get("components", []):
            add("part", score(_camel_words(c.get("name", "")) + words_of(c.get("type", "")), None, 0.5), {"unit": uid, "part": c.get("name"), "type": c.get("type")})
        for p in ans.get("parameters", []):
            if u.built and p.get("name") in u.prog.params:
                add("value", score(_camel_words(p["name"]), float(u.prog.params[p["name"]].value), 0.5),
                    {"unit": uid, "value": p["name"], "mm": round(float(u.prog.params[p["name"]].value), 3)})
    hits.sort(key=lambda h: -h[0])
    lim = max(1, min(int(limit or 40), 100))
    return {"total": len(hits), "hits": [h for _s, h in hits[:lim]], **({"left_out": f"{len(hits) - lim} more: narrow the words or kinds"} if len(hits) > lim else {}),
            "kinds": "note · title · level · dimension · view · part · value"}


# ── arithmetic ─────────────────────────────────────────────────────────────────────


def calculate(expression: str, lookup) -> dict:
    """An arithmetic expression over named values and levels, in millimetres (a level in metres is taken as millimetres: RL 608.051 m = 608051 mm), by the
    engine's own safe evaluator — numbers, names, + - * / ^, and its functions; nothing else runs. `lookup(name)` → (value, unit) or None."""
    expr = (expression or "").strip()
    if not expr:
        return {"error": "give an expression, e.g. 'TopLevel - RoadLevel'"}
    try:
        names = sorted(names_in(expr))
    except ExprError as exc:
        return {"error": str(exc)}
    scope, terms, missing = {}, {}, []
    for n in names:
        got = lookup(n)
        if got is None:
            missing.append(n)
            continue
        value, unit = got
        mm = float(value) * (1000.0 if unit == "m" else 1.0)
        scope[n] = mm
        terms[n] = {"mm": round(mm, 6), **({"given_as": f"{value:g} m"} if unit == "m" else {})}
    if missing:
        return {"error": f"no value or level named {', '.join(missing)} in the open unit, the units opened so far or the shared values", "terms": terms}
    try:
        v = evaluate(expr, scope)
    except ExprError as exc:
        return {"error": str(exc), "terms": terms}
    return {"expression": expr, "result_mm": round(v, 6), "result_m": round(v / 1000, 6), "terms": terms}
