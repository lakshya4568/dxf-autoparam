"""Build the RDSO RCC Box Standards Knowledge Sheet from the page extracts of five standard drawing sets.

    uv run python -I tools/build_rdso_sheet.py [--src <extracts/rcc-box>] [--raw <raw/rcc-box>] [--out src/dxf_autoparam/knowledge/library/bridge/rdso]

Reads only (never writes) the extracts made by the grounding agent in Aagento-GAD-Foundation-Model
(`knowledge/sources/rdso/extracts/rcc-box/<doc>/p<N>.json`, read by eye from the RDSO PDFs) and writes:

    <out>/rdso_rcc_box_standards.json   the sheet: one record per standard, every value with its sheet, page, table, row and column
    <out>/RDSO_RCC_BOX_STANDARDS.md      the same, readable
    <out>/rdso_rcc_box_index.json        the retrieval index (component-oriented; what the agent and the template read)
    <out>/sources.json                   sha256 of every extract file and source PDF used

Nothing is added from engineering knowledge: a value is in the sheet only when an extract prints it. Each item carries a `kind`:
explicit (printed on the RDSO sheet), derived (follows mathematically from printed notations), unverified (printed but flagged unclear or
on a page the extraction did not check, or a page the extraction says not to use). Implementation rules and engineer choices are not RDSO
content: the template records them itself (template/rcc_box_template.json) and points here.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_SRC = Path("/Users/proximus/Documents/Aagento Systems/Aagento-GAD-Foundation-Model/knowledge/sources/rdso/extracts/rcc-box")
DEFAULT_KB = Path("/Users/proximus/Documents/Aagento Systems/Aagento-GAD-Foundation-Model/knowledge/kb/entries")
DEFAULT_RAW = Path("/Users/proximus/Documents/Aagento Systems/Aagento-GAD-Foundation-Model/knowledge/sources/rdso/raw/rcc-box")

# The standards of the sheet, one row each in the manifest (the five of the first iteration). `parts` are the extract folders that hold the set
# (a set split over two PDFs has two). `verification` is the extraction's own status (agent/out/file-status/<folder>/STATUS.md), copied so a reader
# knows what was checked.
MANIFEST =Path(__file__).resolve().parents[1] / "src" / "dxf_autoparam" / "knowledge" / "library" / "bridge" / "rdso" / "standards.json"


def load_standards(path: Path = MANIFEST) -> list[dict]:
    """The sets of the sheet, from the manifest (adding a set is adding a row there): a part's spot-checked pages are numbers, as JSON keeps them as text."""
    rows = json.loads(path.read_text(encoding="utf-8"))["standards"]
    for std in rows:
        for part in std["parts"]:
            part["spot_checked"] = {int(k): list(v) for k, v in (part.get("spot_checked") or {}).items()}
    return rows


STANDARDS = load_standards()

KINDS = {
    "explicit": "Printed on the RDSO sheet and read from a displayed image of it (verification level says whether it was re-checked).",
    "derived": "Follows mathematically from printed notations or tables (the derivation is written out); not printed as such.",
    "unverified": "Printed, but the extraction marks it unclear, or it is on a page the extraction did not check, or the extraction says not to use it.",
    "implementation": "A rule of an existing implementation (aagento-bridge production code, this template): not RDSO content; recorded in the template.",
    "engineer": "A design choice an engineer makes and can change: not RDSO content; recorded in the template and in each bridge's config.",
}

BAR_MARKS = ("a1", "a2", "b", "c", "d", "e", "f1", "f2", "g1", "g2", "g3", "h")
CFG = re.compile(r"(\d+(?:\.\d+)?)\s*m?\s*[xX×]\s*(\d+(?:\.\d+)?)\s*m", re.IGNORECASE)
FILL_AFTER = re.compile(r"FILL\s*(?:HEIGHT|DEPTH)\s*=?\s*(\d+(?:\.\d+)?)\s*m", re.IGNORECASE)
FILL_BEFORE = re.compile(r"(\d+(?:\.\d+)?)\s*m\s*FILL\s*(?:HEIGHT|DEPTH)", re.IGNORECASE)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_cfg(label: str) -> tuple[float, float] | None:
    m = CFG.search(label or "")
    return (float(m.group(1)), float(m.group(2))) if m else None


def cfg_key(span: float, height: float) -> str:
    return f"{span:g}mX{height:g}m"


def parse_fill(text: str) -> float | None:
    """'... FOR 1.0m FILL HEIGHT' or 'FILL DEPTH = 0.5m' or a column '1mX1.2m FILL HEIGHT 0.0m' (the configuration's own size is never read as a fill)."""
    t = CFG.sub(" ", text or "")
    m = FILL_AFTER.search(t) or FILL_BEFORE.search(t)
    return float(m.group(1)) if m else None


def parse_thk(cell: str) -> tuple[float | None, str | None]:
    """'35cm' -> 350 mm. A cell printed without its 'c' (the extraction recorded '50m' as printed) is read as cm and flagged."""
    s = (cell or "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*cm", s, re.IGNORECASE)
    if m:
        return float(m.group(1)) * 10.0, None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*m", s, re.IGNORECASE)
    if m and float(m.group(1)) >= 20:
        return float(m.group(1)) * 10.0, f"printed '{s}' (no 'c'); read as cm like every other cell of the row"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*mm", s, re.IGNORECASE)
    if m:
        return float(m.group(1)), None
    return None, f"not a thickness: '{s}'" if s else "empty cell"


def parse_pressure(cell: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)", cell or "")
    return float(m.group(1)) if m else None


