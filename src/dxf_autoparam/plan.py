"""Instruction-guided, assembly-aware parametrization: what a person asks for, made into a PLAN the engine checks,
compiles into the existing parametric program and proves by measurement.

    plan = build_plan(prog, answer, {"instruction": "Reduce the clear span. Keep the foundation fixed. ..."})
    # a person (or the agent, for what the instruction itself settles) answers plan["questions"] ...
    plan = build_plan(prog, answer, {**request, "decisions": {"Q1": "keep_fixed", "anchor": "centered"}})
    answer = with_plan(answer, plan)          # the plan is stored with the parametrization: saved, undone, redone with it
    prog, rep = validator.apply(an, answer)   # compile_plans + verify_plan run inside; V16 on any broken promise

A plan holds, every id real and every claim checked: the DRIVER (a parameter, the exact occurrences it drives, the
value asked for); the ANCHOR (centered / start_fixed / end_fixed / as_set_out — the evidence for it, and each
alternative with what it would do); the DIRECTIVES (what each part, size, level or line must do, with the different
meanings of "do not change" kept apart); the parts it affects and the parts merely attached to them (each must have an
accepted behaviour); the views, dimensions and notes that follow; the dependency chain in words; the questions only a
person can answer; the conflicts; and the last measurement.

Precedence when things disagree: the current request; then what a person accepted before (held parts, earlier plans);
then existing ownership (formulas a person or the AI set); then the drawing's own sizes and verified relations; then
strong geometric evidence; then hypotheses. A conflict is never settled by overriding a person: it becomes a question.
Nothing here executes text: an instruction is read into ids and modes, and the drawing's notes are never instructions.
"""

from __future__ import annotations

import copy
import math
import os
import re
from functools import lru_cache
from typing import cast

from .ai import domain
from .assembly import (
    MID,
    POLICIES,
    POLICY_WORDS,
    Driver,
    assembly_lines,
    centre_candidates,
    entity_lines,
    interfaces,
    line_values_mm,
    part_entities,
    protected_lines,
    rates,
    stack,
    symmetric_about,
)
from .intent import Part, _depends_on, delta_of, descendants
from .program import ExprError, Program, _num, names_in
from .regen import regenerate_program
from .topology import of

MODES = {
    "parameterize": "becomes (or stays) an editable value",
    "resize": "changes size with the driver",
    "translate": "moves with the driver, keeping its size",
    "follow": "moves with what it is attached to, staying attached",
    "keep_fixed": "stays exactly where it is drawn",
    "keep_value": "its size or value stays the same; it may still move",
    "no_parameter": "gets no editable value of its own; it may still follow",
    "exclude": "outside the edit: no value of its own, no movement, its annotations untouched",
    "preserve": "a relationship stays true (thickness, symmetry, level, connection)",
    "annotations_only": "only its dimensions and notes may change",
    "update_views": "every view, dimension and note showing the change follows",
    "review": "the meaning is unclear: a person decides",
}
FIXED_MODES = ("keep_fixed", "exclude", "annotations_only")
MOVING_MODES = ("resize", "translate", "follow")
RELATIONS = ("thickness", "symmetry", "level", "connection")
PLAN_FORMAT = "dxf-autoparam/plan-1"
MAX_REPAIRS = 3  # bounded: an agent may re-propose a failed plan this many times, then it must ask

# ── reading an instruction ───────────────────────────────────────────────────────

_STOP = {"the", "a", "an", "of", "to", "and", "or", "all", "every", "each", "any", "its", "their", "it", "them", "existing",
         "designated", "main", "both", "this", "that", "these", "those", "new", "current", "same", "drawn", "please", "also",
         "with", "on", "in", "at", "for", "be", "is", "are", "should", "must", "will", "shall", "as", "well", "other"}
_SIZE = {"thickness", "width", "depth", "height", "length", "size", "value", "dimension", "projection", "offset", "cover"}
_NORMAL = {"center": "centre", "centered": "centred", "centerline": "centreline", "thk": "thickness", "lvl": "level",
           "meter": "metre", "meters": "metre", "dim": "dimension", "dims": "dimension"}
_RELWORDS = (("symmetry", r"symmetr|centred|centreline|centre line|center ?line|centerline|axis"),
             ("connection", r"connect|attach|contact"), ("thickness", r"thickness"), ("level", r"\blevel"))
_VERB = (r"(?:maintain|keep|preserve|retain|ensure|resize|update|adjust|do not|don't|dont|never|exclude|ignore|follow|hold|fix|"
         r"leave|param(?:e)?teri[sz]e|parametri[sz]e|make|reduce|decrease|increase|change|set|shrink|enlarge|widen|narrow|grow|move|only|just|when|stretch)")
_NUM = r"(?P<v>\d[\d,]*(?:\.\d+)?)\s*(?P<u>mm|m|%)?"


