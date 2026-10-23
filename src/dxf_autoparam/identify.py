"""What a drawing's own words say it is — read line by line from a vocabulary, each finding with the words and where they are printed.

Generic: nothing here knows a kind of structure, a crossing or what a structure carries. A vocabulary (library data:
`knowledge/library/<domain>/identify.json`) names the kinds and the words that mean them, the words that set a look-alike aside, the status
words (existing, proposed …), how a carried line is named and counted, the count words, the repeat statements ("n × a × b"), and the facts a
sheet is known by. This module matches, weighs and counts:

  • a line printed in the title block or a table, or larger than the sheet's usual text, says more than a label in a view;
  • the status of a finding is the status word nearest before it on its line (after it when there is none before);
  • each carried line named on the sheet (its centre line labelled) is one, per status said — two labels of one line are one;
  • a repeat statement is read with the kind on its line ("1 × 4.00 × 2.56 m" of what).

Nothing read here is a value of the drawing: it is evidence for the model to confirm on the drawing, and what the library holds for a kind is
context with its own status.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from functools import lru_cache

TEXT_TYPES = ("TEXT", "MTEXT", "ATTRIB")
WHERE_WEIGHT = {"title_block": 2.0, "table": 2.0}  # the sheet's statements about itself
LARGE = 1.4  # a text this many times the sheet's median height reads as a title
EVIDENCE = 3  # evidence lines kept per finding


@dataclass(frozen=True)
class Line:
    text: str  # upper case, spaces collapsed
    id: str  # the entity the line is printed by
    unit: str | None
    view: str
    where: str  # the kind of layout group it is in (view, table, notes, title_block, label), "" when not known
    weight: float

    def evidence(self) -> dict:
        return {"text": self.text[:120], "id": self.id, **({"unit": self.unit} if self.unit else {}), **({"where": self.where} if self.where else {})}


def placed_texts(items, layout=None, unit_of_view: dict[str, str] | None = None) -> list[dict]:
    """Each printed text with its entity id, its height, the layout group it is in and that group's kind, and the unit the group is a view of."""
    from .cadjson import entity_id

    group = layout.item_group if layout is not None else {}
    kinds = {g.id: g.kind for g in layout.groups} if layout is not None else {}
    out = []
    for it in items:
        t = (getattr(it, "text", None) or "").strip()
        if not t or getattr(it, "dxftype", "") not in TEXT_TYPES:
            continue
        g = group.get(it.index, "")
        out.append({"text": t, "id": entity_id(it), "height": float(it.text_height or 0.0), "view": g, "where": kinds.get(g, ""),
                    "unit": (unit_of_view or {}).get(g)})
    return out


def lines_of(texts: list[dict], split: bool = True) -> list[Line]:
    """Each printed line (`split`), or each text whole with its lines joined (a label broken over two lines is one name)."""
    heights = [t["height"] for t in texts if t.get("height")]
    median = statistics.median(heights) if heights else 0.0
    out = []
    for t in texts:
        w = WHERE_WEIGHT.get(t.get("where") or "", 1.0) * (1.5 if median and (t.get("height") or 0.0) >= LARGE * median else 1.0)
        parts = re.split(r"\n|\\P", t["text"])
        for part in parts if split else [" ".join(parts)]:
            s = " ".join(part.upper().split())
            if s:
                out.append(Line(s, t.get("id", ""), t.get("unit"), t.get("view", ""), t.get("where", ""), w))
    return out


@lru_cache(maxsize=512)
def _rx(p: str) -> re.Pattern:
    return re.compile(p, re.IGNORECASE)


def _any(patterns, s: str):
    return next((m for p in patterns or () for m in [_rx(p).search(s)] if m), None)


class _Status:
    def __init__(self, entries: list[dict]):
        self.entries = entries

    def marks(self, s: str) -> list[tuple[int, str]]:
        return sorted((m.start(), e["id"]) for e in self.entries for p in e.get("words", []) for m in _rx(p).finditer(s))

    def at(self, s: str, pos: int) -> str | None:
        """The status word nearest before `pos` on the line, else the nearest after it, else none said."""
        marks = self.marks(s)
        before = [k for at, k in marks if at <= pos]
        if before:
            return before[-1]
        after = [k for at, k in marks if at > pos]
        return after[0] if after else None