def parse_bar(cell: str) -> dict:
    out: dict = {"printed": cell}
    m = re.search(r"(\d+)\s*mm\s*DIA\s*@\s*(\d+)\s*mm", cell or "", re.IGNORECASE)
    if m:
        out["dia_mm"], out["spacing_mm"] = int(m.group(1)), int(m.group(2))
    return out


def row_item(label: str, group: str = "") -> str | None:
    """Normalise a schedule row label to an item key."""
    lab = re.sub(r"^\s*\d+\.\s*", "", (label or "")).strip()
    g = (group or "").strip().lower()
    low = lab.lower()
    if low in BAR_MARKS:
        return low
    if low.replace(" ", "") in ("g1,g2,g3", "g1,g2&g3"):
        return "g"
    if "thickness of slabs" in low:
        return "thickness_all"
    if low.startswith("top slab") or (g == "thickness" and "top" in low):
        return "top_slab"
    if low.startswith("bottom slab") or (g == "thickness" and "bottom" in low):
        return "bottom_slab"
    if low.startswith("side wall") or (g == "thickness" and "side" in low):
        return "side_walls"
    if "foundation pressure" in low or "foundation pressure" in g:
        return "pressure"
    if "weight" in low or "weight" in g:
        return "weight"
    return None


class Page:
    def __init__(self, std: dict, part: dict, path: Path):
        self.std, self.part, self.path = std, part, path
        self.j = json.loads(path.read_text())
        self.no = int(self.j["page"])
        self.drawing = (self.j.get("drawing_no_printed") or "").strip()
        self.title = (self.j.get("title_printed") or "").strip()
        self.unclear = list(self.j.get("unclear") or [])
        self.not_read = list(self.j.get("not_read") or [])

    @property
    def ref(self) -> dict:
        return {"pdf": self.part["pdf"], "extract": f"{self.part['folder']}/{self.path.name}", "page": self.no, "drawing": self.drawing}

    def level(self, cfg: str | None = None) -> tuple[str, str]:
        """(kind, verification) of a value on this page."""
        if self.no in self.part["do_not_use_pages"]:
            return "unverified", "the extraction says not to use this page until it is re-read"
        if self.part.get("unchecked"):
            return "unverified", "partly read set: nothing on it was checked against the drawing"
        if any(("EVERY NUMBER" in u.upper() or "ALL CELL VALUES" in u.upper()) for u in self.unclear):
            return "unverified", "the extraction says every number on this page is provisional (soft scan)"
        if self.no in self.part["checked_pages"]:
            return "explicit", "checked against the displayed drawing"
        if cfg and cfg in self.part["spot_checked"].get(self.no, []):
            return "explicit", "spot-checked against the displayed drawing"
        return "explicit", "transcribed by eye from displayed tiles; not re-checked"


def schedule_tables(page: Page) -> list[dict]:
    """Every schedule configuration on a page: [{config, span_m, height_m, fill_m, items{...}, src{...}}]."""
    out: list[dict] = []
    page_fill = parse_fill(page.title)
    for ti, t in enumerate(page.j.get("tables") or []):
        cols = t.get("columns") or []
        rows = t.get("rows") or []
        title = t.get("title_printed") or ""
        table_fill = parse_fill(title)
        cfg_rows = next((i for i, c in enumerate(cols) if "CONFIGURATION" in str(c).upper() and "SPAN" in str(c).upper()), None)
        if cfg_rows is not None:  # one configuration per row (the 10155 transcription)
            for ri, r in enumerate(rows):
                sh = parse_cfg(r[cfg_rows] if cfg_rows < len(r) else "")
                if not sh:
                    continue
                items: dict = {}
                for ci, c in enumerate(cols):
                    if ci == cfg_rows or ci >= len(r):
                        continue
                    key = row_item(str(c))
                    if key:
                        items[key] = r[ci]
                out.append({"label": r[cfg_rows], "shape": sh, "fill": table_fill if table_fill is not None else page_fill, "items": items,
                            "src": {**page.ref, "table": ti, "table_title": title, "row": ri}})
            continue
        group_col = 1 if len(cols) > 1 and str(cols[0]).lower() == "group" else None
        first_cfg = 2 if group_col else 1
        for ci in range(first_cfg, len(cols)):
            sh = parse_cfg(str(cols[ci]))
            if not sh:
                continue
            fill = parse_fill(str(cols[ci]))
            items = {}
            for r in rows:
                if not r:
                    continue
                key = row_item(r[1] if group_col else r[0], r[0] if group_col else "")
                if key and ci < len(r):
                    items[key] = r[ci]
            if not items:
                continue
            out.append({"label": str(cols[ci]), "shape": sh, "fill": fill if fill is not None else (table_fill if table_fill is not None else page_fill), "items": items,
                        "src": {**page.ref, "table": ti, "table_title": title, "column": ci}})
    return out