def _singular(w: str) -> str:
    if len(w) > 4 and w.endswith("nesses"):
        return w[:-2]
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("es") and w[:-2].endswith(("ch", "sh", "ss", "x")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def words(s: str) -> set[str]:
    """The content words of a name or a phrase: CamelCase split, lower case, British spelling, singular."""
    out = set()
    for w in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", s or ""):
        w = _NORMAL.get(w.lower()) or w.lower()
        w = _NORMAL.get(_singular(w), _singular(w))
        if w not in _STOP:
            out.add(w)
    return out


def _concepts(pack_name: str | None = None) -> dict[str, list[frozenset[str]]]:
    """Concept name → its aliases as word sets, from the domain pack when one is on ('FOUNDATION' names a Footing) — none without a pack: the
    names an instruction may use are then the words of this drawing's own parts, values and levels."""
    return _concepts_of(domain.name_of(pack_name))


@lru_cache(maxsize=8)
def _concepts_of(name: str | None) -> dict[str, list[frozenset[str]]]:
    pack = domain.active(name) if name else None
    out: dict[str, list[frozenset[str]]] = {}
    for c in (pack or {}).get("concepts", []):
        al = [frozenset(words(a)) for a in [c.get("label", ""), *c.get("aliases", [])]]
        out[c["name"]] = [a for a in al if a]
    return out


def vocabulary(prog: Program, parts: dict[str, Part] | None = None) -> list[dict]:
    """What an instruction may name on THIS drawing: its parts, its named values and levels, its centre lines — each
    with the words of its name, type and label, and the knowledge pack's aliases for the concept it is."""
    pack_name = domain.name_of()
    fam = (prog.structure or {}).get("family")
    if not pack_name and fam and fam != "other":
        pack_name = next((p for p in domain.available() if any(f[0] == fam for f in domain.families(domain.active(p)))), None)
    concepts = _concepts(pack_name)
    parts = parts if parts is not None else (prog.intent.get("parts") or {})
    comps = {c.name: c for c in prog.components}
    out = []

    def aliases(*names: str) -> list[frozenset[str]]:
        al = []
        for n in names:
            key = "".join(w.capitalize() for w in re.findall(r"[A-Za-z]+", n or "")) if n and not n[:1].isupper() else n
            al += concepts.get(key or "", [])
        return al

    for n, p in parts.items():
        typ = comps[n].type if n in comps else p.type
        out.append({"kind": "part", "name": n, "words": words(n) | words(typ), "core": words(n), "alias": aliases(n, typ),
                    "existing": p.existing})
    void_params = {c.name for c in prog.analysis.clusters.values() if c.name and c.kind.value == "void"}
    for n, q in prog.params.items():
        if q.source == "geometry" and q.kind != "level":
            continue  # a size nobody named is reached through a part or an id, never guessed from words
        kind = "level" if q.kind == "level" else "parameter"
        extra = [frozenset({"opening", "clear"})] if n in void_params else []
        out.append({"kind": kind, "name": n, "words": words(n) | words(q.label), "core": words(n), "alias": aliases(n) + extra})
    an = prog.analysis
    for d in an.datums.values():
        if d.source == "drawn-axis" and d.id in prog.formulas:
            out.append({"kind": "line", "name": d.id, "words": {"centre", "line", "centreline", "axis"}, "core": {"centreline"}, "alias": []})
    return out


_ID = re.compile(r"^(?:x|y|ax)\d+h?$|^R\d+$|^g\d+$|^c\d+$|^[A-Z]{1,5}\d+$")


def resolve(phrase: str, vocab: list[dict], prog: Program | None = None, many_ok: bool = False, prefer: str | None = None) -> dict:
    """A phrase → the objects it names. Every word of the phrase must be in an object's name, type or label (or the
    phrase must be one of the knowledge pack's aliases of the concept it is); several equally good matches are AMBIGUOUS
    — the person said one thing and the drawing has several — unless the phrase is plural."""
    raw = re.sub(r"['’]s\b.*$", "", phrase.strip(" .,;:"))  # "the bottom slab's ends": the slab
    out = {"phrase": raw, "names": [], "kind": None, "how": "", "options": []}
    if prog is not None and _ID.match(raw):
        an = prog.analysis
        kind = ("line" if raw in an.datums else "occurrence" if raw in an.gaps else "candidate" if raw in an.clusters
                else "part" if raw in (prog.intent.get("parts") or {}) else None)
        if kind:
            out.update(names=[raw], kind=kind, how="id")
            return out
    low = raw.lower()
    plural = bool(re.search(r"\b\w+s\b", low)) and any(_singular(w) != w for w in re.findall(r"[a-z]+", low) if w not in ("thickness", "less"))
    W = words(raw)
    if not W:
        return out
    if W & {"connected", "attached", "adjacent"} and not (W - {"connected", "attached", "adjacent", "geometry", "part", "component", "member"}):
        out.update(kind="generic", names=["connected"], how="generic")
        return out
    vague = {"unrelated", "else", "remaining", "rest", "everything", "detail", "geometry", "part", "component", "thing", "member"}
    if W & {"unrelated", "else", "remaining", "rest", "everything"}:
        if not (W - vague):
            out.update(kind="generic", names=["unrelated"], how="generic")
            return out
        W = W - {"unrelated", "else", "remaining", "rest", "everything"}
    if W & {"view", "dimension", "annotation", "note", "label"} and not (W - {"view", "dimension", "annotation", "note", "label", "affected", "corresponding"}):
        out.update(kind="generic", names=["views"], how="generic")
        return out
    W = W - {"connected", "attached", "adjacent"}  # "the connected slabs": how they relate, not what they are called

    def matches(ws: set[str]) -> list[dict]:
        full = [o for o in vocab if ws <= o["words"]]
        al = [o for o in vocab if any(ws == a or (len(a) > 1 and a <= ws) for a in o["alias"])]
        seen, res = set(), []
        for o in full + al:
            if (o["kind"], o["name"]) not in seen:
                seen.add((o["kind"], o["name"]))
                res.append(o)
        return res

    found = matches(W)
    how = "name"
    size = W & _SIZE
    if not found and size and W - _SIZE:  # "slab thickness": the named sizes of the slabs, else the slabs' own thickness
        found = [o for o in matches(W - _SIZE) if o["kind"] == "parameter"]
        how = "named size"
        parts_too = [o for o in matches(W - _SIZE) if o["kind"] == "part"]
        if not found:
            found, how = parts_too, "size of part"
        elif many_ok and parts_too and prefer != "parameter":  # every wall: by its named size, else by its own thickness
            named_words = set().union(*(o["core"] for o in found))
            found += [o for o in parts_too if not (o["core"] - _SIZE) <= named_words]
            how = "named size and parts"
    if not found:  # a phrase that is part of one alias of one named thing ("the opening" of a clear span)
        found = [o for o in vocab if any(len(W) < len(a) and W <= a for a in o["alias"])]
        how = "part of an alias"
        if len(found) != 1:
            found = []
    if not found and re.search(r"\s+of\s+", raw, re.IGNORECASE):  # "the opening of each cell": what it is, else whose
        left, right = re.split(r"\s+of\s+", raw, maxsplit=1, flags=re.IGNORECASE)
        for part in (left, right):
            r = resolve(part, vocab, prog, many_ok, prefer)
            if r["names"] or r["how"] == "ambiguous":
                return {**r, "phrase": raw}
    if not found:
        out["how"] = "nothing on this drawing is called that"
        return out
    if prefer and how != "named size and parts" and any(o["kind"] == prefer for o in found) \
            and len({o["kind"] for o in found}) > 1:  # a part and a value of one name: what the clause does decides
        found = [o for o in found if o["kind"] == prefer]
    exact = [o for o in found if o["core"] == W or (how in ("size of part", "named size") and o["core"] == W - _SIZE)]
    kinds = {o["kind"] for o in found}
    if len(found) == 1:
        pick = found
    elif len(exact) == 1 and not plural:
        pick = exact
    elif (plural or many_ok) and (len(kinds) == 1 or how == "named size and parts"):
        pick, how = found, how if how == "named size and parts" else "plural" if plural else "every one named so"
    else:
        out.update(how="ambiguous", options=[f"{o['kind']} {o['name']}" for o in found])
        return out
    out.update(names=[o["name"] for o in pick], kinds=[o["kind"] for o in pick],
               kind=pick[0]["kind"] if len({o["kind"] for o in pick}) == 1 else "mixed", how=how)
    if how in ("size of part", "named size and parts"):
        out["relation"] = "thickness"
    return out


def _clauses(text: str) -> list[str]:
    out = []
    for sent in re.split(r"[;!?\n]+|(?<!\d)\.+|\.(?!\d)", text or ""):  # a decimal point is not a full stop
        for c in re.split(rf",\s*(?:and\s+|then\s+)?(?={_VERB}\b)|\s+(?:and|then)\s+(?={_VERB}\b)|,?\s+(?:but|while|whilst)\s+"
                          r"|\s+(?:with|and)\s+(?=(?:the\s+)?[a-z ]+?\s+(?:staying|remaining|following|moving|kept)\b)"
                          r"|,\s+(?=(?:the\s+)?[a-z ]+?\s+(?:can|may|must|should|will|stays?|follows?|moves?)\b)",
                          sent, flags=re.IGNORECASE):
            c = c.strip(" ,")
            if c:
                out.append(c)
    return out


def _mm(v: str, unit: str | None) -> float:
    x = float(v.replace(",", ""))
    return x * 1000 if unit == "m" else x


def _phrases(t: str) -> list[str]:
    ps = [p.strip() for p in re.split(r",\s*(?:and\s+)?|\s+and\s+|\s*&\s*", t or "") if p.strip()]

    size = next((w for p in ps for w in words(p) if w in _SIZE), None)
    if size and len(ps) > 1:  # "wall and slab thicknesses": the size word belongs to each
        ps = [p if words(p) & _SIZE else f"{p} {size}" for p in ps]
    return ps


_PATTERNS: list[tuple[str, str]] = [
    (r"\b(?:do not|don't|dont|never)\s+(?:param(?:e)?teri[sz]e|parametri[sz]e|make)\s+(?P<t>.+?)(?:\s+(?:editable|a parameter|parametric))?$", "no_parameter"),
    (r"\b(?:do not|don't|dont|never)\s+(?:touch|change)\s+(?P<t>.+)$", "review"),
    (r"\bleave\s+(?P<t>.+?)\s+(?:alone|as (?:it|they) (?:is|are)|as is|untouched)$", "review"),
    (r"\b(?:do not|don't|dont|never)\s+(?:modify|alter|edit)\s+(?P<t>.+)$", "exclude"),
    (r"\b(?:exclude|ignore)\s+(?P<t>.+?)(?:\s+from\s+.*)?$", "exclude"),
    (r"\b(?:do not|don't|dont|never)\s+move\s+(?P<t>.+)$", "keep_fixed"),
    (r"\b(?:do not|don't|dont|never)\s+let\s+(?P<t>.+?)\s+(?:move|shift|change|budge)\b.*$", "keep_fixed"),
    (r"^(?P<t>.+?)\s+(?:must|should|may|can|will)\s*(?:not|n't)\s+(?:move|shift|change|budge)\b.*$", "keep_fixed"),
    (r"^(?P<t>.+?)\s+(?:staying|remaining|kept)\s+(?:fixed|where (?:it|they) (?:is|are)|in place|put|as drawn)$", "keep_fixed"),
    (r"^(?!(?:keep|hold|leave|make|let|set|fix|maintain|preserve|retain|ensure)\b)(?P<t>[A-Za-z][A-Za-z ]*?)\s+(?:fixed|held|in place)$", "keep_fixed"),
    (r"\b(?:only|just)\s+(?:update\s+|change\s+)?(?:the\s+)?(?:dimensions?|annotations?|labels?|notes?|texts?)\s+(?:of|on|for)\s+(?P<t>.+)$", "annotations_only"),
    (r"\bupdate\s+only\s+(?:the\s+)?(?:dimensions?|annotations?|notes?)\s+(?:of|on|for)\s+(?P<t>.+)$", "annotations_only"),
    (r"\b(?:keep|hold|leave)\s+(?P<t>.+?)\s+(?:fixed|in place|in position|where (?:it|they) (?:is|are)|as drawn|as built|stationary|still)$", "keep_fixed"),
    (r"\bkeep\s+(?P<t>.+?)\s+(?:unchanged|untouched|unmodified|as it is|as they are)$", "unchanged"),
    (r"^(?:fix|hold)\s+(?P<t>.+)$", "keep_fixed"),
    (r"^(?P<t>.+?)\s+(?:should\s+|must\s+|will\s+|to\s+)?(?:stays?|remains?|is kept|are kept|be kept)\s+(?:fixed|where (?:it|they) (?:is|are)|in place|in position|put|as drawn|as built)$", "keep_fixed"),
    (r"^(?P<t>.+?)\s+(?:unchanged|untouched|as (?:it|they) (?:is|are)|as is|as drawn|as built)$", "unchanged"),
    (r"^(?P<t>.+?)\s+(?:should\s+|must\s+|will\s+|can\s+|may\s+)?(?:follow|follows|moves? with|moves? along with|goes? with|stays? attached to|remains? attached to|stays? connected to)\s+(?P<i>.+)$", "follow"),
    (r"\b(?:update|move|adjust)\s+(?:the\s+)?(?P<t>(?:connected|attached|adjacent)\b.*)$", "follow"),
    (r"\bmove\s+(?P<t>.+?)\s+(?:along\s+)?with\s+(?P<i>.+)$", "follow"),
    (r"^(?P<t>.+?)\s+(?:can|may|should|must|will)\s+(?:move|go)\s+(?:along\s+)?with\s+(?P<i>.+)$", "follow"),
    (r"^(?P<t>.+?)\s+(?:following|moving with(?: it)?|moving along)$", "follow"),
    (r"\b(?:update|regenerate|refresh)\s+(?:all\s+|every\s+)?(?:the\s+)?(?:corresponding\s+|affected\s+|other\s+)?(?P<t>(?:views?|dimensions?|annotations?|notes?)\b.*)$", "update_views"),
    (r"^(?P<t>.+?\s+(?:keeps?|maintains?|retains?|preserves?)\s+(?:their|its|the same|his|her)\s+.+)$", "keep_own"),
    (r"\b(?:maintain|keep|preserve|retain|ensure|hold)\s+(?P<t>.+?)(?:\s+(?:constant|unchanged|the same|as drawn|as is))?$", "keep"),
    (r"^(?P<t>.+?)\s+(?:stays?|remains?)\s+(?:constant|the same|unchanged|fixed)$", "keep"),
    (r"\b(?:resize|stretch)\s+(?P<t>.+)$", "resize"),
    (r"\b(?:update|adjust)\s+(?P<t>.+)$", "follow"),
    (r"\bparam(?:e)?teri[sz]e|parametri[sz]e\s+(?P<t>.+)$", "parameterize"),
    (r"\bmake\s+(?P<t>.+?)\s+(?:editable|a parameter|parametric|adjustable)$", "parameterize"),
]
_DVERB = r"(?P<verb>reduce|decrease|increase|change|set|shrink|enlarge|widen|narrow|lengthen|shorten|raise|lower|modify|alter)"
_DRIVER = [
    rf"\b{_DVERB}\s+(?:the\s+)?(?P<t>.+?)\s*\(\s*\d[\d,]*(?:\.\d+)?\s*(?:mm|m)?\s*(?:->|→|to)\s*{_NUM}\s*\)",
    rf"\b{_DVERB}\s+(?:the\s+)?(?P<t>.+?)\s+(?:from\s+\d[\d,]*(?:\.\d+)?\s*(?:mm|m)?\s+)?(?P<rel>to|by|=)\s+{_NUM}(?![\d.])",
    rf"\bmake\s+(?:the\s+)?(?P<t>[A-Za-z][A-Za-z' ]*?)\s+(?:equal to\s+|=\s*)?{_NUM}\b",
    rf"^(?:the\s+)?(?P<t>[A-Za-z][A-Za-z' ]*?)\s+(?:should|must|shall|will|is to|has to)?\s*(?:become|be|equal|go to)\s+{_NUM}\b",
    rf"^(?P<t>[A-Za-z][A-Za-z ]*?)\s*(?P<rel>=|to)\s*{_NUM}\b",
    rf"^(?:the\s+)?(?P<t>[A-Za-z][A-Za-z ]*?)\s+(?:of\s+|at\s+)?{_NUM}\b",
    rf"\b{_DVERB}\s+(?:the\s+)?(?P<t>[^,;]+?)\s*(?:,|;|$)",
    r"\bwhen\s+(?:the\s+)?(?P<t>.+?)\s+(?:changes?|grows?|shrinks?|increases?|decreases?|is changed)\b",
]
_ANCHOR = [
    ("centered", r"\b(?:centred|centered|centrally|symmetric(?:al)?(?:ly)?|about (?:the|its) (?:centre|center) ?line|both sides equally)\b"),
    ("start_fixed", (r"\b(?:left|bottom|upstream|near)\s+(?:end\s+|side\s+|face\s+)?(?:fixed|stays?|in place)|\bfrom the (?:left|bottom)\b|"
                     r"\bgrows? (?:to the right|rightwards?|upwards?)\b")),
    ("end_fixed", (r"\b(?:right|top|downstream|far)\s+(?:end\s+|side\s+|face\s+)?(?:fixed|stays?|in place)|\bfrom the (?:right|top)\b|"
                   r"\bgrows? (?:to the left|leftwards?|downwards?)\b")),
]


def read_instruction(text: str, vocab: list[dict], prog: Program | None = None) -> dict:
    """The deterministic first reading of an instruction: clauses → a mode and the objects each names, the driver and
    the value asked for, an anchor if one is stated. Generic English only, resolved against THIS drawing's names; what
    it cannot resolve is said, never guessed (the agent's reading, or the person, fills it in)."""
    out: dict = {"driver": None, "anchor": None, "clauses": []}
    for clause in _clauses(text):
        norm = re.sub(r"\b(?:exactly|completely|entirely|strictly|absolutely|just)\s+(?=where|fixed|in place|as )", "", clause, flags=re.IGNORECASE)
        norm = re.sub(r"^(?:can|could|would|will) you\s+|^(?:please|kindly)\s+|^i (?:want|need|would like)(?: you)?(?: to)?\s+", "", norm.strip(),
                      flags=re.IGNORECASE)
        norm = re.sub(r"\s+", " ", norm).strip()
        low = norm.lower()  # the same length: a span found in `low` is cut from `norm`, so a CamelCase name survives
        c: dict = {"text": norm, "mode": None, "targets": [], "unresolved": [], "ambiguous": []}
        cut = None  # where an anchor phrase starts: it says how the size grows, not what the clause is about
        for pol, rx in _ANCHOR:
            m = re.search(rx, low)
            if m:
                out["anchor"] = {"policy": pol, "clause": norm}
                cut = m.start() if cut is None else min(cut, m.start())
        drv = None
        if not re.search(r"\b(?:do not|don't|dont|never)\b", low):
            for rx in _DRIVER:
                m = re.search(rx, low)
                if m:
                    drv = m
                    break
        if drv is not None:
            t0, t1 = drv.span("t")
            if cut is not None and t0 < cut < t1:
                t1 = cut
            r = resolve(norm[t0:t1].strip(" ,"), vocab, prog, prefer="parameter")
            rest = (norm[:drv.start()] + " " + norm[drv.end():]).strip(" ,")
            if cut is not None:
                rest = norm[:drv.start()] + " " + norm[drv.end():cut] if cut > drv.end() else norm[:drv.start()]
            if words(rest) - {"please", "mm", "m", "value", "now"}:
                c["unread"] = rest.strip(" ,")
            req = None
            if drv.groupdict().get("v"):
                x = _mm(drv.group("v"), drv.group("u") if drv.group("u") != "%" else None)
                req = {"value": x, "relative": drv.groupdict().get("rel") == "by", "percent": drv.group("u") == "%",
                       "sign": -1.0 if (drv.groupdict().get("verb") or "") in ("reduce", "decrease", "shrink", "narrow", "shorten", "lower") else 1.0}
            out["driver"] = {"phrase": norm[t0:t1].strip(" ,"), "resolved": r, "requested": req, "clause": norm}
            c["mode"] = "driver"
            out["clauses"].append(c)
            continue
        for rx, mode in _PATTERNS:
            m = re.search(rx, low)
            if not m:
                continue
            t0, t1 = m.span("t")
            if cut is not None and t0 < cut < t1:
                t1 = cut
            t = norm[t0:t1].strip(" ,")
            if mode == "keep_own":
                subj, own = re.split(r"\s+(?:keeps?|maintains?|retains?|preserves?)\s+(?:their|its|the same|his|her)\s+", t, maxsplit=1, flags=re.IGNORECASE)
                t, mode = f"{subj} {own}", "keep"
            c["mode"] = mode
            lead = norm[:m.start()].strip(" ,")
            if words(lead) - {"then", "also", "please", "finally", "first"}:
                c["unread"] = lead
            if cut is not None and not words(t):
                c["mode"] = "anchor"
                break
            if mode == "follow" and m.groupdict().get("i"):
                ri = resolve(norm[slice(*m.span("i"))], vocab, prog)
                c["interface"] = ri["names"] if ri["names"] else []
                if not ri["names"]:
                    c["unresolved"].append(norm[slice(*m.span("i"))])
            phrases = _phrases(t)
            head = (re.findall(r"[A-Za-z]+", phrases[-1]) or [""])[-1] if len(phrases) > 1 else ""
            for k, ph in enumerate(phrases):
                prefer = ("parameter" if mode == "parameterize" else None if mode in ("keep", "unchanged", "update_views") else "part")
                many = mode in ("keep", "unchanged", "parameterize", "update_views", "follow", "resize")
                r = resolve(ph, vocab, prog, many_ok=many, prefer=prefer)
                if not r["names"] and r["how"] != "ambiguous" and head and k < len(phrases) - 1 and head.lower() not in ph.lower():
                    r2 = resolve(f"{ph} {head}", vocab, prog, many_ok=many, prefer=prefer)  # "the top and bottom slabs"
                    if r2["names"] or r2["how"] == "ambiguous":
                        r, ph = r2, f"{ph} {head}"
                if r["names"]:
                    c["targets"].append(r)
                elif r["how"] == "ambiguous":
                    c["ambiguous"].append(r)
                else:
                    c["unresolved"].append(ph)
            break
        if c["mode"] is None and cut is not None:
            c["mode"] = "anchor"  # nothing but how the size grows
        out["clauses"].append(c)
    return out


# ── the driver and its occurrences ───────────────────────────────────────────────


def pairs_of(prog: Program, answer: dict | None, name: str) -> list[tuple[str, str]]:
    """The exact pairs of lines a value is bound to (low, high as drawn): its occurrences, or the two lines it spans."""
    an = prog.analysis
    v = line_values_mm(prog)
    row = next((p for p in (answer or {}).get("parameters", []) if p.get("name") == name), None)
    out: list[tuple[str, str]] = []
    if row:
        cid, occ = row.get("candidate"), row.get("occurrences")
        if cid and cid in an.clusters:
            gids = an.clusters[cid].gaps if occ in (None, "all", ["all"]) else occ
            out = [(an.gaps[g].a, an.gaps[g].b) for g in gids if g in an.gaps and an.gaps[g].axis in ("x", "y")]
        elif row.get("from_datum") and row.get("to_datum"):
            out = [(cast(str, row["from_datum"]), cast(str, row["to_datum"]))]
    if not out:
        c = next((c for c in an.clusters.values() if c.name == name), None)
        if c is not None:
            out = [(an.gaps[g].a, an.gaps[g].b) for g in c.gaps if g in an.gaps and an.gaps[g].axis in ("x", "y")]
    prm = prog.params.get(name)
    if not out and prm is not None and prm.measures:
        out = [prm.measures]
    return cast(
        list[tuple[str, str]],
        [
            (a, b) if v.get(a, 0) <= v.get(b, 0) else (b, a)
            for a, b in out
            if a in an.datums and b in an.datums
        ],
    )


def parameter_pairs(
    prog: Program, answer: dict | None, name: str
) -> list[tuple[str, str]]:
    pairs = pairs_of(prog, answer, name)
    if pairs:
        return pairs
    prm = prog.params.get(name)
    measures = prm.measures if prm is not None else None
    return [cast(tuple[str, str], measures)] if measures is not None else []


def drives_pairs(prog: Program, name: str, pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The pairs the value does NOT drive 1 mm per mm (empty: it drives every one)."""
    r = rates(prog, name)
    v = line_values_mm(prog)
    return [(a, b) for a, b in pairs
            if abs(((r.get(b, 0.0) - r.get(a, 0.0)) if v[a] <= v[b] else (r.get(a, 0.0) - r.get(b, 0.0))) - 1.0) > 1e-6]


# ── the plan ─────────────────────────────────────────────────────────────────────


def _parts(prog: Program) -> dict[str, Part]:
    return prog.intent.get("parts") or {}


def _top(parts: dict[str, Part], n: str) -> str:
    seen = {n}
    while True:
        parent = parts[n].parent
        if parent is None or parent not in parts or parent in seen:
            break
        n = parent
        seen.add(n)
    return n


def core_parts(parts: dict[str, Part], pairs: list[tuple[str, str]]) -> set[str]:
    """The parts a size belongs to: the leaf parts drawn on its lines, and the assembly they are part of."""
    ends = {x for p in pairs for x in p}
    leaves = [n for n, p in parts.items() if p.own_datums & ends and not any(q.parent == n for q in parts.values())]
    if not leaves:
        leaves = [n for n, p in parts.items() if p.own_datums & ends]
    return {_top(parts, n) for n in leaves}


def _part_lines(parts: dict[str, Part], n: str, axis: str, an) -> set[str]:
    return {d for d in parts[n].datums if d in an.datums and an.datums[d].axis == axis}


def _attached(prog: Program, parts: dict[str, Part], members: set[str], core: set[str], axis: str) -> dict[str, str]:
    """Parts outside the assembly that are tied to it on this axis, with how: drawn on its lines, set out from them,
    or touching it — each needs an accepted behaviour before the assembly may move."""
    an = prog.analysis
    inside = set()
    for n in core:
        inside |= {n} | descendants(parts, n)
    out: dict[str, str] = {}
    touch = {}
    for row in interfaces(prog, parts):
        a, b = cast(tuple[str, str], row["parts"])
        for x, y in ((a, b), (b, a)):
            if x in inside and y not in inside:
                touch.setdefault(y, f"touches {x} ({row['evidence']})")
    for n in parts:
        if n in inside or any(a in inside for a in _ancestors(parts, n)) or any(q.parent == n for q in parts.values()):
            continue
        own = entity_lines(prog, part_entities(prog, parts, n), axis) or _part_lines(parts, n, axis, an)
        shared = sorted(own & members)
        hangs = sorted(d for d in own - members if d in prog.formulas and _depends_on(prog, d) & members)
        if shared:
            out[n] = f"drawn on the assembly's lines {', '.join(shared[:4])}"
        elif n in touch:
            out[n] = touch[n]
        elif hangs:  # not touching: only the set-out happens to hang it on the assembly's lines
            out[n] = f"its lines {', '.join(hangs[:4])} are set out from the assembly"
    return out


def _sibling_parts(prog: Program, parts: dict[str, Part], answer: dict | None, name: str | None, pairs: list[tuple[str, str]], axis: str | None,
                   own: set[str]) -> set[str]:
    """The parts the value moves through its occurrences in OTHER assemblies (a sibling view beside this one on this axis), with what is drawn on or
    hung from their lines: the value itself moves them, and the plan of THAT assembly answers for how. This plan neither holds them nor takes them
    along — a view that is only positioned from this one by the set-out is not part of this structure. `own`: this plan's own core and subtree."""
    if not (parts and axis and name and name in prog.params):
        return set()
    mine = {tuple(p) for p in pairs}
    other = [tuple(pr) for pr in parameter_pairs(prog, answer, name) if tuple(pr) not in mine]
    if not other:
        return set()
    core = core_parts(parts, other)
    out: set[str] = set()
    for n in core:
        out |= {n} | descendants(parts, n)
    out |= set(_attached(prog, parts, assembly_lines(prog, parts, core, axis, seed={x for pr in other for x in pr}), core, axis))
    return out - own


def _touches(why: str) -> bool:
    return not why.startswith("its lines")


BEHAVIOUR_MODES = (*MOVING_MODES, *FIXED_MODES, "review", "no_parameter")  # what a part DOES (an invariant is not a behaviour)


def _behaves(dirs: list[dict], n: str) -> bool:
    return any(d["target"] == n and d["mode"] in BEHAVIOUR_MODES and d["status"] in ("accepted", "unresolved", "proposed") for d in dirs)


def _ancestors(parts: dict[str, Part], n: str) -> list[str]:
    out, seen = [], {n}
    p = parts.get(n)
    while p is not None and p.parent and p.parent not in seen:
        out.append(p.parent)
        seen.add(p.parent)
        p = parts.get(p.parent)
    return out


def _effect(prog: Program, parts: dict[str, Part], drv: str, axis: str, an, fixed: set[str] | None = None) -> dict[str, str]:
    """Per part, what +1 mm of the driver does to it on this axis, measured on its lines: which side moves by how much."""
    r = rates(prog, drv)
    lo_word, hi_word = ("left", "right") if axis == "x" else ("bottom", "top")
    v = line_values_mm(prog)
    out = {}
    for n in parts:
        if n in (fixed or ()):
            out[n] = "stays (kept fixed)"
            continue
        ls = _part_lines(parts, n, axis, an)
        if not ls:
            continue
        a, b = min(ls, key=lambda d: v[d]), max(ls, key=lambda d: v[d])
        ka, kb = r.get(a, 0.0), r.get(b, 0.0)
        if abs(ka) < 1e-9 and abs(kb) < 1e-9:
            continue
        out[n] = (f"moves {ka:+g} mm per mm" if abs(ka - kb) < 1e-9
                  else f"{'grows' if kb > ka else 'shrinks'}: {lo_word} side {ka:+g}, {hi_word} side {kb:+g} mm per mm")
    return out


# the sides as the chooser under a value names them (the line that stays)
SIDE_WORDS = {"start_fixed": "its start (left / bottom) staying", "centered": "centred", "end_fixed": "its end (right / top) staying"}


def _trial(prog: Program, parts: dict[str, Part], name: str, pairs, axis: str, policy: str, centre: str | None,
           members: set[str], fixed: set[str], named, held: set[str] | None = None, give: bool = True) -> dict:
    """What a policy would do, without keeping it: the stacking on the program, measured per part, then undone. `give`: as `stack` (False for the
    engine's own default)."""
    saved = (dict(prog.formulas), dict(prog.origin))
    try:
        st = stack(prog, axis, [Driver(name, pairs, policy, centre)], members, still=fixed, named=named, give=give)
        eff = _effect(prog, parts, name, axis, prog.analysis, held) if st.ok else {}
        moved = sorted(d for d, k in rates(prog, name).items() if abs(k) > 1e-9 and prog.analysis.datums[d].axis == axis) if st.ok else []
    finally:
        prog.formulas.clear()
        prog.formulas.update(saved[0])
        prog.origin.clear()
        prog.origin.update(saved[1])
        prog.invalidate()
    return {"policy": policy, "centre": centre, "available": st.ok, "why": st.why if not st.ok else POLICY_WORDS[policy],
            "anchor_line": st.root, "rewrites": len(st.written), "parts": eff, "lines_moved": len(moved),
            "conflicts": st.conflicts[:3], "blocked": st.blocked[:12]}


def _question(qid: str, about: str, text: str, options: list[str], recommended: str | None = None, why: str = "") -> dict:
    return {"id": qid, "about": about, "text": text, "options": options, "recommended": recommended, "why": why}


def build_plan(prog: Program, answer: dict, request: dict, sheet: dict | None = None, reader: bool = True) -> dict:
    """A plan for one request on the program as it stands (built from `answer`). `request`: {instruction, driver?,
    directives?, anchor?, requested_value?, decisions?, questions?, id?} — explicit fields (the agent's structured
    reading, the person's choices) take precedence over the deterministic reading of the instruction. `sheet`:
    {revision, unit, views_of(items) → view ids, shared {local: shared name}, other_units(local) → units} when the unit
    is on a sheet.

    `reader`: whether the built-in phrase matcher (read_instruction) also reads `instruction`. It is a narrow,
    non-authoritative first pass kept for tests and the benchmark; everything a person uses (the agent's run) passes
    reader=False, so the plan holds only what the model proposed (its directives quote the person's words, which are
    checked here) and what the person decided. `request["questions"]`: ambiguities the model puts to the person.

    Nothing is changed: the plan says what WOULD happen, what is decided and what is not."""
    an = prog.analysis
    parts = _parts(prog)
    vocab = vocabulary(prog, parts)
    instruction = (request.get("instruction") or "").strip()
    reading = read_instruction(instruction, vocab, prog) if instruction and reader else {"driver": None, "anchor": None, "clauses": []}
    decisions = dict(request.get("decisions") or {})
    plan: dict = {"format": PLAN_FORMAT, "id": request.get("id") or "P1", "instruction": instruction, "status": "draft",
                  "revision": {"sheet": (sheet or {}).get("revision"), "unit": (sheet or {}).get("unit")},
                  "driver": None, "anchor": None, "directives": [], "affected": {}, "dependency": [], "questions": [],
                  "conflicts": [], "reading": [{"clause": c["text"], "mode": c["mode"],
                                                "targets": [f"{t['kind']} {', '.join(t['names'])}" for t in c["targets"]],
                                                "unresolved": c["unresolved"], "ambiguous": [a["phrase"] for a in c["ambiguous"]]}
                                               for c in reading["clauses"]], "checks": None}
    qn = 0

    def ask(about: str, text: str, options: list[str], recommended: str | None = None, why: str = "") -> str:
        nonlocal qn
        qn += 1
        qid = f"Q{qn}"
        if about in decisions:  # answered already: the person's (or the instruction's) choice is applied, no question
            return decisions[about]
        plan["questions"].append(_question(qid, about, text, options, recommended, why))
        return ""

    # ── 1. the driver ──
    drq = request.get("driver") or {}
    name = drq.get("parameter")
    how = "request" if name else ""
    req_value = request.get("requested_value", drq.get("requested_value"))
    if not name and reading["driver"]:
        r = reading["driver"]["resolved"]
        if r["names"] and r["kind"] == "part":  # "widen both cells": the named value whose occurrences ARE their widths
            by = _value_sizing(prog, answer, parts, r["names"])
            if by:
                r = {**r, "names": [by], "kind": "parameter", "how": f"the size of {', '.join(r['names'])}"}
        if r["names"] and r["kind"] in ("parameter", "level") and len(r["names"]) == 1:
            name, how = r["names"][0], f"the instruction: '{reading['driver']['clause']}'"
        elif r["how"] == "ambiguous":
            pick = ask("driver", f"'{reading['driver']['phrase']}' could be {', '.join(r['options'])}: which value is meant?", r["options"])
            if pick:
                name, how = pick.split(" ", 1)[-1], "the person's choice"
                if name not in prog.params:
                    name = None
        else:
            ask("driver", f"'{reading['driver']['phrase']}' is not a named value of this drawing: name the size first "
                          f"(define it on its occurrences), then plan the change.", [])
        rq = reading["driver"].get("requested")
        if req_value is None and rq and name in prog.params:
            base = prog.params[name].value
            step = base * rq["value"] / 100 if rq.get("percent") else rq["value"]
            req_value = base + rq["sign"] * step if rq["relative"] else (None if rq.get("percent") else rq["value"])
    if name and name not in prog.params:
        plan["conflicts"].append(f"{name} is not a value of this drawing (define it on its occurrences first)")
        name = None
    if name:
        prm = prog.params[name]
        pairs = [cast(tuple[str, str], tuple(p)) for p in drq.get("pairs") or pairs_of(prog, answer, name)]
        # occurrences the value was asked for and the plain set-out could not follow: the anchor's set-out is what makes them follow
        extra = [cast(tuple[str, str], tuple(p)) for p in drq.get("extra_pairs") or [] if tuple(p) not in pairs and all(x in an.datums for x in p)]
        axis = an.datums[(pairs or extra)[0][0]].axis if (pairs or extra) else None
        if (pairs or extra) and any(an.datums[a].axis != axis for a, _b in pairs + extra):
            plan["conflicts"].append(f"{name}'s occurrences lie on both axes: plan one axis at a time")
        lost = drives_pairs(prog, name, pairs)
        if lost:
            plan["conflicts"].append(f"{name} does not drive {', '.join(f'{a}–{b}' for a, b in lost[:4])} (it is worked out there)")
        pairs = pairs + extra
        row = next((p for p in answer.get("parameters", []) if p.get("name") == name), {})
        plan["driver"] = {"parameter": name, "label": prm.label, "kind": prm.kind, "unit": prm.unit, "value": round(prm.value, 6),
                          "requested_value": None if req_value is None else round(float(req_value), 6),
                          "candidate": row.get("candidate"), "occurrences": row.get("occurrences"),
                          "pairs": [list(p) for p in pairs], "extra_pairs": [list(p) for p in extra], "axis": axis, "source": how or "request"}
    else:
        pairs, axis = [], None

    # ── 2. the directives the instruction (and the request) state ──
    dirs: list[dict] = []

    def add(target: str, kind: str, mode: str, clause: str, source: str = "instruction", **extra) -> dict:
        d = {"id": f"D{len(dirs) + 1}", "target": target, "kind": kind, "mode": mode, "status": "accepted" if mode != "review" else "unresolved",
             "source": source, "clause": clause, **extra}
        dirs.append(d)
        return d

    for c in reading["clauses"]:
        mode = c["mode"]
        unread = c["text"] if mode is None else c.get("unread")
        if unread:  # never silently dropped: what the reading could not account for is put to the person
            pick = ask(f"unread:{unread}", f"I could not read: '{unread}' ({c['text']}). What should happen? Say it again plainly "
                       "(e.g. 'Keep the foundation fixed', 'Change the width to 2800'), or ignore it.", ["ignore"])
            if pick:
                c["unread_answer"] = pick
        if mode in (None, "driver", "anchor"):
            continue
        for amb in c["ambiguous"]:
            pick = ask(f"target:{amb['phrase']}", f"'{amb['phrase']}' ({c['text']}) could be {', '.join(amb['options'])}: which one?",
                       amb["options"])
            if pick:
                kind, _sp, nm = pick.partition(" ")
                c["targets"].append({"phrase": amb["phrase"], "names": [nm], "kind": kind, "how": "person"})
        for un in c["unresolved"]:
            pick = ask(f"phrase:{un}", f"'{un}' ({c['text']}): nothing on this drawing is called that — which part or value is it?",
                       sorted(parts)[:30] + ["ignore"])
            if pick and pick != "ignore":
                c["targets"].append({"phrase": un, "names": [pick], "kind": _kind_of(prog, parts, pick), "how": "person"})
        for t in c["targets"]:
            for n, kind in zip(t["names"], t.get("kinds") or [t["kind"]] * len(t["names"]), strict=False):
                m = mode
                if m == "keep":
                    rel = next((r for r, rx in _RELWORDS if re.search(rx, c["text"].lower())), None)
                    if kind == "level" or (kind == "line" and n in an.datums):
                        m = "keep_fixed"
                    elif kind == "parameter" or t.get("relation") == "thickness" and kind != "part":
                        m = "keep_value"
                    elif kind == "part" and (t.get("relation") or rel in ("thickness",)):
                        add(n, kind, "preserve", c["text"], relation="thickness")
                        continue
                    elif rel == "symmetry":
                        add(n, kind, "preserve", c["text"], relation="symmetry")
                        continue
                    elif rel == "connection":
                        add(n, kind, "preserve", c["text"], relation="connection")
                        continue
                    elif kind == "part":
                        m = "review"
                    else:
                        m = "keep_value"
                if m == "unchanged":
                    m = "keep_value" if kind in ("parameter",) else "exclude" if kind == "generic" else "keep_fixed"
                if kind == "generic":
                    if not any(x["target"] == n and x["kind"] == "generic" for x in dirs):
                        add(n, "generic", "update_views" if n == "views" else m, c["text"])
                    continue
                if m == "review":
                    add(n, kind, "review", c["text"], options=["keep_fixed", "follow", "exclude"] if mode == "keep" else
                        ["no_parameter", "keep_fixed", "exclude"])
                    continue
                extra = {"interface": c.get("interface")} if m == "follow" and c.get("interface") else {}
                add(n, kind, m, c["text"], **extra)
        if mode == "update_views" and not c["targets"]:
            add("views", "generic", "update_views", c["text"])
    said = re.sub(r"\s+", " ", instruction.lower())
    asked: dict[str, dict] = {}
    for d in request.get("directives") or []:  # explicit (the agent's reading, a person's edit): replaces the same target's
        tgt = d.get("target")
        src = d.get("source") or "person"
        clause = (d.get("clause") or "").strip()
        if src == "instruction" and not (clause and re.sub(r"\s+", " ", clause.lower()) in said):
            src = "ai"  # authority the instruction's own words do not bear out is only a proposal
        mode = d.get("mode", "review")
        if mode not in MODES:
            plan["conflicts"].append(f"{tgt}: {mode!r} is not a directive mode ({', '.join(MODES)})")
            continue
        before = asked.get(tgt)
        if before is not None and before["mode"] != mode and not (before.get("relation") or d.get("relation")):
            # one proposal that says two things of one part is not one instruction: the later never silently wins
            plan["conflicts"].append(f"{tgt}: {before['mode']} and {mode} cannot both hold ('{before['clause'][:70]}' / '{clause[:70]}') — ask which is meant")
        asked[tgt] = {"mode": mode, "clause": clause, "relation": d.get("relation")}
        dirs[:] = [x for x in dirs if x["target"] != tgt]
        nd = add(tgt, d.get("kind") or _kind_of(prog, parts, tgt), mode, clause, source=src,
                 **{k: d[k] for k in ("relation", "interface", "options", "axis", "why") if d.get(k)})
        if src == "ai" and nd["status"] == "accepted":
            nd["status"] = "proposed"  # the AI's inference: a person accepts it, or it does not bind
    # unknown targets are refused, never guessed
    for d in dirs:
        if d["kind"] in ("part",) and d["target"] not in parts or d["kind"] in ("parameter", "level") and d["target"] not in prog.params \
                or d["kind"] == "line" and d["target"] not in an.datums:
            plan["conflicts"].append(f"{d['id']}: {d['target']} is not a {d['kind']} of this drawing")
            d["status"] = "rejected"
    # ── 3. the assembly ──
    named = {
        n: parameter_pairs(prog, answer, n)
        for n, q in prog.params.items()
        if q.source in ("ai", "dimension", "person") and q.kind != "level"
    }
    fixed_parts = {d["target"] for d in dirs if d["kind"] == "part" and d["mode"] in FIXED_MODES and d["status"] == "accepted"}
    core = core_parts(parts, pairs) if parts and pairs else set()
    plan["affected"]["core"] = sorted(core)
    followers = {d["target"] for d in dirs if d["kind"] == "part" and d["mode"] in MOVING_MODES and d["status"] == "accepted"}
    own_core: set[str] = set()
    for n in core:
        own_core |= {n} | descendants(parts, n)
    sibling = _sibling_parts(prog, parts, answer, name, pairs, axis, own_core)  # a sibling view's parts are not this assembly's: neither held nor taken along
    # ── 4. generic directives expand to the parts they mean ──
    members: set[str] = set()
    attached: dict[str, str] = {}
    if name and axis and prog.params[name].kind != "level":
        members = assembly_lines(prog, parts if parts else None, (core | followers) if parts else None, axis,
                                 seed={x for p in pairs for x in p}, exclude=fixed_parts)
        if parts:
            attached = {n: why for n, why in _attached(prog, parts, members, core | followers, axis).items() if n not in sibling}
    for d in [x for x in dirs if x["kind"] == "generic"]:
        if d["target"] == "connected":  # what touches the assembly — not what the set-out merely hangs on its lines
            d["expands_to"] = sorted(n for n, why in attached.items() if _touches(why))
            for n in d["expands_to"]:
                if not _behaves(dirs, n):
                    add(n, "part", d["mode"] if d["mode"] in MOVING_MODES else "follow", d["clause"], source="instruction (connected geometry)")
        elif d["target"] == "unrelated" and parts:
            inside = set()
            for n in core:
                inside |= {n} | descendants(parts, n)
            rest = [n for n in parts if n not in inside and not (n in attached and _touches(attached[n]))
                    and not any(a in inside for a in _ancestors(parts, n)) and not any(q.parent == n for q in parts.values())
                    and not _behaves(dirs, n)]
            d["expands_to"] = sorted(rest)
            for n in rest:
                add(n, "part", d["mode"] if d["mode"] in FIXED_MODES else "exclude", d["clause"], source="instruction (unrelated geometry)")
    # ── 5. decisions on what was unclear, and on what the AI proposes ──
    for d in dirs:
        if d["status"] == "proposed":
            pick = ask(d["id"], f"The AI proposes: {d['target']} — {d['mode']} ({MODES[d['mode']]})"
                       + (f", because {d['why']}" if d.get("why") else "") + ". Accept?",
                       ["accept", "reject"] + [m for m in ("keep_fixed", "follow", "exclude", "no_parameter") if m != d["mode"]],
                       recommended="accept")
            if pick == "accept":
                d.update(status="accepted", source="person (accepted the AI's proposal)")
            elif pick == "reject":
                d["status"] = "rejected"
            elif pick in MODES:
                d.update(mode=pick, status="accepted", source="person")
    for d in dirs:
        if d["status"] == "unresolved":
            pick = ask(d["id"], f"'{d['clause']}': for {d['target']}, which is meant — "
                       + "; ".join(f"{o}: {MODES[o]}" for o in d.get("options", [])), d.get("options", []))
            if pick:
                d.update(mode=pick, status="accepted", source="person")
    for k, q in enumerate(request.get("questions") or []):  # an ambiguity the model found: put to the person, never settled by a guess
        q = q if isinstance(q, dict) else {"text": str(q)}
        if (q.get("text") or "").strip():
            ask(f"ask:{k + 1}", q["text"].strip(), [str(o) for o in q.get("options") or []], why=q.get("why") or "")
    fixed_parts = {d["target"] for d in dirs if d["kind"] == "part" and d["mode"] in FIXED_MODES and d["status"] == "accepted"}
    followers = {d["target"] for d in dirs if d["kind"] == "part" and d["mode"] in MOVING_MODES and d["status"] == "accepted"}
    if name and axis and parts and prog.params[name].kind != "level":
        # the directives above (a generic "what touches it follows", a person's answers) have just named more parts that move with the assembly:
        # its lines are worked out again, or the anchor below would be tried on a smaller assembly than the one that moves
        members = assembly_lines(prog, parts, core | followers, axis, seed={x for p in pairs for x in p}, exclude=fixed_parts)
        attached = {n: why for n, why in _attached(prog, parts, members, core | followers, axis).items() if n not in sibling}
    # ── 6. conflicts between directives, and with the driver ──
    by_target: dict[str, list[dict]] = {}
    for d in dirs:
        if d["status"] == "accepted":
            by_target.setdefault(d["target"], []).append(d)
    for tgt, ds in by_target.items():
        modes = {d["mode"] for d in ds}
        if modes & set(FIXED_MODES) and modes & set(MOVING_MODES):
            plan["conflicts"].append(f"{tgt}: {' and '.join(sorted(modes))} cannot both hold ({'; '.join(d['clause'] for d in ds)[:160]})")
        if name and tgt == name and modes & {"keep_value", "keep_fixed"}:
            plan["conflicts"].append(f"{name} is the value being changed, and also asked to stay as it is")
    if parts and pairs:
        ends = {x for p in pairs for x in p}
        for n in fixed_parts:
            if n in parts and ends <= parts[n].own_datums:
                plan["conflicts"].append(f"{name}'s lines all belong to {n}, which is kept fixed: the value could not change")
    for d in dirs:
        if d["status"] == "accepted" and d["kind"] == "part" and d["mode"] in ("no_parameter", "exclude"):
            own = [n for n, q in prog.params.items() if q.source == "ai" and q.component == d["target"] and n != name]
            if own:
                plan["conflicts"].append(f"{d['target']} gets no value of its own, but {', '.join(own)} is one: remove it, or change the directive")
    # ── 7. the anchor ──
    anchor = _decide_anchor(prog, plan, request, reading, decisions, dirs, parts, name, pairs, axis, members, fixed_parts, named, ask, answer)
    plan["anchor"] = anchor
    # ── 8. attached parts without an accepted behaviour ──
    if name and parts and anchor and anchor.get("policy"):
        for n, why in sorted(attached.items()):
            if _behaves(dirs, n):
                continue
            trial = next((a for a in anchor.get("alternatives", []) if a["policy"] == anchor["policy"] and a.get("centre") == anchor.get("centre")), None)
            does = (trial or {}).get("parts", {}).get(n)
            touches = _touches(why)
            pick = ask(f"attached:{n}", f"{n} is tied to the assembly ({why}); as the set-out stands, when {name} changes it "
                       f"{does if does else 'stays where it is'} — should it follow, or stay fixed?",
                       ["follow", "keep_fixed"], recommended="follow" if touches else "keep_fixed",
                       why=("it is drawn against the assembly" if touches else
                            "it does not touch the assembly: it only hangs on its lines through the set-out")
                       + "; a part tied to the assembly needs an accepted behaviour before the assembly moves")
            if pick:
                add(n, "part", pick, f"decision on attached {n}", source="person")
    # ── 9. what follows: views, dimensions, notes, other units ──
    if name:
        plan["affected"].update(_affected(prog, plan, name, pairs, axis, members, sheet))
        plan["dependency"] = _dependency(prog, plan, name, pairs, parts, sheet)
    plan["directives"] = dirs
    plan["affected"]["attached"] = attached
    plan["affected"]["members"] = len(members)
    # ── 10. status ──
    if not name:
        plan["status"] = "needs_decision" if plan["questions"] else "draft"
    elif plan["conflicts"]:
        plan["status"] = "conflict"
    elif plan["questions"]:
        plan["status"] = "needs_decision"
    else:
        plan["status"] = "ready"
    decided = [d for d in dirs if d["status"] == "accepted"]
    explicit = [d for d in decided if d["source"] in ("instruction", "person", "request") or d["source"].startswith("instruction")]
    plan["confidence"] = {"directives_explicit": f"{len(explicit)}/{len(decided)}",
                          "anchor": (anchor or {}).get("source", "none"),
                          "basis": "every behaviour stated or chosen by a person" if len(explicit) == len(decided) and (anchor or {}).get("source") in ("instruction", "person", "accepted before", "only feasible")
                          else "some behaviour rests on evidence or a provisional choice: shown for review"}
    return plan


def _value_sizing(prog: Program, answer: dict, parts: dict[str, Part], names: list[str]) -> str | None:
    """The one named value whose occurrences are exactly these parts' extents on one axis (the cells' widths → the
    clear span), or None."""
    an = prog.analysis
    v = line_values_mm(prog)
    hits = []
    for ax in ("x", "y"):
        ext = set()
        for n in names:
            ls = _part_lines_all(parts, n, ax, an) if n in parts else set()
            if len(ls) < 2:
                break
            ext.add((min(ls, key=lambda d: v[d]), max(ls, key=lambda d: v[d])))
        else:
            for q, prm in prog.params.items():
                if prm.source in ("ai", "dimension", "person") and prm.kind != "level" and set(pairs_of(prog, answer, q)) == ext:
                    hits.append(q)
    return hits[0] if len(set(hits)) == 1 else None


def _kind_of(prog: Program, parts: dict[str, Part], target: str) -> str:
    if target in parts:
        return "part"
    if target in prog.params:
        return "level" if prog.params[target].kind == "level" else "parameter"
    if target in prog.analysis.datums:
        return "line"
    return "generic" if target in ("connected", "unrelated", "views") else "unknown"


def _decide_anchor(prog, plan, request, reading, decisions, dirs, parts, name, pairs, axis, members, fixed_parts, named, ask, answer) -> dict | None:
    """Which line stays when the driver changes, decided by evidence in this order: the request, an earlier accepted
    plan for the same value, the instruction, the drawing (when only one policy keeps every fixed line where it is);
    otherwise a person chooses between the alternatives, each shown with what it would do (or a provisional policy a
    person configured, shown as provisional)."""
    if not name or not pairs or prog.params[name].kind == "level":
        return {"policy": "as_set_out", "status": "accepted", "source": "a level moves its own line", "alternatives": []} if name else None
    fixed_lines = set()  # lines a part kept fixed is drawn on that the assembly shares: the anchor must not move them
    for n in fixed_parts:
        if n in parts:
            fixed_lines |= entity_lines(prog, part_entities(prog, parts, n), axis) & members
    owned = set(protected_lines(prog)) & members  # set by a person, a level, a slope: evidence of what may not move
    cands = centre_candidates(prog, members, pairs)
    give = (request.get("anchor") or {}).get("source") != "design intent"  # a gap may give for a side somebody chose, never for the engine's default
    alts = []
    for pol in ("centered", "start_fixed", "end_fixed", "as_set_out"):
        for centre in ([c for c, _w in cands[:2]] if pol == "centered" else [None]):
            t = _trial(prog, parts, name, pairs, axis, pol, centre, members, fixed_lines, named, fixed_parts, give)
            if pol == "centered":
                t["evidence"] = next((w for c, w in cands if c == centre), "")
                t["symmetric"] = (
                    symmetric_about(prog, members, centre)
                    if centre is not None
                    else False
                )
            alts.append(t)
        if pol == "centered" and not cands:
            alts.append({"policy": "centered", "centre": None, "available": False, "why": "no line at the middle to stay about",
                         "parts": {}, "lines_moved": 0, "rewrites": 0, "conflicts": []})
    out = {"policy": None, "centre": None, "status": "unresolved", "source": "", "evidence": [], "alternatives": alts}
    want = dict(request.get("anchor") or {})
    ai_rec = None
    if want.get("source") == "ai":  # the AI's inference is a recommendation: the instruction or a person decides
        ai_rec, want = want, {}
    if decisions.get("anchor"):  # "centered about x7", or the policy alone
        pol, _sep, c = str(decisions["anchor"]).partition(" about ")
        want = {"policy": pol.strip(), "centre": c.strip() or decisions.get("anchor_centre"), "source": "person"}
    src = want.get("source", "request") if want.get("policy") else ""
    if not want.get("policy"):
        prior = next((p for p in (answer or {}).get("plans", []) if p.get("status") == "accepted"
                      and (p.get("driver") or {}).get("parameter") == name and (p.get("anchor") or {}).get("policy")
                      and (p.get("anchor") or {}).get("source") != "design intent"), None)  # the engine's own default is not a decision: words outrank it
        if prior:
            want, src = {"policy": prior["anchor"]["policy"], "centre": prior["anchor"].get("centre")}, "accepted before"
        elif reading.get("anchor"):
            want, src = {"policy": reading["anchor"]["policy"]}, "instruction"
            out["evidence"].append(f"the instruction: '{reading['anchor']['clause']}'")
            centre_dir = next((d for d in dirs if d["kind"] == "line" and d["mode"] in ("keep_fixed", "preserve")), None)
            if centre_dir and want["policy"] == "centered":
                want["centre"] = centre_dir["target"]
        else:  # a drawn centre line the instruction keeps (or keeps the assembly symmetric about): it stays about it
            centre_dir = next((d for d in dirs if d["kind"] == "line" and d["status"] == "accepted" and d["mode"] in ("preserve", "keep_fixed")
                               and any(c == d["target"] for c, _w in cands)), None)
            if centre_dir:
                want, src = {"policy": "centered", "centre": centre_dir["target"]}, "instruction"
                out["evidence"].append(f"the instruction keeps the centre line {centre_dir['target']}: '{centre_dir['clause']}'")
    if want.get("policy"):
        pol = want["policy"]
        if pol not in POLICIES:
            plan["conflicts"].append(f"anchor {pol!r} is not one of {', '.join(POLICIES)}")
            return out
        centre = want.get("centre") or (next((a["centre"] for a in alts if a["policy"] == "centered" and a["available"]),
                                             next((a["centre"] for a in alts if a["policy"] == "centered"), None)) if pol == "centered" else None)
        alt = next((a for a in alts if a["policy"] == pol and (pol != "centered" or a["centre"] == centre)), None)
        if alt is None and pol == "centered" and centre:
            alt = _trial(prog, parts, name, pairs, axis, pol, centre, members, fixed_lines, named, fixed_parts, give)
            alts.append(alt)
        if pol == "centered" and not want.get("centre") and (alt is None or not alt["available"]):
            # no line is drawn at the middle (a thickness, a course): the size grows half each way about its own middle — asked for, never assumed
            mid = _trial(prog, parts, name, pairs, axis, pol, MID, members, fixed_lines, named, fixed_parts, give)
            mid["evidence"] = "the middle of the size itself (no line is drawn there)"
            alts.append(mid)
            if mid["available"] or alt is None or alt.get("centre") is None:
                alt, centre = mid, MID
        if alt is None or not alt["available"]:
            about = " about its own middle" if centre == MID else f" about {centre}" if centre else ""
            # what a person can do instead: the sides the stacking allows (tried above, nothing kept) — checked on the whole sheet once chosen. A
            # side only a site level stands in the way of is taken for a person too: the level follows the structure (crossview.anchor)
            def follows(a: dict) -> bool:
                return src == "person" and bool(a.get("blocked")) and all(b.get("kind") == "level" and b.get("line") not in prog.reference_only
                                                                         for b in a["blocked"])

            other = [w + ("" if any(a["policy"] == p and a["available"] for a in alts) else " (its site levels follow)")
                     for p, w in SIDE_WORDS.items() if p != pol and any(a["policy"] == p and (a["available"] or follows(a)) for a in alts)]
            instead = (f" — {' or '.join(other)} keeps what may not move (choose it to have it checked on the sheet)" if other
                       else " — no side keeps what may not move: leave it to the set-out as it stands, or release what holds it (a held part or level, "
                            "a named size on the way)")
            plan["conflicts"].append(f"anchor {pol}{about} is not possible here: {(alt or {}).get('why', 'no such line')}{instead}")
            out.update(policy=None, status="unresolved")
            return out
        out.update(policy=pol, centre=centre, status="accepted", source=src, line=alt.get("anchor_line"))
        return out
    feasible = [a for a in alts if a["available"] and a["policy"] != "as_set_out"]
    if (fixed_lines or owned) and len({(a["policy"], a.get("centre")) for a in feasible}) == 1:
        a = feasible[0]
        out.update(policy=a["policy"], centre=a.get("centre"), status="accepted", source="only feasible", line=a.get("anchor_line"))
        out["evidence"].append(f"the only policy that keeps {', '.join(sorted(fixed_lines or owned)[:4])} as they must be")
        return out
    provisional = request.get("provisional_anchor") or os.environ.get("DXF_AUTOPARAM_PROVISIONAL_ANCHOR")
    rec = next((a for a in feasible if a["policy"] == "centered" and a.get("symmetric") and "drawn" in a.get("evidence", "")), None)
    if ai_rec and ai_rec.get("policy"):
        rec = next((a for a in feasible if a["policy"] == ai_rec["policy"] and (not ai_rec.get("centre") or a.get("centre") == ai_rec["centre"])), rec)
    if provisional in POLICIES:
        a = next((x for x in alts if x["policy"] == provisional and x["available"]), None)
        if a is not None:
            out.update(policy=a["policy"], centre=a.get("centre"), status="provisional", source="provisional (configured)", line=a.get("anchor_line"))
            out["evidence"].append("a configured provisional policy: visible and reversible, not a decision")
            return out
    options = [f"{a['policy']}{' about ' + a['centre'] if a.get('centre') else ''}" for a in alts if a["available"]]
    pick = ask("anchor", f"When {name} changes, which side stays? " + "; ".join(
        f"{a['policy']}{' about ' + a['centre'] if a.get('centre') else ''}: {a['why']}"
        + (f" ({', '.join(f'{k} {v}' for k, v in list(a['parts'].items())[:4])})" if a["parts"] else "") for a in alts if a["available"]),
        options, recommended=(f"{rec['policy']}{' about ' + rec['centre'] if rec.get('centre') else ''}" if rec else None),
        why="the drawing alone does not say which side of the size is the design datum" + (
            "; the AI recommends it" if ai_rec and rec else f"; it is drawn symmetric about the centre line {rec['centre']}" if rec else ""))
    if pick:
        pol, _sep, c = pick.partition(" about ")
        alt = next((a for a in alts if a["policy"] == pol and (not c or a.get("centre") == c)), None)
        if alt and alt["available"]:
            out.update(policy=pol, centre=alt.get("centre"), status="accepted", source="person", line=alt.get("anchor_line"))
    return out


def _affected(prog: Program, plan: dict, name: str, pairs, axis: str | None, members: set[str], sheet: dict | None) -> dict:
    an = prog.analysis
    out: dict = {}
    ends = {x for p in pairs for x in p}
    dims = []
    for it in an.drawing.items:
        if it.dxftype != "DIMENSION" or not axis:
            continue
        b1, b2 = an.slot_datum.get((it.index, 1, axis)), an.slot_datum.get((it.index, 2, axis))
        if b1 and b2 and tuple(sorted((b1[0], b2[0]))) in {tuple(sorted(p)) for p in pairs}:
            dims.append(_eid(it))
    out["dimensions_on_driver"] = dims[:40]
    notes = [i for i, links in prog.text_links.items() for _t, ref, _d in links
             if ref == name or ref.startswith("len:") and set(ref[4:].split(":")) & ends]
    out["notes"] = sorted(
        {
            (an.drawing.items[i].text or "").split("\n")[0][:40]
            for i in notes
            if an.drawing.items[i].text
        }
    )[:20]
    moved_items = sorted({i for (i, _k, ax), (d, _o) in an.slot_datum.items() if ax == axis and d in members})
    if sheet and sheet.get("views_of"):
        out["views"] = sheet["views_of"](moved_items)
    if sheet and sheet.get("shared"):
        sh = sheet["shared"].get(name)
        if sh:
            out["shared_as"] = sh
            out["other_units"] = sheet["other_units"](name)
    return out


def _dependency(prog: Program, plan: dict, name: str, pairs, parts, sheet) -> list[str]:
    """The chain from the value to everything that follows it, in words a person checks against the drawing."""
    out = [f"{name} = {plan['driver']['value']:g} {plan['driver']['unit']}"
           + (f" → {plan['driver']['requested_value']:g}" if plan['driver'].get('requested_value') is not None else "")]
    out.append(f"  sets {len(pairs)} occurrence(s): " + ", ".join(f"{a}–{b}" for a, b in pairs[:8]))
    anc = plan.get("anchor") or {}
    if anc.get("policy"):
        out.append(f"  anchor: {anc['policy']}{' about its own middle' if anc.get('centre') == MID else ' about ' + anc['centre'] if anc.get('centre') else ''} ({anc.get('source')}) — "
                   + POLICY_WORDS[anc["policy"]])
    for d in plan.get("directives", []):
        if d["status"] == "accepted" and d["kind"] in ("part", "parameter", "level", "line"):
            out.append(f"  {d['target']}: {d['mode']}{' (' + d['relation'] + ')' if d.get('relation') else ''} — {MODES[d['mode']]}")
    aff = plan.get("affected", {})
    if aff.get("dimensions_on_driver"):
        out.append(f"  dimensions that read it: {', '.join(aff['dimensions_on_driver'][:8])}")
    if aff.get("notes"):
        out.append(f"  notes that state it: {'; '.join(aff['notes'][:4])}")
    if aff.get("views"):
        out.append(f"  views: {', '.join(aff['views'])}")
    if aff.get("other_units"):
        out.append(f"  shared as {aff['shared_as']} with {', '.join(aff['other_units'])}: they follow the same value")
    return out


def accept(plan: dict, by: str = "person") -> dict:
    """A plan made binding: refused while a question is open or a conflict stands; the person (or the instruction, for
    an agent's plan that needed no decision) accepts it."""
    if plan.get("status") != "ready":
        raise ValueError(f"plan {plan.get('id')} is {plan.get('status')}: "
                         + "; ".join([q["text"] for q in plan.get("questions", [])][:2] + plan.get("conflicts", [])[:2]))
    out = copy.deepcopy(plan)
    out["status"] = "accepted"
    out["accepted_by"] = by
    return out


def with_plan(answer: dict, plan: dict) -> dict:
    """The answer with this plan stored (one plan per driver: a newer plan for the same value replaces the older)."""
    out = copy.deepcopy(answer)
    drv = (plan.get("driver") or {}).get("parameter")
    out["plans"] = [p for p in out.get("plans", []) if (p.get("driver") or {}).get("parameter") != drv and p.get("id") != plan.get("id")] + [plan]
    return out


# ── compiled into the program (validator.apply calls this) ───────────────────────


def prepare_plans(prog: Program, answer: dict, parts: dict[str, Part]) -> dict:
    """First half of compiling the accepted plans, before held parts are held: which parts the plans hold (keep_fixed /
    exclude / annotations_only), the relationships they add as constraints, and — per axis — the assembly's lines and the
    lines a held part is drawn on, which the anchor must not move (worked out before holding splits them off)."""
    an = prog.analysis
    # exclude → held (its lines constants, shared lines split off: outside the edit, as built); keep_fixed and
    # annotations_only → pinned: it does not move when THIS plan's value changes, and stays parametric otherwise
    out: dict = {"hold": set(), "pin": set(), "pin_of": {}, "constraints": [], "rows": [], "groups": {}}
    plans = [p for p in answer.get("plans", []) if p.get("status") == "accepted"]
    for plan in plans:
        row = {"id": plan.get("id"), "ok": True, "problems": [], "stack": None}
        out["rows"].append(row)
        drv = plan.get("driver") or {}
        name = drv.get("parameter")
        derived = (plan.get("anchor") or {}).get("source") == "design intent"  # the engine's own: written for the parametrization of the day
        dirs = [d for d in plan.get("directives", []) if d.get("status") == "accepted"]
        for d in dirs:
            if d["kind"] == "part" and d["target"] in parts and d["mode"] in FIXED_MODES:
                if d["mode"] == "exclude":
                    out["hold"].add(d["target"])
                elif derived:  # the engine's own plan keeps a part still for ITS assembly: another assembly's value moving that part is no conflict
                    out["pin_of"].setdefault(row["id"], set()).add(d["target"])
                else:
                    out["pin"].add(d["target"])
            if d["kind"] == "part" and d["mode"] in ("no_parameter", "exclude"):
                own = [n for n, q in prog.params.items() if q.source == "ai" and q.component == d["target"] and n != name]
                if own:
                    row["problems"].append(f"{d['target']} gets no value of its own ({d['mode']}), but {', '.join(own)} is one")
            if d["mode"] == "preserve" and d.get("relation") == "connection" and d["kind"] == "part" and d.get("interface"):
                for other in d["interface"]:
                    out["constraints"].append({"type": "connected", "components": [d["target"], other], "datums": [],
                                               "description": f"{plan.get('id')}: {d['target']} stays connected to {other}", "confidence": 1.0})
        if not name or name not in prog.params:
            if not derived:  # a derived plan whose value is gone is simply not needed any more
                row["problems"].append(f"the driver {name} is not a value of the program (removed or renamed since the plan was made)")
            continue
        pairs = [cast(tuple[str, str], tuple(p)) for p in drv.get("pairs") or pairs_of(prog, answer, name)]
        extra = {tuple(p) for p in drv.get("extra_pairs") or []}  # asked for and not yet followed: the anchor's set-out makes them follow
        bad = [p for p in pairs if p[0] not in an.datums or p[1] not in an.datums]
        if bad or not pairs:
            if not derived:
                row["problems"].append(f"{name}: its occurrences {bad or 'none'} are not lines of this drawing")
            continue
        lost = drives_pairs(prog, name, [p for p in pairs if p not in extra])
        if lost:
            if not derived:
                row["problems"].append(f"{name} does not drive {', '.join(f'{a}–{b}' for a, b in lost[:4])}")
            continue
        anc = plan.get("anchor") or {}
        if prog.params[name].kind == "level" or not anc.get("policy") or anc["policy"] == "as_set_out":
            continue
        axis = an.datums[pairs[0][0]].axis
        # one anchor per assembly: the plans of separate assemblies on one axis (two views of a unit, a detail beside a section) each have their own
        grp = out["groups"].setdefault((axis, anc.get("assembly") or ""), {"items": [], "chosen": False})
        grp["items"].append((row, Driver(name, pairs, anc["policy"], anc.get("centre")), dirs))
        grp["chosen"] = grp["chosen"] or not derived  # somebody chose this side (a gap may give for it): not only the engine's default
    for (axis, _assembly), g in out["groups"].items():
        drivers = [drv for _r, drv, _d in g["items"]]
        followers = {d["target"] for _r, _drv, ds in g["items"] for d in ds if d["kind"] == "part" and d["mode"] in MOVING_MODES}
        core = set()
        for drv in drivers:
            core |= core_parts(parts, drv.pairs) if parts else set()
        pins = out["pin"] | set().union(*(out["pin_of"].get(r["id"], set()) for r, _d, _x in g["items"]))
        fixed = out["hold"] | pins
        g["members"] = assembly_lines(prog, parts if parts else None, (core | followers) if parts else None, axis,
                                      seed={x for drv in drivers for p in drv.pairs for x in p}, exclude=fixed)
        g["still"], g["pinned"] = set(), set()
        for n in fixed:
            if n in parts:
                ls = entity_lines(prog, part_entities(prog, parts, n), axis)
                g["still"] |= ls & g["members"]
                if n in pins:
                    g["pinned"] |= ls - g["members"]
    return out


def compile_plans(prog: Program, answer: dict, rep, pre: dict) -> dict:
    """Second half, after held parts are held and slopes kept: the anchor of each axis written into the set-out
    (assembly.stack: one policy per assembly and axis). Every problem is a V16 finding; the program is never left half
    rewritten (a refused stacking changes nothing)."""
    named = {n: pairs_of(prog, answer, n) for n, q in prog.params.items() if q.source in ("ai", "dimension", "person") and q.kind != "level"}
    for (axis, _assembly), g in pre["groups"].items():
        drivers = [drv for _r, drv, _d in g["items"]]
        if len({(d.policy, d.centre) for d in drivers}) > 1:
            for row, _d, _x in g["items"]:
                row["problems"].append(f"plans on the {axis} axis disagree on the anchor ({', '.join(f'{d.name}: {d.policy}' for d in drivers)})")
            continue
        st = stack(prog, axis, drivers, set(g["members"]), still=g["still"], named=named, give=g.get("chosen", True))
        pinned = _pin(prog, g.get("pinned", set()), drivers, answer) if st.ok else {}
        for row, _d, _x in g["items"]:
            row["stack"] = {"axis": axis, "policy": st.policy, "anchor_line": st.root, "rewritten": {k: v[1] for k, v in st.written.items()},
                            "by_drawn_distance": st.by_drawn_distance, "members": sorted(g["members"]), "expected": st.expected,
                            "pinned": pinned, "blocked": st.blocked[:12]}
            if not st.ok:
                row["problems"].append(f"anchor {st.policy}: {st.why}")
    for row in pre["rows"]:
        row["ok"] = not row["problems"]
        for msg in row["problems"]:
            rep.bad("plan", "V16", str(row["id"]), f"plan {row['id']}: {msg}")
    return pre


def _pin(prog: Program, lines: set[str], drivers: list[Driver], answer: dict | None = None) -> dict[str, str]:
    """A part kept fixed does not move when the plan's value changes: the lines of it that HANG on something that moves (set out from the
    assembly) are set where they are drawn, and nothing else. The lines that hang on those keep their formulas, so the part's own named
    sizes (a haunch, a thickness) still drive it: it is fixed for this edit, not frozen — and its lines on the other axis are left as they are."""
    an = prog.analysis
    u = an.drawing.units_mm
    out: dict[str, str] = {}
    v = prog.datum_values()
    drv_names = {drv.name for drv in drivers}
    # the lines of the drivers' OWN occurrences outside this assembly (a haunch of the same size in the part): the value drives them through that
    # size, so a part kept fixed against the assembly still follows it there — pinning them would take the value's own binding away
    own = {x for drv in drivers for pr in parameter_pairs(prog, answer, drv.name) if tuple(pr) not in {tuple(q) for q in drv.pairs} for x in pr}
    still: set[str] = set()  # the lines that move with the plan's values, as the set-out stands now (every line: what a line hangs on may be outside the part)
    for drv in drivers:
        still |= set(rates(prog, drv.name))
    mine = {d for drv in drivers for d, k in rates(prog, drv.name, lines).items() if abs(k) > 1e-9}
    for d in prog.order():  # parents first: a line hung on one that has just been set where it is drawn no longer moves
        if d not in still or d not in mine or d in own:
            continue
        try:
            refs = names_in(prog.formulas[d])
        except ExprError:
            refs = set()
        hangs = any(p in still for p in refs if p in prog.formulas)
        if not (hangs or refs & drv_names):
            still.discard(d)  # what it hangs on does not move any more: it stays with its formula, and its own sizes still drive it
        elif prog.origin.get(d) not in ("ai", "held", "existing", "slope"):
            prog.formulas[d] = _num(v[d] * u)
            prog.origin[d] = "plan"
            out[d] = prog.formulas[d]
            still.discard(d)
    if out:
        prog.invalidate()
    return out


# ── measured: does the regenerated drawing do what the plan says? ────────────────


def _seg_dist(p, q, r, s) -> float:
    """Shortest distance between segments p–q and r–s."""
    def pd(a, b, c):
        bx, by = b[0] - a[0], b[1] - a[1]
        L = bx * bx + by * by
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((c[0] - a[0]) * bx + (c[1] - a[1]) * by) / L))
        return math.hypot(a[0] + t * bx - c[0], a[1] + t * by - c[1])

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2, d3, d4 = cross(p, q, r), cross(p, q, s), cross(r, s, p), cross(r, s, q)
    if (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0):
        return 0.0
    return min(pd(p, q, r), pd(p, q, s), pd(r, s, p), pd(r, s, q))