def _kinds(lines: list[Line], entries: list[dict], status: _Status) -> tuple[list[dict], list[dict]]:
    """Each kind with its score (the weights of the lines naming it), split by status, with evidence; and what was set aside as a look-alike."""
    found: dict[str, dict] = {}
    aside = []
    for ln in lines:
        for e in entries:
            m = _any(e.get("words"), ln.text)
            if m is None or (e.get("context") and not _rx(e["context"]).search(ln.text)):
                continue
            why = _any(e.get("lookalike"), ln.text)
            if why is not None:
                aside.append({"kind": e["id"], "text": ln.text[:100], "id": ln.id, "because": why.group(0)})
                continue
            row = found.setdefault(e["id"], {"id": e["id"], "label": e.get("label", e["id"]), **({"graded": e["graded"]} if e.get("graded") else {}),
                                             "score": 0.0, "status": {}, "evidence": []})
            st = status.at(ln.text, m.start()) or "unsaid"
            row["score"] += ln.weight
            row["status"][st] = round(row["status"].get(st, 0.0) + ln.weight, 2)
            if len(row["evidence"]) < EVIDENCE and all(x["text"] != ln.text[:120] for x in row["evidence"]):
                row["evidence"].append({**ln.evidence(), "status": st})
    refined = {e["id"] for e in entries if e["id"] in found and any(x in found for x in e.get("refined_by", ()))}  # "25 t" where "25 t-2008" is read
    rows = sorted((r for k, r in found.items() if k not in refined), key=lambda r: (-r["score"], r["id"]))
    for r in rows:
        r["score"] = round(r["score"], 2)
    return rows, aside[:6]


def _metres(v: str, unit: str | None, default_m: bool) -> float:
    x = float(v)
    return x / 1000.0 if unit == "MM" or (not unit and not default_m) or (not unit and x > 100) else x


def _spans(lines: list[Line], spec: dict, kinds: list[dict], status: _Status) -> list[dict]:
    out = []
    cap_n, cap_m = int(spec.get("max_count", 30)), float(spec.get("max_metres", 200))
    for ln in lines:
        hits = []
        if spec.get("repeat"):
            for m in _rx(spec["repeat"]).finditer(ln.text):
                n = int(m.group("n"))
                ua = (m.group("ua") or m.group("ub") or "").upper() or None
                a = _metres(m.group("a"), ua, True)
                b = _metres(m.group("b"), (m.group("ub") or ua or "").upper() or None, True) if m.group("b") else None
                if 1 <= n <= cap_n and 0 < a <= cap_m and (b is None or 0 < b <= cap_m) and (ua or "." in m.group("a") or b is not None):
                    hits.append((m, {"count": n, "span_m": round(a, 4), **({"height_m": round(b, 4)} if b is not None else {})}))
        if spec.get("single"):
            for m in _rx(spec["single"]).finditer(ln.text):
                a = _metres(m.group("a"), (m.group("ua") or "").upper() or None, True)
                if 0 < a <= cap_m:
                    hits.append((m, {"count": 1, "span_m": round(a, 4)}))
        for m, row in hits:
            km = next(((k, mm) for k in kinds for mm in [_any(k.get("words"), ln.text)] if mm), None)
            out.append({**row, **({"kind": km[0]["id"]} if km else {}), "status": status.at(ln.text, m.start()) or "unsaid", "text": ln.text[:120], "id": ln.id})
    # one row per statement: the same sizes said again (another view, the title block) are one, under the kind and status they were said with
    keep: list[dict] = []
    for r in sorted(out, key=lambda r: ("kind" not in r, r["status"] == "unsaid")):
        same = [x for x in keep if (x["count"], x["span_m"], x.get("height_m")) == (r["count"], r["span_m"], r.get("height_m"))]
        if not same or ("kind" in r and all(x.get("kind") != r["kind"] for x in same)):  # new sizes, or the same sizes said of another kind
            keep.append(r)
    return keep[:8]