def normalise_config(raw: dict, page: Page) -> dict:
    span, height = raw["shape"]
    key = cfg_key(span, height)
    kind, ver = page.level(key)
    items = raw["items"]
    flags: list[str] = []
    rec: dict = {"config": key, "printed": raw["label"], "span_m": span, "height_m": height}
    thk = {}
    for name in ("top_slab", "bottom_slab", "side_walls"):
        cell = items.get(name, items.get("thickness_all"))
        if cell is None:
            continue
        mm, flag = parse_thk(str(cell))
        thk[name] = {"mm": mm, "printed": cell}
        if flag:
            flags.append(f"{name}: {flag}")
    rec["thickness"] = thk
    if "pressure" in items:
        rec["max_foundation_pressure_kN_m2"] = parse_pressure(str(items["pressure"]))
        rec["pressure_printed"] = items["pressure"]
    if "weight" in items and str(items["weight"]).strip():
        rec["segment_weight_printed"] = items["weight"]
    bars = {}
    for mark in BAR_MARKS:
        if mark in items:
            bars[mark] = parse_bar(str(items[mark]))
    if "g" in items:
        bars["g1/g2/g3"] = parse_bar(str(items["g"]))
    rec["bars"] = bars
    field_kind = {"thickness": kind, "pressure": kind, "bars": kind}
    for u in unclear_for(page, key, raw.get("fill")):
        flags.append(u)
        up = u.upper()
        hit = [f for f, words in (("thickness", ("SLAB", "WALL", "THICK", "CM")), ("pressure", ("PRESSURE", "KN")), ("bars", ("DIA", "MARK", "ROW", "BAR", "BARELL")))
               if any(w in up for w in words)]
        for f in hit or ("thickness", "pressure", "bars"):
            field_kind[f] = "unverified"
    for name in rec["thickness"]:
        rec["thickness"][name]["kind"] = field_kind["thickness"]
    rec["pressure_kind"], rec["bars_kind"] = field_kind["pressure"], field_kind["bars"]
    rec["kind"], rec["verification"] = kind, ver
    if flags:
        rec["flags"] = flags
    rec["src"] = raw["src"]
    return rec


def configs_in(text: str) -> set[str]:
    """Every span x height configuration a sentence names, a range 'AmXBm to AmXCm' included (same span)."""
    found = [(float(m.group(1)), float(m.group(2)), m.end()) for m in CFG.finditer(text or "")]
    out = {cfg_key(a, b) for a, b, _ in found}
    for (a1, b1, e1), (a2, b2, _e2) in itertools.pairwise(found):
        if a1 == a2 and re.match(r"\s*(?:to|-)\s*", (text or "")[e1:e1 + 5], re.IGNORECASE):
            out |= {f"{a1:g}mX{h:g}m" for h in HEIGHTS if b1 <= h <= b2}
    return out


HEIGHTS = (1.2, 1.8, 2.0, 2.5, 3.0, 3.5, 3.6, 3.75, 4.0, 4.15, 4.5, 4.65, 5.0, 5.15, 5.5, 6.0)


def unclear_for(page: Page, key: str, fill: float | None) -> list[str]:
    """The extraction's unclear notes that name this configuration (and, when a note names a fill block, this fill)."""
    out = []
    for u in page.unclear:
        if key not in configs_in(u):
            continue
        blk = re.search(r"(\d+(?:\.\d+)?)\s*m\s*block", u, re.IGNORECASE)
        if blk and fill is not None and abs(float(blk.group(1)) - fill) > 1e-9:
            continue
        out.append(u)
    return out


def ga_page(std: dict, pages: list[Page]) -> Page | None:
    for p in pages:
        if (p.j.get("page_kind") or "").startswith("general arrangement") and p.no == 1:
            return p
    return next((p for p in pages if (p.j.get("page_kind") or "").startswith("general arrangement")), None)


def haunch_bands(t: dict) -> list[dict]:
    """The B x B haunch table as bands [from, to) in metres of 'CLS or cht', size in mm, each with the printed text."""
    out = []
    cols = t.get("columns") or []
    pairs = [(i, i + 1) for i in range(0, len(cols) - 1, 2)]
    for r in t.get("rows") or []:
        for a, b in pairs:
            if b >= len(r) or not str(r[a]).strip():
                continue
            band, size = str(r[a]), str(r[b])
            nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", band)]
            low = band.lower().replace("≥", ">=")
            lo = hi = None
            if "less than" in low and nums:
                hi = nums[0]
            elif len(nums) >= 2:
                lo, hi = nums[0], nums[1]
            elif nums:
                lo = nums[0]
            mm = re.findall(r"(\d+)\s*X\s*(\d+)", size.replace(" ", ""), re.IGNORECASE)
            out.append({"from_m": lo, "to_m": hi, "size_mm": float(mm[0][0]) if mm else None, "printed": f"{band} -> {size}",
                        "lower_inclusive": not low.startswith(">") or ">=" in low})
    out.sort(key=lambda b: (b["from_m"] if b["from_m"] is not None else -1))
    return out


def key_depth(t: dict) -> list[dict]:
    out = []
    for r in t.get("rows") or []:
        if len(r) < 2:
            continue
        lab, val = str(r[0]), str(r[1])
        lim = re.search(r"(\d+)\s*mm", lab)
        rule = {"printed": f"{lab} -> {val}", "tsb_mm_limit": float(lim.group(1)) if lim else None}
        if "UPTO" in lab.upper():
            rule["applies"] = "tsb <= limit"
            m = re.search(r"(\d+)\s*mm", val)
            rule["dk_mm"] = float(m.group(1)) if m else None
        else:
            rule["applies"] = "tsb > limit"
            m = re.search(r"tsb\s*\+\s*(\d+)\s*mm", val, re.IGNORECASE)
            rule["dk_formula"] = f"tsb + {m.group(1)}" if m else val
        out.append(rule)
    return out


def design_basis(page: Page) -> list[dict]:
    out = []
    for q in page.j.get("parameters") or []:
        out.append({"name": q.get("name"), "printed": q.get("value_printed"), "where": q.get("where"), "kind": "explicit",
                    "verification": page.level()[1], "src": page.ref})
    return out