def _segments(it, pts) -> list:
    if it.segments:
        return [(pts[i], pts[j]) for i, j in it.segments if i < len(pts) and j < len(pts)]
    vs = [pts[k] for k in it.vertex_pts if k < len(pts)] or pts
    return [(vs[k], vs[k + 1]) for k in range(len(vs) - 1)] or [(vs[0], vs[0])] if vs else []


def _touch(a, pa, b, pb, tol) -> bool:
    sa, sb = _segments(a, pa), _segments(b, pb)
    return any(_seg_dist(p, q, r, s) <= tol for p, q in sa for r, s in sb)


def _crosses(p, q, r, t, eps: float) -> bool:
    """Segments p–q and r–t cross at a point inside both (touching, or running along each other, is not crossing)."""
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2, d3, d4 = orient(p, q, r), orient(p, q, t), orient(r, t, p), orient(r, t, q)
    lq = math.hypot(q[0] - p[0], q[1] - p[1]) * eps
    lt = math.hypot(t[0] - r[0], t[1] - r[1]) * eps
    return ((d1 > lq and d2 < -lq) or (d1 < -lq and d2 > lq)) and ((d3 > lt and d4 < -lt) or (d3 < -lt and d4 > lt))


def clashes(prog: Program, pts: dict[int, list], moved: set[int]) -> list[tuple[int, int]]:
    """Structural entities that moved and now cross another one they did not cross as drawn (two members running
    into each other: a haunch through a wall, a cell closed up past its haunches) — what keeps a value's range honest
    where no single outline turns inside out."""
    an = prog.analysis
    items = an.drawing.items
    eps = an.drawing.tol
    struct = [it for it in items if it.role.value == "structural" and len(it.pts) > 1]

    def box(ps):
        return (min(x for x, _ in ps), min(y for _, y in ps), max(x for x, _ in ps), max(y for _, y in ps))

    after = {it.index: pts.get(it.index, it.pts) for it in struct}
    boxes = {i: box(ps) for i, ps in after.items()}
    out = []
    for i in sorted(moved):
        if i not in after:
            continue
        si, si0 = _segments(items[i], after[i]), _segments(items[i], items[i].pts)
        bi = boxes[i]
        for it in struct:
            j = it.index
            if j == i or (j in moved and j < i):
                continue
            bj = boxes[j]
            if bj[0] > bi[2] + eps or bi[0] > bj[2] + eps or bj[1] > bi[3] + eps or bi[1] > bj[3] + eps:
                continue
            sj, sj0 = _segments(it, after[j]), _segments(it, it.pts)
            if any(_crosses(p, q, r, t, eps) for p, q in si for r, t in sj) and \
                    not any(_crosses(p, q, r, t, eps) for p, q in si0 for r, t in sj0):
                out.append((i, j))
    return out