def _carried(lines: list[Line], spec: dict, status: _Status) -> dict:
    """Each carried line named on the sheet (its centre line labelled), counted per status said; the count words; kinds; spacings."""
    named: dict[str, dict] = {}
    for ln in lines:
        m = _rx(spec["line"]).search(ln.text) if spec.get("line") else None
        if m is None:
            continue
        name = m.group("name").strip(" .:-")
        if not _rx(spec.get("name_has", ".")).search(name) or _any(spec.get("name_not"), name):
            continue
        st = status.at(name, 0) or "unsaid"
        key = name
        for e in status.entries:
            for p in e.get("words", []):
                key = _rx(p).sub(" ", key)
        for pat, rep in spec.get("aliases", []):
            key = _rx(pat).sub(rep, key)
        key = " ".join(re.sub(r"[^\w ]", " ", key).split()) or "?"
        row = named.setdefault(key, {"name": key, "status": {}, "evidence": []})
        row["status"][st] = row["status"].get(st, 0) + 1
        if len(row["evidence"]) < 2:
            row["evidence"].append({**ln.evidence(), "status": st})
    # one per status said; a name said with no status is one; a bare name ("the line") stands for one of the named ones when there are any
    bare = {k for k in named if len(k.split()) == 1}
    counted = []
    for k, r in named.items():
        said = [s for s in r["status"] if s != "unsaid"]
        for s in said or ["unsaid"]:
            counted.append((k, s))
    if bare and len(named) > len(bare):
        covered = {s for k, s in counted if k not in bare}
        counted = [(k, s) for k, s in counted if k not in bare or (s not in covered and s != "unsaid")]
    by: dict[str, int] = {}
    for _k, s in counted:
        by[s] = by.get(s, 0) + 1
    words = []
    for c in spec.get("configurations", []):
        for ln in lines:
            if _any(c.get("words"), ln.text):
                words.append({"id": c["id"], "count": int(c["count"]), "label": c.get("label", c["id"]), **ln.evidence()})
                break
    n_named = len(counted)
    n_words = max((w["count"] for w in words), default=0)
    n = max(n_named, n_words)
    conf = next((c for c in spec.get("configurations", []) if int(c["count"]) == n), None)
    kinds = []
    for k in spec.get("kinds", []):
        ln = next((x for x in lines if _any(k.get("words"), x.text)), None)
        if ln is not None:
            kinds.append({"id": k["id"], "label": k.get("label", k["id"]), **ln.evidence()})
    spacing = []
    if spec.get("spacing"):
        for ln in lines:
            for m in _rx(spec["spacing"]).finditer(ln.text):
                spacing.append({"m": round(_metres(m.group("v"), (m.group("u") or "").upper() or None, "." in m.group("v")), 4), **ln.evidence()})
    return {"label": spec.get("label", "lines"), "count": n, "named": n_named, "by_status": by,
            "lines": [{"name": r["name"], "status": sorted(r["status"]), "evidence": r["evidence"]} for r in named.values()][:8],
            **({"configuration": {"id": conf["id"], "label": conf.get("label", conf["id"]), "count": n,
                                  "from": "named and stated" if n_named and n_words == n_named else "named" if n_named >= n_words else "stated"}}
               if conf else {}),
            "words": words[:4], "kinds": kinds[:3], "spacing": spacing[:4]}


def _facts(lines: list[Line], entries: list[dict]) -> dict:
    out = {}
    for e in entries:
        vals: dict[str, dict] = {}
        for ln in lines:
            for m in _rx(e["pattern"]).finditer(ln.text):
                v = " ".join(m.group("v").split())
                row = vals.setdefault(v, {"value": v, "n": 0, "weight": 0.0, "evidence": []})
                row["n"] += 1
                row["weight"] += ln.weight
                if len(row["evidence"]) < 2:
                    row["evidence"].append(ln.evidence())
        if vals:
            out[e["id"]] = {"label": e.get("label", e["id"]),
                            "values": sorted(vals.values(), key=lambda r: (-r["weight"], -r["n"], r["value"]))[:5]}
    return out