def configuration(std_id: str, ga: Page | None, pages: list[Page]) -> dict:
    """What the set says about the structure it covers, each statement with its note. Nothing here is inferred beyond the printed words."""
    title = (ga.title if ga else "").upper()
    notes = {str(n.get("no")): (n.get("text") or "") for n in ((ga.j.get("notes_block") if ga else None) or [])}
    joined = " ".join(notes.values()).upper()
    cfg: dict = {"title_printed": ga.title if ga else None, "date_printed": ga.j.get("date_printed") if ga else None,
                 "loading_printed": ga.j.get("loading_printed") if ga else None, "provisional": "PROVISIONAL" in json.dumps(ga.j.get("date_printed") if ga else "").upper()}
    if "SEGMENTAL" in title:
        cfg["structure"] = {"value": "segmental (pre-cast) RCC box culvert for limited height subway (LHS)", "basis": "title"}
    elif "SINGLE BOX" in title:
        cfg["structure"] = {"value": "single-cell RCC box culvert", "basis": "title"}
    if "DOUBLE LINE" in title or "DOUBLE LINE" in joined:
        cfg["track"] = {"value": "double line", "basis": "title / note 2"}
    elif "SINGLE TRACK" in joined or "SINGLE LINE" in joined:
        cfg["track"] = {"value": "single line", "basis": "note 2"}
    elif "SINGLE AS WELL AS MULTIPLE LINES" in joined:
        cfg["track"] = {"value": "single or multiple lines (limited height subway)", "basis": "note 2"}
    if "DFC" in title:
        cfg["loading"] = {"value": "DFC loading (32.5 t axle load)", "basis": "title"}
    elif "25t" in (ga.title if ga else ""):
        cfg["loading"] = {"value": "25t loading - 2008", "basis": "title"}
    for no, text in notes.items():
        up = text.upper()
        if "SKEW" in up:
            cfg["skew"] = {"value": "no skew angle considered in the design", "basis": f"note {no}", "printed": text}
        if "CURVATURE" in up or "STRAIGHT TRACK" in up:
            cfg["curvature"] = {"printed": text, "basis": f"note {no}"}
        if "SPACING OF TRACKS" in up:
            m = re.search(r"(\d+(?:\.\d+)?)\s*m", text)
            cfg["min_track_spacing_m"] = {"value": float(m.group(1)) if m else None, "printed": text, "basis": f"note {no}"}
        if "BALLAST CUSHION" in up:
            m = re.search(r"(\d+)\s*mm", text)
            cfg["ballast_cushion_mm"] = {"value": float(m.group(1)) if m else None, "printed": text, "basis": f"note {no}"}
        if "CLEAR COVER" in up:
            m = re.search(r"(\d+)\s*mm", text)
            cfg["clear_cover_mm"] = {"value": float(m.group(1)) if m else None, "printed": text, "basis": f"note {no}"}
        if "INTERMEDIATE SPAN" in up:
            cfg["intermediate_configuration_rule"] = {"printed": text, "basis": f"note {no}"}
        if "BARREL LENGTH" in up:
            cfg["barrel_length_rule"] = {"printed": text, "basis": f"note {no}"}
        if "GRADE CONCRETE" in up and "M-3" in up:
            cfg["concrete_grade_rule"] = {"printed": text, "basis": f"note {no}"}
        if "INDICATE CLEAR SPAN" in up:
            cfg["config_label_meaning"] = {"printed": text, "basis": f"note {no}",
                                           "value": "span x height = clear span (CLS) x height of box including wearing course (ht)"}
        if "UPTO 1m FILL" in up or "UP TO 1m FILL" in up:
            cfg["fill_limit_m"] = {"value": 1.0, "printed": text, "basis": f"note {no}"}
    if "config_label_meaning" not in cfg:
        cfg["config_label_meaning"] = {"value": None, "basis": "not stated on the sheets read",
                                       "note": "the schedule header says SPAN LENGTH X BOX HEIGHT; which height (cht, ht or tht) is not printed on this set"}
    return cfg


def relations(ga: Page | None, std_id: str) -> list[dict]:
    """Relations that follow from the printed notations (each derived, with the notations it rests on)."""
    nots = {str(n.get("symbol")).strip(): (n.get("meaning") or "") for n in ((ga.j.get("notations") if ga else None) or [])}
    table_nots = []
    for t in (ga.j.get("tables") if ga else []) or []:
        if "NOTATION" in (t.get("title_printed") or "").upper():
            table_nots = t.get("rows") or []
    for r in table_nots:
        if len(r) >= 2:
            nots.setdefault(str(r[0]).strip(), str(r[1]))
    rel = []
    def add(rid, statement, uses, note=""):
        if all(u in nots for u in uses):
            rel.append({"id": f"{std_id}:{rid}", "statement": statement, "kind": "derived", "rests_on": {u: nots[u] for u in uses}, **({"note": note} if note else {})})
    add("ht", "ht = cht + wearing course thickness", ["ht", "cht"], "ht is the height of box including wearing course; cht the clear height above the wearing course")
    add("tht", "tht = ht + tst + tsb", ["tht", "ht", "tst", "tsb"])
    add("ols", "OLS = CLS + 2 x tsv (single cell)", ["OLS", "CLS", "tsv"])
    add("tbl", "TBL = UBL + DBL", ["TBL", "UBL", "DBL"])
    return rel