def _max_move(p0, p1) -> float:
    return max((math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(p0, p1, strict=False)), default=0.0)


def verify_plan(prog: Program, plan: dict, parts: dict[str, Part], compiled: dict | None = None, values: list[float] | None = None,
                answer: dict | None = None) -> dict:
    """Change the driver up, down, to the value asked for, and back; regenerate; measure every promise of the plan on
    the regenerated geometry — entity by entity, not by bounding boxes. Returns {ok, checks, outcomes}; every failure
    says what was expected, what was measured, the cause and what to do."""
    an = prog.analysis
    u = an.drawing.units_mm
    tol = max(an.drawing.tol * u * 2, 0.5)  # mm
    items = an.drawing.items
    drv = plan.get("driver") or {}
    name = drv.get("parameter")
    res: dict = {"id": plan.get("id"), "ok": True, "checks": [], "outcomes": []}
    if not name or name not in prog.params:
        res["ok"] = False
        res["checks"].append({"check": "driver", "target": name, "status": "fail", "expected": "a value of the program", "measured": "missing",
                              "cause": "the driver is gone", "action": "plan again"})
        return res
    P0 = prog.params[name].value
    pairs = [tuple(p) for p in drv.get("pairs") or []]
    axis = drv.get("axis")
    row = next((r for r in (compiled or {}).get("rows", []) if r["id"] == plan.get("id")), None) or {}
    stk = row.get("stack") or {}
    expected = (stk.get("expected") or {}).get(name, {})
    dirs = [d for d in plan.get("directives", []) if d.get("status") == "accepted"]
    checks: dict[tuple[str, str], dict] = {}

    def check(kind: str, target: str, ok: bool, expected_txt: str, measured_txt: str, cause: str = "", action: str = "", at: float | None = None):
        key = (kind, target)
        c = checks.get(key)
        if c is None:
            c = checks[key] = {"check": kind, "target": target, "status": "pass", "expected": expected_txt, "measured": measured_txt, "at": []}
        if at is not None:
            c["at"].append(round(at, 3))
        if not ok and c["status"] == "pass":
            c.update(status="fail", measured=measured_txt, cause=cause, action=action, failed_at=at)

    def warn(kind: str, target: str, ok: bool, expected_txt: str, measured_txt: str, cause: str = "", action: str = "", at: float | None = None):
        """A check that says, never refuses: what the engine cannot tell is wrong (an entity no part owns) is for the person to look at."""
        key = (kind, target)
        c = checks.get(key)
        if c is None:
            c = checks[key] = {"check": kind, "target": target, "status": "pass", "expected": expected_txt, "measured": measured_txt, "at": []}
        if at is not None:
            c["at"].append(round(at, 3))
        if not ok and c["status"] == "pass":
            c.update(status="warn", measured=measured_txt, cause=cause, action=action, failed_at=at)

    base = regenerate_program(prog, check=False)
    dev = max((_max_move(base.pts.get(it.index, it.pts), it.pts) for it in items if it.index in base.pts), default=0.0) * u
    check("baseline", "drawing", dev <= 1e-6 * max(1.0, u), "the formulas reproduce the drawing exactly", f"largest deviation {dev:.2e} mm",
          "the formulas do not reproduce the drawn state", "a formula's constant is wrong: rebuild the plan")
    d = delta_of(prog, name)
    tests = list(values or [])
    if not tests:
        # up by the step, down by the step but never past half the value: a 20 mm gap is not tested at -30 mm
        tests = [P0 + d, P0 - (d if prog.params[name].kind == "level" else min(d, 0.5 * abs(P0)))]
        req = drv.get("requested_value")
        if req is not None and all(abs(req - t) > 1e-9 for t in tests) and abs(req - P0) > 1e-9:
            tests.append(float(req))
    fixed_parts = [d_["target"] for d_ in dirs if d_["kind"] == "part" and d_["mode"] in FIXED_MODES and d_["target"] in parts]
    mine_pairs = {tuple(p) for p in pairs}
    driven_here = {x for pr in parameter_pairs(prog, answer, name) if tuple(pr) not in mine_pairs for x in pr}  # its occurrences outside this plan's assembly
    own = {n: part_entities(prog, parts, n) for n in parts} if parts else {}
    inside_core = set()
    for n in (plan.get("affected") or {}).get("core", []):
        if n in parts:
            inside_core |= {n} | descendants(parts, n)
    elsewhere = _sibling_parts(prog, parts, answer, name, pairs, axis, inside_core)  # moved by the value in another assembly: that plan answers for them
    directed = {d_["target"] for d_ in dirs if d_["kind"] == "part"}
    topo = of(an)
    v0 = line_values_mm(prog)
    for w in tests:
        r = regenerate_program(prog, {name: w})
        dw = w - P0
        check("regeneration", name, not r.issues, "the drawing stays valid", "; ".join(r.issues[:2]) or "valid",
              "an outline inverts or collapses at this value", "a smaller change, or the anchor / a part's behaviour is wrong", at=w)
        dv = {k: x * u for k, x in r.datum.items()}
        # the driver: every occurrence measures the new value
        for a, b in pairs:
            got = abs(dv.get(b, v0[b]) - dv.get(a, v0[a]))
            check("driver", f"{a}–{b}", abs(got - w) <= tol, f"{w:g} mm", f"{got:.1f} mm", f"{name} does not drive {a}–{b}",
                  "bind the occurrence again", at=w)
        # the anchor: the line that stays stays; every assembly line moves as the policy says
        if stk.get("anchor_line"):
            al = stk["anchor_line"]
            mv = dv.get(al, v0[al]) - v0[al]
            check("anchor", al, abs(mv) <= tol, "stays", f"moved {mv:+.1f} mm", "the anchor line is set out from something that moves",
                  "choose another anchor, or hold what it hangs on", at=w)
        off = [(x, k) for x, k in expected.items() if abs((dv.get(x, v0[x]) - v0[x]) - k * dw) > tol]
        if expected:
            check("assembly", plan.get("anchor", {}).get("policy") or "", not off, f"each line moves as {plan.get('anchor', {}).get('policy')} says",
                  "; ".join(f"{x} moved {dv.get(x, v0[x]) - v0[x]:+.1f} mm, expected {k * dw:+.1f}" for x, k in off[:3]) or "as expected",
                  "a line of the assembly is set out from something the plan does not move", "inspect the line's formula", at=w)
        moved_ents = {i for i, pts in r.pts.items() if _max_move(items[i].pts, pts) * u > tol}
        # fixed parts: every point of every entity of their own stays — except what the value itself drives there: a part drawn with an
        # occurrence of the same value (a haunch of the same size in another view) follows it through that size, and stays put against the rest
        for n in fixed_parts:
            mv = [i for i in own.get(n, ()) if i in moved_ents and not (driven_here and (entity_lines(prog, {i}, "x") | entity_lines(prog, {i}, "y")) & driven_here)]
            check("fixed", n, not mv, "every point stays", f"{len(mv)} of its entities move" if mv else "stays",
                  f"{n} is drawn on lines the change moves", "hold it (its own lines become fixed copies)", at=w)
        # values kept, levels kept, thickness / symmetry kept
        for d_ in dirs:
            t = d_["target"]
            if d_["mode"] == "keep_value" and d_["kind"] == "parameter" and t in prog.params:
                for a, b in parameter_pairs(prog, answer, t):
                    g0, g1 = abs(v0[b] - v0[a]), abs(dv.get(b, v0[b]) - dv.get(a, v0[a]))
                    check("keep_value", f"{t} {a}–{b}", abs(g1 - g0) <= tol, f"{g0:.1f} mm", f"{g1:.1f} mm",
                          f"{t}'s lines are set out from lines the change moves differently", "re-anchor, or make it an input", at=w)
            elif d_["mode"] in ("keep_fixed", "keep_value") and d_["kind"] in ("level", "line"):
                lines = [t] if d_["kind"] == "line" else [x for x, e in prog.formulas.items() if t in names_in(e)]
                for x in lines:
                    mv = dv.get(x, v0[x]) - v0[x]
                    check("keep_fixed", f"{t} ({x})", abs(mv) <= tol, "stays", f"moved {mv:+.1f} mm", f"{x} follows the change",
                          "hold the level / line", at=w)
            elif (d_["mode"] == "preserve" and d_.get("relation") == "thickness" or d_["mode"] == "keep_value" and d_["kind"] == "part") and t in parts:
                for ax in ("x", "y"):
                    ls = _part_lines_all(parts, t, ax, an)
                    if len(ls) < 2:
                        continue
                    e0 = max(v0[x] for x in ls) - min(v0[x] for x in ls)
                    e1 = max(dv.get(x, v0[x]) for x in ls) - min(dv.get(x, v0[x]) for x in ls)
                    thin = ax == _thin_axis(parts, t, v0, an)
                    if thin:
                        check("thickness", t, abs(e1 - e0) <= tol, f"{e0:.1f} mm", f"{e1:.1f} mm", f"{t}'s faces are set out from different things",
                              "set one face out from the other", at=w)
            elif d_["mode"] == "preserve" and d_.get("relation") == "symmetry" and (d_["kind"] == "line" or t in parts) \
                    and (d_["kind"] == "line" or (plan.get("anchor") or {}).get("centre") not in (None, MID)):
                # about the line itself, or (for parts) about the centre line the anchor keeps
                c = t if d_["kind"] == "line" else plan["anchor"]["centre"]
                c0, c1 = v0[c], dv.get(c, v0[c])
                if d_["kind"] == "line":
                    ms = [x for x in (stk.get("members") or []) if x != c]
                else:
                    sym = {x["target"] for x in dirs if x.get("relation") == "symmetry" and x["target"] in parts}
                    ms = sorted({ln for n in sym for ln in _part_lines_all(parts, n, axis, an)} - {c}) if axis else []
                pairs_m = [(x, y) for x in ms for y in ms if x < y and abs((v0[x] - c0) + (v0[y] - c0)) <= tol]
                broken = [(x, y) for x, y in pairs_m if abs((dv.get(x, v0[x]) - c1) + (dv.get(y, v0[y]) - c1)) > tol]
                check("symmetry", t, not broken, f"mirrored about {c}", f"{len(broken)} pair(s) no longer mirrored" if broken else "mirrored",
                      "one side moves more than the other", "anchor centered about the line", at=w)
            elif d_["mode"] == "translate" and t in parts:
                vecs = {(round((r.pts[i][0][0] - items[i].pts[0][0]) * u, 3), round((r.pts[i][0][1] - items[i].pts[0][1]) * u, 3))
                        for i in own.get(t, ()) if i in r.pts and items[i].pts}
                rigid = all(_max_move([(p[0] + vv[0] / u, p[1] + vv[1] / u) for p in items[i].pts], r.pts[i]) * u <= tol
                            for i in own.get(t, ()) if i in r.pts for vv in [next(iter(vecs))] if vecs)
                check("translate", t, len(vecs) <= 1 and rigid, "moves whole, same size", "moves whole" if rigid else "changes shape",
                      f"{t}'s lines move by different amounts", "set its lines out from one line", at=w)
            elif d_["mode"] == "resize" and t in parts and axis:
                ls = _part_lines_all(parts, t, axis, an)
                if len(ls) >= 2:
                    e0 = max(v0[x] for x in ls) - min(v0[x] for x in ls)
                    e1 = max(dv.get(x, v0[x]) for x in ls) - min(dv.get(x, v0[x]) for x in ls)
                    check("resize", t, abs(e1 - e0) > tol / 2, "changes size", f"{e0:.0f} → {e1:.0f} mm", f"{t} is not drawn across the size",
                          "it may follow instead of resizing", at=w)
        # unrelated parts: no movement unless the plan says so
        if parts:
            for n in parts:
                if (n in directed or n in inside_core or n in elsewhere or any(a in directed or a in inside_core or a in elsewhere for a in _ancestors(parts, n))
                        or any(q.parent == n for q in parts.values())):
                    continue
                mv = [i for i in own.get(n, ()) if i in moved_ents]
                if mv:
                    check("unrelated", n, False, "stays (no behaviour accepted for it)", f"{len(mv)} of its entities move",
                          f"{n} is set out from the assembly but the plan says nothing about it", "decide: follow or keep fixed", at=w)
        # connections: what touched still touches, among what moved (a tear inside the assembly, or across a 'stay connected')
        torn = []
        conn_pairs = {tuple(sorted((d_["target"], o))) for d_ in dirs if d_["mode"] in ("follow", "preserve") for o in (d_.get("interface") or [])}
        part_of = {}
        for n, ents in own.items():
            for i in ents:
                part_of.setdefault(i, n)
        for i in sorted(moved_ents):
            if items[i].role.value != "structural":
                continue
            for j in topo.connections.get(i, ()):
                if j < i and j in moved_ents or items[j].role.value != "structural":
                    continue
                if not _touch(items[i], r.pts[i], items[j], r.pts.get(j, items[j].pts), an.drawing.tol * 2):
                    torn.append((i, j))
        bad = []
        for i, j in torn:
            pa, pb = part_of.get(i), part_of.get(j)
            both_moving = pa in inside_core and pb in inside_core if parts else True
            if both_moving or (pa and pb and tuple(sorted((pa, pb))) in conn_pairs) or (pa in inside_core and pb in directed and pb not in fixed_parts):
                bad.append((i, j, pa, pb))
        check("connection", "assembly", not bad, "what touched still touches", "; ".join(
            f"{_eid(items[i])} ({pa or '-'}) no longer meets {_eid(items[j])} ({pb or '-'})" for i, j, pa, pb in bad[:3]) or
            (f"{len(torn)} contact(s) with fixed parts released, as the plan says" if torn else "all contacts kept"),
            "an end that should follow its neighbour is set out from something else", "set the end out from the face it meets", at=w)
        cl = clashes(prog, r.pts, moved_ents)
        # two members of the structure running into each other cannot be drawn; a crossing with an entity no part owns may be a detail that
        # should follow (or something the member must not reach): the engine cannot tell — said, for the person, never a refusal of the plan
        owned = [(i, j) for i, j in cl if part_of.get(i) and part_of.get(j)]
        loose = [(i, j) for i, j in cl if not (part_of.get(i) and part_of.get(j))]
        check("clash", "members", not owned, "no member runs into another",
              "; ".join(f"{_eid(items[i])} ({part_of.get(i, '-')}) crosses {_eid(items[j])} ({part_of.get(j, '-')})" for i, j in owned[:3]) or "none",
              "the value takes the assembly past where its members fit together", "a value inside the valid range", at=w)
        warn("clash", "unowned", not loose, "nothing runs into an entity no part owns",
             "; ".join(f"{_eid(items[i])} ({part_of.get(i, '-')}) crosses {_eid(items[j])} ({part_of.get(j, '-')})" for i, j in loose[:3]) or "none",
             "an entity no part owns is in the way: it may be a detail that should follow, or something the member must not reach",
             "say which part it is (define_parts) to have it checked", at=w)
        # dimensions and notes
        dims_out = []
        for it in items:
            if it.dxftype != "DIMENSION" or it.index not in r.pts or len(it.pts) < 3:
                continue
            p1, p2 = it.pts[1], it.pts[2]
            q1, q2 = r.pts[it.index][1], r.pts[it.index][2]
            horiz = abs(p2[0] - p1[0]) >= abs(p2[1] - p1[1])
            m0 = abs((p2[0] - p1[0]) if horiz else (p2[1] - p1[1])) * u
            m1 = abs((q2[0] - q1[0]) if horiz else (q2[1] - q1[1])) * u
            if abs(m1 - m0) > tol:
                dims_out.append((_eid(it), round(m0, 1), round(m1, 1)))
            b = (an.slot_datum.get((it.index, 1, "x" if horiz else "y")), an.slot_datum.get((it.index, 2, "x" if horiz else "y")))
            if b[0] and b[1] and tuple(sorted((b[0][0], b[1][0]))) in {tuple(sorted(p)) for p in pairs}:
                check("dimension", _eid(it), abs(m1 - w) <= tol, f"reads {w:g}", f"reads {m1:.1f}", "the dimension's points are not on the lines",
                      "re-attach it", at=w)
        notes = [(_eid(items[i]), items[i].text, t) for i, t in r.texts.items() if t != items[i].text]
        res["outcomes"].append({"value": round(w, 3), "change": round(dw, 3), "entities_moved": len(moved_ents),
                                "parts": _part_outcome(parts, own, r, items, u, tol) if parts else {},
                                "dimensions_changed": dims_out[:30], "notes_changed": [f"{e}: {a!r} → {b!r}" for e, a, b in notes[:12]],
                                "moved": sorted(moved_ents)})
    back = regenerate_program(prog, {name: P0}, check=False)
    dev2 = max((_max_move(base.pts[i], back.pts.get(i, base.pts[i])) for i in base.pts), default=0.0) * u
    check("restore", name, dev2 <= 1e-6 * max(1.0, u), "back to the drawing exactly", f"largest deviation {dev2:.2e} mm",
          "the program is not a function of its values", "report this: it is an engine fault", at=P0)
    # every named value still drives what it is bound to (a plan must not take another input's lines)
    for n, q in prog.params.items():
        if q.source != "ai" or n == name or q.kind == "level":
            continue
        lost = drives_pairs(prog, n, parameter_pairs(prog, answer, n))
        check("binding", n, not lost, "still drives its lines", f"no longer drives {', '.join(f'{a}–{b}' for a, b in lost[:3])}" if lost else "drives",
              f"the plan's set-out took {n}'s lines", "re-anchor so both can hold, or make one a result")
    res["checks"] = list(checks.values())
    res["ok"] = all(c["status"] in ("pass", "warn") for c in res["checks"])
    res["summary"] = {"passed": sum(c["status"] == "pass" for c in res["checks"]), "failed": sum(c["status"] == "fail" for c in res["checks"]),
                      "warned": sum(c["status"] == "warn" for c in res["checks"]), "values_tested": [round(t, 3) for t in tests]}
    return res