def _summary(kinds, crossings, carried, spans, loading, facts) -> str:
    parts = []

    def dims(s: dict) -> str:
        return f"{s['count']} × {s['span_m']:g}{' × ' + format(s['height_m'], 'g') if s.get('height_m') else ''} m"

    def label(r: dict) -> str:
        said = sorted((k for k in r["status"] if k != "unsaid"), key=lambda k: -r["status"][k])
        size = next((s for s in spans if s.get("kind") == r["id"]), None)
        return f"{' and '.join(said) + ' ' if said else ''}{r['label']}{' ' + dims(size) if size else ''}"

    if kinds:
        parts.append(label(kinds[0]) + "".join(f"; also {label(r)}" for r in kinds[1:3] if r["score"] >= 0.25 * kinds[0]["score"]))
    loose = [s for s in spans if "kind" not in s and not any(t.get("kind") and (t["count"], t["span_m"]) == (s["count"], s["span_m"]) for t in spans)]
    if loose:
        parts.append("span " + ", ".join(f"{dims(s)}{'' if s['status'] == 'unsaid' else ' (' + s['status'] + ')'}" for s in loose[:2]))
    if crossings:
        parts.append(f"over / under: {crossings[0]['label']}")
    if carried.get("count"):
        by = ", ".join(f"{v} {k}" for k, v in sorted(carried["by_status"].items()) if k != "unsaid")
        conf = carried.get("configuration", {}).get("label")
        parts.append(f"{carried['count']} {carried['label']}{' (' + by + ')' if by else ''}{' — ' + conf if conf else ''}")
    if loading:
        parts.append(loading[0]["label"])
    for k in ("number", "chainage"):
        if k in facts:
            parts.append(f"{facts[k]['label']} {facts[k]['values'][0]['value']}")
    return "; ".join(parts) or "nothing in the printed words names what this is"


def read(texts: list[dict], vocab: dict) -> dict:
    """The reading of these printed texts with this vocabulary."""
    lines = lines_of(texts)
    status = _Status(vocab.get("status", []))
    kinds, aside = _kinds(lines, vocab.get("kinds", []), status)
    crossings, _ = _kinds(lines, vocab.get("crossings", []), status)
    foundations, _ = _kinds(lines, vocab.get("foundations", []), status)
    loading, _ = _kinds(lines, vocab.get("loading", []), status)
    carried = _carried(lines_of(texts, split=False), vocab.get("carried", {}), status) if vocab.get("carried") else {}
    spans = _spans(lines, vocab.get("spans", {}), vocab.get("kinds", []), status) if vocab.get("spans") else []
    facts = _facts(lines, vocab.get("facts", []))
    return {"reading": _summary(kinds, crossings, carried, spans, loading, facts), "kinds": kinds[:5], "set_aside": aside, "crossings": crossings[:3],
            "foundations": foundations[:3], "carried": carried, "spans": spans, "loading": loading[:3], "facts": facts, "lines_read": len(lines)}


def main_kind(reading: dict) -> dict | None:
    """The kind the drawing's work is about: the best one said proposed (or with no status), else the best one."""
    kinds = reading.get("kinds") or []
    work = [k for k in kinds if any(s in k["status"] for s in ("proposed", "extension", "unsaid"))]
    return (work or kinds or [None])[0]


def relations_for(relations: list[dict], count: int) -> list[dict]:
    """The configuration relations with this count written in (each names its count: `count_name`): "(n - 1) * c" with n = 2 reads "1 * c"."""
    out = []
    for r in relations:
        expr = re.sub(rf"\b{re.escape(r.get('count_name', 'count'))}\b", str(count), r["expression"])
        expr = re.sub(r"\((\d+)\s*-\s*(\d+)\)", lambda m: str(int(m.group(1)) - int(m.group(2))), expr)
        out.append({**r, "for_this_drawing": expr})
    return out