def build(src: Path, raw: Path) -> tuple[dict, dict]:
    sources: dict = {"extract_root": str(src), "raw_root": str(raw), "files": [], "pdfs": []}
    out_standards = []
    for std in STANDARDS:
        pages: list[Page] = []
        for part in std["parts"]:
            folder = src / part["folder"]
            for f in sorted(folder.glob("p*.json"), key=lambda s: int(s.stem[1:])):
                pages.append(Page(std, part, f))
                sources["files"].append({"path": f"{part['folder']}/{f.name}", "sha256": sha256(f)})
            for f in ("doc.md", "doc.json"):
                if (folder / f).exists():
                    sources["files"].append({"path": f"{part['folder']}/{f}", "sha256": sha256(folder / f)})
            pdf = raw / part["pdf"]
            sources["pdfs"].append({"pdf": part["pdf"], "sha256": sha256(pdf) if pdf.exists() else None, "present": pdf.exists()})
        ga = ga_page(std, pages)
        rec: dict = {"id": std["id"], "series": std["series"],
                     "source": [{"pdf": p["pdf"], "extract_folder": p["folder"], "extraction_status": p["verification"]} for p in std["parts"]],
                     "configuration": configuration(std["id"], ga, pages), "sheets": [], "general": {}, "schedules": [], "relations": relations(ga, std["id"]),
                     "unclear": [], "not_read": [], "disputes": []}
        for p in pages:
            kind, ver = p.level()
            rec["sheets"].append({"drawing": p.drawing, "page": p.no, "pdf": p.part["pdf"], "title": p.title, "kind": p.j.get("page_kind"),
                                  "fill_height_m": parse_fill(p.title), "verification": ver, "usable": kind != "unverified"})
            rec["unclear"].extend({"page": p.no, "pdf": p.part["pdf"], "text": u} for u in p.unclear)
            rec["not_read"].extend({"page": p.no, "pdf": p.part["pdf"], "text": u} for u in p.not_read)
        if ga:
            g = rec["general"]
            g["src"] = ga.ref
            for t in ga.j.get("tables") or []:
                tt = (t.get("title_printed") or "").upper()
                cols = " ".join(str(c) for c in (t.get("columns") or [])).upper()
                if "HAUNCH" in tt:
                    g["haunch_table"] = {"basis": "CLS or cht (as printed)", "bands": haunch_bands(t), "kind": "explicit", "verification": ga.level()[1],
                                         "src": {**ga.ref, "table": t.get("title_printed")}}
                elif "DK" in cols or "DEPTH OF KEY" in tt:
                    g["key_depth_table"] = {"rules": key_depth(t), "kind": "explicit", "src": {**ga.ref, "table": t.get("title_printed") or "DK table"},
                                            "meaning": "DK: depth of key at bottom slab (notations)"}
                elif "REFERENCE" in tt or "TABLE-'X'" in tt or "RELATED" in tt:
                    g["reference_drawings"] = [{"no": r[0], "description": r[1], "drawing": r[2] if len(r) > 2 else None} for r in t.get("rows") or []]
                elif "REINFORCEMENT FOR BOX" in tt:
                    g["bar_shapes"] = [{"mark": r[0], "shape": r[1] if len(r) > 1 else None, "remarks": r[2] if len(r) > 2 else None} for r in t.get("rows") or []]
                elif "NOTATION" in tt:
                    g["notations"] = [{"symbol": r[0], "meaning": r[1] if len(r) > 1 else None} for r in t.get("rows") or []]
            g["notes"] = [{"no": n.get("no"), "text": n.get("text")} for n in ga.j.get("notes_block") or []]
            g["design_basis"] = design_basis(ga)
            g["revisions"] = [{"mark": r.get("mark"), "text": r.get("text"), "date": r.get("date_printed")} for r in ga.j.get("revisions") or []]
            g["refers_to"] = ga.j.get("refers_to") or []
        # schedules: one per (page, fill) with its configurations
        by: dict[tuple, dict] = {}
        for p in pages:
            if (p.j.get("page_kind") or "").startswith("general"):
                continue
            for raw_cfg in schedule_tables(p):
                fill = raw_cfg["fill"]
                key = (p.part["pdf"], p.no, fill)
                if key not in by:
                    kind, ver = p.level()
                    by[key] = {"drawing": p.drawing, "page": p.no, "pdf": p.part["pdf"], "fill_height_m": fill, "title": p.title,
                               "usable": kind != "unverified", "verification": ver, "configs": {}}
                c = normalise_config(raw_cfg, p)
                if c["config"] in by[key]["configs"]:
                    by[key]["configs"][c["config"]].setdefault("duplicates", []).append(c["src"])
                else:
                    by[key]["configs"][c["config"]] = c
        rec["schedules"] = sorted(by.values(), key=lambda s: (s["fill_height_m"] if s["fill_height_m"] is not None else -1, s["pdf"], s["page"]))
        # printed discrepancies the extraction recorded between pages of the same set
        if std["id"] == "RDSO-RCC-BOX-10153":
            rec["disputes"].append({"id": "10153-D1", "text": "p3 (RDSO/B-10153/2) prints heights 3.6 m / 4.0 m where p4 (RDSO/B-10153/2A) prints 3.75 m / 4.15 m for the same 0.0 m fill "
                                    "configurations; note 21 (ALT 2) says the height in the labels includes the wearing course. Neither page is chosen.", "source": "doc.md discrepancy 1"})
            rec["disputes"].append({"id": "10153-D2", "text": "Table X row 3 lists six span-height configurations on p1 and five on p2 (4.5X5 missing); the p5/p6 headers use another form. Nothing chosen.",
                                    "source": "doc.md discrepancy 2"})
            rec["disputes"].append({"id": "10153-D3", "text": "Table X cites RDSO/B-10153/2 and /3; the later-dated /2A and /3A (8.02.2017) are in the file; no sheet says which is current.",
                                    "source": "doc.md discrepancy 3"})
        out_standards.append(rec)
    sheet = {
        "schema": "rdso-rcc-box-standards/1",
        "title": "RDSO RCC Box Standards Knowledge Sheet (five standards)",
        "built_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "builder": "tools/build_rdso_sheet.py",
        "scope": "RDSO/B-10151/R, RDSO/B-10152/R, RDSO/B-10153, RDSO/B-10155, RDSO/B-10157 series as extracted in Aagento-GAD-Foundation-Model; nothing else",
        "kinds": KINDS,
        "rules_of_use": [
            ("A schedule value applies only to its own standard, fill height and span x height configuration; the five standards are NOT interchangeable "
             "(loading, track, construction and curvature differ: see each configuration)."),
            ("No interpolation: the sheets give discrete configurations. The notes allow the IMMEDIATELY HIGHER span/height configuration for intermediate "
             "spans/heights (the note is cited per standard). For an intermediate FILL height the sheets say nothing: taking the next higher tabulated fill is "
             "an engineer's choice, recorded as such by the template."),
            "RDSO guides geometry and validation; it never overrides an engineer's explicit input. A difference is reported with both values.",
            "Values marked unverified are shown but never used to pass or fail a check.",
        ],
        "standards": out_standards,
    }
    return sheet, sources