def _eid(it) -> str:
    from .cadjson import entity_id

    return entity_id(it)


def _part_lines_all(parts: dict[str, Part], n: str, axis: str, an) -> set[str]:
    names = {n} | descendants(parts, n)
    out = set()
    for m in names:
        if m in parts:
            out |= {d for d in parts[m].datums if d in an.datums and an.datums[d].axis == axis}
    return out


def _thin_axis(parts: dict[str, Part], n: str, v0: dict[str, float], an) -> str:
    ext = {}
    for ax in ("x", "y"):
        ls = _part_lines_all(parts, n, ax, an)
        ext[ax] = (max(v0[x] for x in ls) - min(v0[x] for x in ls)) if len(ls) >= 2 else math.inf
    return "x" if ext["x"] <= ext["y"] else "y"


def _part_outcome(parts, own, r, items, u, tol) -> dict[str, str]:
    out = {}
    for n, ents in own.items():
        pts0 = [p for i in ents for p in items[i].pts]
        pts1 = [p for i in ents if i in r.pts for p in r.pts[i]]
        if not pts0 or len(pts0) != len(pts1):
            continue
        w0 = (max(p[0] for p in pts0) - min(p[0] for p in pts0)) * u
        w1 = (max(p[0] for p in pts1) - min(p[0] for p in pts1)) * u
        h0 = (max(p[1] for p in pts0) - min(p[1] for p in pts0)) * u
        h1 = (max(p[1] for p in pts1) - min(p[1] for p in pts1)) * u
        mv = max(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(pts0, pts1, strict=True)) * u
        words_ = []
        if abs(w1 - w0) > tol:
            words_.append(f"width {w0:.0f} → {w1:.0f}")
        if abs(h1 - h0) > tol:
            words_.append(f"height {h0:.0f} → {h1:.0f}")
        if not words_ and mv > tol:
            words_.append(f"moves {mv:.0f} mm, same size")
        if words_:
            out[n] = ", ".join(words_)
    return out