def md(sheet: dict) -> str:
    L: list[str] = []
    a = L.append
    a(f"# {sheet['title']}\n")
    a(f"Built {sheet['built_utc']} by `{sheet['builder']}` from the page extracts (read by eye from the RDSO PDFs; no OCR). Scope: {sheet['scope']}.\n")
    a("## How to read it\n")
    for k, v in sheet["kinds"].items():
        a(f"- **{k}**: {v}")
    a("")
    for r in sheet["rules_of_use"]:
        a(f"- {r}")
    a("")
    a("## The five standards at a glance\n")
    a("| Standard | Structure | Track | Loading | Fill heights tabulated (m) | Configurations | Extraction status |")
    a("|---|---|---|---|---|---|---|")
    for s in sheet["standards"]:
        c = s["configuration"]
        fills = sorted({x["fill_height_m"] for x in s["schedules"] if x["fill_height_m"] is not None})
        ncfg = max((len(x["configs"]) for x in s["schedules"]), default=0)
        a(f"| {s['series']} | {c.get('structure', {}).get('value', '-')} | {c.get('track', {}).get('value', '-')} | {c.get('loading', {}).get('value', '-')} | "
          f"{', '.join(f'{f:g}' for f in fills)} | up to {ncfg} per sheet | {'; '.join(p['extraction_status'] for p in s['source'])} |")
    a("")
    for s in sheet["standards"]:
        c = s["configuration"]
        a(f"## {s['series']} ({s['id']})\n")
        a(f"Source: {', '.join(p['pdf'] for p in s['source'])}. Title: {c.get('title_printed')}. Date: {c.get('date_printed')}.\n")
        a("### Applicability (as printed)\n")
        for k in ("structure", "track", "loading", "curvature", "skew", "min_track_spacing_m", "ballast_cushion_mm", "clear_cover_mm", "fill_limit_m",
                  "config_label_meaning", "intermediate_configuration_rule", "barrel_length_rule", "concrete_grade_rule"):
            if k in c:
                v = c[k]
                a(f"- **{k}**: {v.get('value') if v.get('value') is not None else ''} {('— ' + v['printed']) if v.get('printed') else ''} ({v.get('basis')})")
        a("")
        a("### Sheets\n")
        a("| Drawing | Page | Kind | Fill (m) | Verification | Usable |")
        a("|---|---|---|---|---|---|")
        for sh in s["sheets"]:
            a(f"| {sh['drawing']} | {sh['page']} ({sh['pdf']}) | {sh['kind']} | {sh['fill_height_m'] if sh['fill_height_m'] is not None else '-'} | {sh['verification']} | {'yes' if sh['usable'] else 'NO'} |")
        a("")
        g = s["general"]
        if g.get("haunch_table"):
            a("### Haunch B x B (by CLS or cht)\n")
            a("| From (m) | To (m) | Size (mm) | Printed |")
            a("|---|---|---|---|")
            for b in g["haunch_table"]["bands"]:
                a(f"| {b['from_m'] if b['from_m'] is not None else '-'} | {b['to_m'] if b['to_m'] is not None else '-'} | {b['size_mm']:g} | {b['printed']} |")
            a("")
        if g.get("key_depth_table"):
            a("### Depth of key DK at bottom slab\n")
            for r in g["key_depth_table"]["rules"]:
                a(f"- {r['printed']}")
            a("")
        if s["relations"]:
            a("### Relations from the notations (derived)\n")
            for r in s["relations"]:
                a(f"- `{r['id']}`: {r['statement']}" + (f" ({r['note']})" if r.get("note") else ""))
            a("")
        if g.get("notes"):
            a("### Notes (verbatim, general arrangement)\n")
            for n in g["notes"]:
                a(f"{n['no']}. {n['text']}")
            a("")
        if g.get("design_basis"):
            a("### Design basis (as printed)\n")
            for d in g["design_basis"]:
                a(f"- **{d['name']}**: {d['printed']} ({d['where']})")
            a("")
        for sc in s["schedules"]:
            a(f"### Schedule {sc['drawing']} — fill {sc['fill_height_m']} m (page {sc['page']}, {sc['pdf']}){'' if sc['usable'] else ' — NOT USABLE'}\n")
            a(f"Verification: {sc['verification']}.\n")
            a("| Config (span x height) | Top slab (mm) | Bottom slab (mm) | Side walls (mm) | Max. foundation pressure (kN/m2) | Kind | Flags |")
            a("|---|---|---|---|---|---|---|")
            for k, cf in sorted(sc["configs"].items(), key=lambda kv: (kv[1]["span_m"], kv[1]["height_m"])):
                th = cf["thickness"]
                f = "; ".join(cf.get("flags", []))
                a(f"| {k} | {th.get('top_slab', {}).get('mm', '-')} | {th.get('bottom_slab', {}).get('mm', '-')} | {th.get('side_walls', {}).get('mm', '-')} | "
                  f"{cf.get('max_foundation_pressure_kN_m2', '-')} | {cf['kind']} | {f} |")
            a("")
        if s["disputes"]:
            a("### Printed discrepancies within the set\n")
            for d in s["disputes"]:
                a(f"- **{d['id']}**: {d['text']}")
            a("")
        a(f"Unclear items recorded by the extraction: {len(s['unclear'])}; not-read items: {len(s['not_read'])} (full list in the JSON).\n")
    if sheet.get("kb_context"):
        a("## Context from the Foundation Model knowledge base (unreviewed there)\n")
        a("| Id | Topic | Name | Statement | Evidence | Kind here |")
        a("|---|---|---|---|---|---|")
        for e in sheet["kb_context"]:
            d = (e.get("definition") or "").replace("|", "/")
            a(f"| `{e['id']}` | {e['topic']} | {e.get('name') or ''} | {d[:220]}{'…' if len(d) > 220 else ''} | {e['evidence_status']} ({e.get('review_state')}) | {e['kind']} |")
        a("")
    return "\n".join(L) + "\n"


RULE_TOPICS = (("BARREL LENGTH", "barrel_length"), ("INTERMEDIATE SPAN", "intermediate_configuration"), ("GRADE CONCRETE", "concrete_grade"),
               ("SKEW", "skew"), ("SPACING OF TRACKS", "track_spacing"), ("CURVATURE", "curvature"), ("SINGLE TRACK", "track"), ("SINGLE LINE", "track"),
               ("BALLAST CUSHION", "ballast_cushion"), ("CLEAR COVER", "cover"), ("DEPTH OF KEY", "key_depth"), ("WEEP HOLE", "weep_holes"),
               ("BACK FILL", "backfill"), ("BED SLOPE", "bed_slope"), ("BASE COURSE", "base_course"), ("WING WALL AND RETURN WALL", "wing_return_walls"),
               ("CURTAIN WALL", "curtain_drop_walls"), ("INDICATE CLEAR SPAN", "configuration_label"), ("FILL HEIGHT", "fill_height"), ("LOADING", "loading"))


KB_TOPICS = ("standard_drawing", "formula", "rule", "level_chain", "conflict", "datum", "component")
KB_MATCH = re.compile(r"1015[1-7]|box culvert|rcc box|segmental|haunch|earth retainer|cushion|wearing course|shear key|cut[- ]?off key|return wall|toe wall|"
                      r"formation level|rail level|barrel length|limited height subway|subway|soffit", re.IGNORECASE)
KB_KIND = {"NORMATIVE": "explicit", "REFERENCE_OBSERVED": "explicit", "DERIVED": "derived", "ENGINEERING_INFERENCE": "unverified", "COMMON_PRACTICE": "unverified",
           "ASSUMPTION": "unverified", "UNKNOWN": "unverified", "DISPUTED": "unverified"}


def kb_context(kb: Path) -> list[dict]:
    """The Foundation Model knowledge base's entries on RCC boxes (standard drawings, formulas, rules, level chains, conflicts), as pointers with their
    own evidence status: every one is unreviewed there, and it says so here. NORMATIVE entries cite IRBM clauses, not the RDSO standard drawings."""
    out: list[dict] = []
    if not kb.is_dir():
        return out
    for topic in KB_TOPICS:
        f = kb / f"{topic}.jsonl"
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            names = e.get("names") or {}
            text = " ".join([names.get("canonical") or "", " ".join(names.get("aliases") or []), e.get("definition") or ""])
            if topic == "component" and not re.search(r"box|haunch|earth retainer|cushion|wearing course|shear key|return wall|toe wall", text, re.IGNORECASE):
                continue
            if not KB_MATCH.search(text):
                continue
            status = e.get("evidence_status") or "UNKNOWN"
            out.append({"id": e.get("id"), "topic": topic, "name": names.get("canonical"), "definition": e.get("definition"),
                        "evidence_status": status, "review_state": e.get("review_state"), "kind": KB_KIND.get(status, "unverified"),
                        "sources": [s.get("id") or s.get("source") or s for s in (e.get("sources") or [])][:6] if isinstance(e.get("sources"), list) else e.get("sources")})
    return out