def plan_errors_at(prog: Program, plans: list[dict], values: dict[str, float]) -> list[str]:
    """The plans' promises at the values a person sets (slider edits): the cheap, line-level part of the verification —
    fixed levels and lines stay, kept values stay, the driver's occurrences measure it."""
    an = prog.analysis
    u = an.drawing.units_mm
    tol = max(an.drawing.tol * u * 2, 0.5)
    try:
        dv0 = {k: x * u for k, x in prog.datum_values().items()}
        dv = {k: x * u for k, x in prog.datum_values(values).items()}
    except (ExprError, KeyError, ZeroDivisionError) as exc:
        return [f"cannot evaluate: {exc}"]
    out = []
    for plan in plans:
        if plan.get("status") != "accepted":
            continue
        drv = plan.get("driver") or {}
        name = drv.get("parameter")
        for d in plan.get("directives", []):
            if d.get("status") != "accepted":
                continue
            t = d["target"]
            if d["mode"] in ("keep_fixed", "keep_value") and d["kind"] in ("level", "line") and t not in values:
                # a person may still change the level itself: the promise is that OTHER changes leave it where it is
                lines = [t] if d["kind"] == "line" else [x for x, e in prog.formulas.items() if t in names_in(e)]
                for x in lines:
                    if x in dv and abs(dv[x] - dv0[x]) > tol:
                        out.append(f"plan {plan.get('id')}: {x} ({t}) must stay, moves {dv[x] - dv0[x]:+.1f} mm")
        if name in prog.params:
            w = values.get(name, prog.params[name].value)
            for a, b in [tuple(p) for p in drv.get("pairs") or []]:
                if a in dv and b in dv and abs(abs(dv[b] - dv[a]) - w) > tol and name in values:
                    out.append(f"plan {plan.get('id')}: {a}–{b} measures {abs(dv[b] - dv[a]):.1f} mm, not {w:g}")
    return out


__all__ = [
    "MODES",
    "accept",
    "build_plan",
    "clashes",
    "compile_plans",
    "plan_errors_at",
    "prepare_plans",
    "protected_lines",
    "read_instruction",
    "resolve",
    "verify_plan",
    "vocabulary",
    "with_plan",
]