def compact(sheet: dict) -> dict:
    """The retrieval index: small, component-oriented records that point back into the full sheet (standard, drawing, page)."""
    stds, thick, haunch, keyd, basis, rules, rels, disputes = [], [], [], [], [], [], [], []
    for s in sheet["standards"]:
        c = s["configuration"]
        fills = sorted({x["fill_height_m"] for x in s["schedules"] if x["fill_height_m"] is not None and x["usable"]})
        stds.append({"id": s["id"], "series": s["series"], "title": c.get("title_printed"), "date": c.get("date_printed"),
                     "structure": c.get("structure", {}).get("value"), "track": c.get("track", {}).get("value"), "loading": c.get("loading", {}).get("value"),
                     "curvature": (c.get("curvature") or {}).get("printed"), "skew": (c.get("skew") or {}).get("value"),
                     "min_track_spacing_m": (c.get("min_track_spacing_m") or {}).get("value"), "ballast_cushion_mm": (c.get("ballast_cushion_mm") or {}).get("value"),
                     "clear_cover_mm": (c.get("clear_cover_mm") or {}).get("value"), "fill_limit_m": (c.get("fill_limit_m") or {}).get("value"),
                     "config_label_meaning": c.get("config_label_meaning", {}).get("value"), "usable_fill_heights_m": fills,
                     "sheets": [{k: sh[k] for k in ("drawing", "page", "pdf", "fill_height_m", "usable", "verification")} for sh in s["sheets"]],
                     "extraction_status": [p["extraction_status"] for p in s["source"]]})
        for sc in s["schedules"]:
            for k, cf in sorted(sc["configs"].items(), key=lambda kv: (kv[1]["span_m"], kv[1]["height_m"])):
                th = cf["thickness"]
                kinds = {v.get("kind") for v in th.values()} | {cf.get("pressure_kind")}
                thick.append([s["id"], sc["drawing"], sc["page"], sc["fill_height_m"], k, cf["span_m"], cf["height_m"],
                              th.get("top_slab", {}).get("mm"), th.get("bottom_slab", {}).get("mm"), th.get("side_walls", {}).get("mm"),
                              cf.get("max_foundation_pressure_kN_m2"), "unverified" if ("unverified" in kinds or not sc["usable"]) else "explicit", sc["verification"]])
        g = s["general"]
        for b in (g.get("haunch_table") or {}).get("bands", []):
            haunch.append({"standard": s["id"], "basis": "CLS or cht", **b, "src": g["haunch_table"]["src"]})
        for r in (g.get("key_depth_table") or {}).get("rules", []):
            keyd.append({"standard": s["id"], **r, "src": g["key_depth_table"]["src"]})
        for d in g.get("design_basis") or []:
            basis.append({"standard": s["id"], "item": d["name"], "printed": d["printed"], "where": d["where"], "kind": d["kind"], "src": d["src"]})
        for n in g.get("notes") or []:
            up = (n.get("text") or "").upper()
            topics = sorted({t for w, t in RULE_TOPICS if w in up})
            if topics:
                rules.append({"standard": s["id"], "note": n.get("no"), "topics": topics, "printed": n.get("text"), "kind": "explicit", "src": g.get("src")})
        rels.extend(s["relations"])
        disputes.extend({"standard": s["id"], **d} for d in s["disputes"])
    return {"schema": "rdso-rcc-box-index/1", "built_utc": sheet["built_utc"], "full_sheet": "rdso_rcc_box_standards.json", "kinds": sheet["kinds"],
            "rules_of_use": sheet["rules_of_use"], "standards": stds,
            "thickness_table": {"columns": ["standard", "drawing", "page", "fill_m", "config", "span_m", "height_m", "top_slab_mm", "bottom_slab_mm",
                                            "side_walls_mm", "max_foundation_pressure_kN_m2", "kind", "verification"], "rows": thick},
            "haunch": haunch, "key_depth": keyd, "design_basis": basis, "rules": rules, "relations": rels, "disputes": disputes,
            "kb_context": sheet.get("kb_context", [])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--kb", type=Path, default=DEFAULT_KB)
    ap.add_argument("--index-only", action="store_true", help="write the retrieval index, the readable sheet and the sources, not the full 3 MB sheet")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "src" / "dxf_autoparam" / "knowledge" / "library" / "bridge" / "rdso")
    a = ap.parse_args(argv)
    if not a.src.is_dir():
        print(f"no extracts at {a.src}", file=sys.stderr)
        return 2
    sheet, sources = build(a.src, a.raw)
    sheet["kb_context"] = kb_context(a.kb)
    sheet["kb_context_source"] = {"path": str(a.kb), "note": "Aagento-GAD-Foundation-Model knowledge base (unified KB); every entry there is unreviewed"}
    a.out.mkdir(parents=True, exist_ok=True)
    if not a.index_only:
        (a.out / "rdso_rcc_box_standards.json").write_text(json.dumps(sheet, indent=1, ensure_ascii=False) + "\n")
    (a.out / "RDSO_RCC_BOX_STANDARDS.md").write_text(md(sheet))
    (a.out / "sources.json").write_text(json.dumps(sources, indent=1) + "\n")
    (a.out / "rdso_rcc_box_index.json").write_text(json.dumps(compact(sheet), ensure_ascii=False, separators=(",", ":")) + "\n")
    n_cfg = sum(len(sc["configs"]) for s in sheet["standards"] for sc in s["schedules"])
    print(f"{len(sheet['standards'])} standards, {sum(len(s['schedules']) for s in sheet['standards'])} schedules, {n_cfg} configurations -> {a.out}")
    for s in sheet["standards"]:
        print(f"  {s['series']}: sheets {len(s['sheets'])}, schedules {len(s['schedules'])}, configs {sum(len(x['configs']) for x in s['schedules'])}, "
              f"haunch bands {len(s['general'].get('haunch_table', {}).get('bands', []))}, notes {len(s['general'].get('notes', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
