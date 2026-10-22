"""The engineering library: skills, references and documented rules the agent retrieves ON DEMAND while it works.

It is data, not code. Nothing here knows a kind of structure, a part name or a value: it reads a *domain* (a folder under
`knowledge/library/<domain>/`, see its README) whose sources are the migrated engineering material (`knowledge/agent_context`, kept as the
source wrote it) and the authored recipes. A domain is switched on with the domain pack of the same name (`options.domain`, `--domain`,
`AUTOPARAM_DOMAIN`); without one the model sees none of it.

What the harness does (deterministically), and what the model decides:

    discover(words)     which skills' recognition cues the drawing's own printed words match, and WHICH words — a lead, never a verdict
    list_skills         the catalogue (compact) with the matches for this drawing
    load_skill          one skill, section by section, within a character budget; sections not shown are listed with their size
    search_library      records by words, filtered by category / topic / family; every hit carries its review state
    get_reference       one record in full (bounded), or a grounded example sheet as a compact reading
    check_rule          a documented definition evaluated on values the model bound by NAME (never by number): advisory
    record_finding      what the model applied, assumed, found in conflict, or proposed; a cited library id must exist

Trust, as the source states it and as the engine keeps it: a library item is CONTEXT, labelled with its category (B reference, C vocabulary,
D proposed or disputed, E operational) and review state. It never establishes a value of the drawing in hand; where it disagrees with the
drawing the drawing wins, and the disagreement is recorded. Every retrieval is traced (`KnowledgeSession.summary`) into the run's verdict.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import re
import threading
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path

from ..program import ExprError, evaluate, names_in

LIBRARY_PACKAGE = "dxf_autoparam.knowledge"

DEFAULT_LOAD_CHARS = 9000  # what load_skill shows when no section is asked for
MAX_LOAD_CHARS = 24000  # the most one load_skill call returns, however much is asked
REFERENCE_CHARS = 3500  # one record in full; `full` raises it to MAX_LOAD_CHARS
EXAMPLE_CHARS = 9000  # one stored sheet reading
SEARCH_LIMIT = 12
SEARCH_MAX = 25
HIT_CHARS = 240
RUN_BUDGET_CHARS = 160_000  # all library text one run may read (about 40k tokens); then retrieval says so
FINDING_KINDS = ("applied", "assumption", "conflict", "gap", "proposal")
MAX_FINDINGS = 200

# a heading of a skill file → the section key the harness uses (family skills of the source and authored recipes share the keys)
HEADINGS = {
    "purpose": "purpose", "applicability": "applicability", "required inputs": "inputs", "recognition cues": "recognition",
    "prerequisites": "prerequisites", "engineering rules": "rules", "procedure": "procedure", "dependencies": "dependencies",
    "outputs": "outputs", "validation": "validation", "failure handling": "failure", "source traceability": "sources",
    # the source's own headings
    "when to use this skill": "recognition", "when to use": "recognition", "scope in this repository": "scope",
    "what drawings of this family usually show": "components", "formulas and rules for this family": "rules",
    "known hazards for this family": "hazards", "evidence to request before proposing anything": "evidence_requests",
    "permitted output": "permitted", "blocked output": "blocked", "abstain or ask for review when": "failure", "sources used": "sources",
    "steps": "procedure", "status today": "scope", "conditions that must all hold before a binding can be proposed as ready": "rules",
    "required evidence": "inputs", "the ladder (say which rung you are on)": "rules", "rules": "rules",
}
# shown by load_skill when no section is asked for, in this order; the rest is listed with its size and loaded on request
DEFAULT_SECTIONS = ["purpose", "applicability", "inputs", "recognition", "prerequisites", "representation", "failure", "procedure", "components",
                    "conventions", "rules", "dependencies", "outputs", "validation"]
ALL_SECTIONS = DEFAULT_SECTIONS + ["hazards", "scope", "scope_note", "permitted", "blocked", "evidence_requests", "sources"]

LIBRARY_ID_PREFIXES = ("kb:", "kb.", "skill:", "family:", "chunk:", "ontology:", "issue:", "rdso-doc:", "rdso-extract:", "rdso:", "proposal:", "teach:",
                       "component:")
SHEET_ID = re.compile(r"^(v-)?[0-9a-f]{12}-p\d+(#[A-Za-z0-9_.-]+)?$")


# ── words ────────────────────────────────────────────────────────────────────────

TOKEN = re.compile(r"[a-z0-9]+")
STOP = frozenset({"the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "by", "is", "as", "at", "with", "from", "be", "that", "this",
                  "it", "are", "was", "not"})
_MTEXT = re.compile(r"\\[A-Za-z][^;\\]*;|\\P|\\~|[{}]|%%[A-Za-z]")


def tokens(text: str | None) -> list[str]:
    """Lowercase words, a trailing plural dropped: how records and queries are matched."""
    out = []
    for t in TOKEN.findall((text or "").lower()):
        if len(t) < 2 or t in STOP:
            continue
        out.append(t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t)
    return out


def printed_tokens(text: str | None) -> list[str]:
    """A printed note as upper-case words: layout codes and punctuation dropped, dotted abbreviations joined ("R.C.C." → "RCC")."""
    t = _MTEXT.sub(" ", text or "").upper()
    t = re.sub(r"[.\-_/,:;()=]+", " ", t)
    out: list[str] = []
    run: list[str] = []
    for p in t.split():
        if len(p) == 1 and p.isalpha():
            run.append(p)
            continue
        if run:
            out.append("".join(run))
            run = []
        out.append(p)
    if run:
        out.append("".join(run))
    return out


def clip(text, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


# ── files ────────────────────────────────────────────────────────────────────────


def _open_text(base: Path):
    """`base`, or `base.gz` (the migration stores large generated data compressed)."""
    if base.is_file():
        return base.open(encoding="utf-8")
    gz = base.with_name(base.name + ".gz")
    if gz.is_file():
        return gzip.open(gz, "rt", encoding="utf-8")
    raise FileNotFoundError(str(base))


def _jsonl(base: Path, contains: tuple[str, ...] | None = None) -> Iterator[dict]:
    with _open_text(base) as f:
        for line in f:
            if not line.strip() or (contains and not any(c in line for c in contains)):
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def library_root() -> Path:
    env = os.environ.get("AUTOPARAM_LIBRARY_DIR")
    return Path(env) if env else Path(str(resources.files(LIBRARY_PACKAGE).joinpath("library")))


def domains() -> list[str]:
    root = library_root()
    return sorted(p.name for p in root.iterdir() if (p / "domain.json").is_file()) if root.is_dir() else []


# ── skills ───────────────────────────────────────────────────────────────────────


@dataclass
class Skill:
    id: str
    title: str
    kind: str  # workflow | recipe | family
    purpose: str
    applies_to: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)
    source: str = ""  # where it comes from, relative to its source or the domain folder
    family: dict | None = None  # for a family skill: {"kb": id, "ontology": id}

    def sizes(self) -> dict[str, int]:
        return {k: len(self.sections[k]) for k in ALL_SECTIONS if k in self.sections}


def _split_sections(body: str) -> tuple[str, dict[str, str]]:
    intro: list[str] = []
    sections: dict[str, list[str]] = {}
    cur: list[str] | None = None
    for line in body.splitlines():
        if line.startswith("## "):
            head = re.sub(r"\s*\(.*\)\s*$", "", line[3:].strip().lower())
            key = HEADINGS.get(line[3:].strip().lower()) or HEADINGS.get(head)
            if key is None:
                key = re.sub(r"[^a-z0-9]+", "_", head).strip("_") or "other"
            cur = sections.setdefault(key, [])
            continue
        (cur if cur is not None else intro).append(line)
    return "\n".join(intro).strip(), {k: "\n".join(v).strip() for k, v in sections.items() if "\n".join(v).strip()}


def _front_matter(text: str) -> tuple[dict, str]:
    """`---` + a block + `---` + body. The block is JSON (authored skills) or `key: value` lines (the source's skills)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    block, body = text[3:end].strip(), text[end + 4:].lstrip("\n")
    if block.startswith("{"):
        try:
            return json.loads(block), body
        except ValueError:
            return {}, body
    meta = {}
    for line in block.splitlines():
        k, _, v = line.partition(":")
        if k.strip() and v.strip():
            meta[k.strip()] = v.strip()
    return meta, body


def parse_authored(path: Path) -> Skill:
    meta, body = _front_matter(path.read_text(encoding="utf-8"))
    _intro, sections = _split_sections(body)
    sid = meta.get("id") or path.stem
    return Skill(id=sid, title=meta.get("title", sid), kind=meta.get("kind", "recipe"), purpose=meta.get("purpose", ""),
                 applies_to=list(meta.get("applies_to", [])), tools=list(meta.get("tools", [])), related=list(meta.get("related", [])),
                 sections=sections, source=f"skills/{path.name}")


# ── a source of the agent-context shape ──────────────────────────────────────────


class ContextSource:
    """One migrated `agent-context` folder, read through its generated data files only (never the repository it came from)."""

    def __init__(self, root: Path):
        self.root = root
        self._lock = threading.RLock()
        self._cache: dict[str, object] = {}

    def _once(self, key: str, build: Callable[[], object]):
        with self._lock:
            if key not in self._cache:
                self._cache[key] = build()
            return self._cache[key]

    @property
    def knowledge(self) -> dict[str, dict]:
        def build():
            return {r["id"]: r for r in _jsonl(self.root / "knowledge" / "knowledge.jsonl")}
        return self._once("knowledge", build)  # type: ignore[return-value]

    @property
    def by_kb_id(self) -> dict[str, dict]:
        return self._once("by_kb", lambda: {r["kb_id"]: r for r in self.knowledge.values() if r.get("kb_id") and r.get("proposal_status") == "none"})  # type: ignore[return-value]

    @property
    def issues(self) -> dict[str, dict]:
        return self._once("issues", lambda: {r["id"]: r for r in _jsonl(self.root / "registry" / "issues.jsonl")})  # type: ignore[return-value]

    @property
    def sources(self) -> dict[str, dict]:
        return self._once("sources", lambda: {r["id"]: r for r in _jsonl(self.root / "registry" / "sources.jsonl")})  # type: ignore[return-value]

    @property
    def observations(self) -> dict[str, list[dict]]:
        """Observations of the sheets a model has read (owner → rows). Only drawing sheets are kept: the vector-text and RDSO pages are 90% of
        the file and are not worked examples of a reading."""
        def build():
            out: dict[str, list[dict]] = defaultdict(list)
            for r in _jsonl(self.root / "registry" / "observations.jsonl", contains=('"owner_kind":"drawing_sheet"',)):
                if r.get("owner_kind") == "drawing_sheet":
                    out[r["owner_id"]].append(r)
            return dict(out)
        return self._once("observations", build)  # type: ignore[return-value]

    def skill_files(self) -> list[Path]:
        return sorted((self.root / "skills").glob("**/SKILL.md")) if (self.root / "skills").is_dir() else []


def _family_skill(path: Path, root: Path, procedure: list[str], template: dict[str, str] | None = None) -> Skill:
    text = path.read_text(encoding="utf-8")
    meta, body = _front_matter(text)
    intro, sections = _split_sections(body)
    title = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith("# ")), meta.get("name", path.parent.name))
    rel = path.relative_to(root).as_posix()
    is_family = "families" in path.parts
    sid = f"family:{path.parent.name}" if is_family else path.parent.name
    sk = Skill(id=sid, title=title, kind="family" if is_family else "recipe", purpose=meta.get("description", ""), sections=sections,
               source=rel, applies_to=[path.parent.name])
    if intro:
        sk.sections["scope_note"] = intro
    if is_family:
        kbs = Counter(re.findall(r"kb:(kb\.family\.[a-z_]+)", text))
        onto = re.search(r"ontology family `([a-z_]+)`", text)
        sk.family = {"dataset": path.parent.name, "kb": f"kb:{kbs.most_common(1)[0][0]}" if kbs else None, "ontology": onto.group(1) if onto else None}
        sk.sections["procedure"] = "\n".join(f"{i}. {s}" for i, s in enumerate(procedure, 1))
        for key, text in (template or {}).items():  # what the structure skills share (authored in domain.json), never overriding the source's own text
            sk.sections.setdefault(key, text)
    return sk


# ── the library ──────────────────────────────────────────────────────────────────


class Library:
    def __init__(self, domain_dir: Path):
        self.dir = domain_dir
        self.meta = json.loads((domain_dir / "domain.json").read_text(encoding="utf-8"))
        self.name: str = self.meta["name"]
        self.title: str = self.meta.get("title", self.name)
        self.sources = [ContextSource((domain_dir / s["path"]).resolve()) for s in self.meta.get("sources", []) if s.get("kind") == "agent_context"]
        self._lock = threading.RLock()
        self._built: dict[str, object] = {}

    # lazily built, shared, read-only afterwards
    def _once(self, key: str, build: Callable[[], object]):
        with self._lock:
            if key not in self._built:
                self._built[key] = build()
            return self._built[key]

    @property
    def protocol(self) -> str:
        p = self.dir / self.meta.get("protocol", "protocol.md")
        return p.read_text(encoding="utf-8").strip() if p.is_file() else ""

    # ── components: the parametric definition of a part as a production generator builds it (components.json) ──────────────

    @property
    def components(self) -> list[dict]:
        def build():
            p = self.dir / self.meta.get("components", "components.json")
            return json.loads(p.read_text(encoding="utf-8")).get("components", []) if p.is_file() else []

        return self._once("components", build)

    def component(self, ident: str) -> dict | None:
        ident = (ident or "").strip().removeprefix("component:")
        return next((c for c in self.components if c.get("id") == ident), None)

    def component_cards(self, words: set[str]) -> list[dict]:
        """The cards whose names share the most content words with a part's own (its name, type and the labels on it) — best first. Words
        are compared as words (labels.words); a card needs every word of one of its names to match: 'return wall' is not 'wall'."""
        from .labels import words as wordset

        hits = []
        for c in self.components:
            best = 0
            for n in c.get("names", []):
                w = wordset(n)
                if w and w <= words:
                    best = max(best, len(w))
            if best:
                hits.append((best, c))
        return [c for _n, c in sorted(hits, key=lambda h: -h[0])]

    # ── skills ───────────────────────────────────────────────────────────────────

    @property
    def skills(self) -> dict[str, Skill]:
        def build():
            out: dict[str, Skill] = {}
            sdir = self.dir / self.meta.get("skills_dir", "skills")
            for p in sorted(sdir.glob("*.md")) if sdir.is_dir() else []:
                sk = parse_authored(p)
                out[sk.id] = sk
            for src in self.sources:
                for p in src.skill_files():
                    if "families" not in p.parts:  # the source's general skills are written for its repository command line: this domain's
                        continue  # authored recipes adapt them (their `derived_from` names the originals, which stay migrated and unedited)
                    sk = _family_skill(p, src.root, self.meta.get("family_procedure", []), self.meta.get("family_sections"))
                    self._add_family_sections(sk, src)
                    out.setdefault(sk.id, sk)
            return out
        return self._once("skills", build)  # type: ignore[return-value]

    def _ontology_family(self, ident: str | None) -> dict | None:
        if not ident:
            return None
        for src in self.sources:
            for r in src.knowledge.values():
                if r.get("topic") == "ontology:bridge-families" and (r.get("raw") or {}).get("id") == ident:
                    return r["raw"]
        return None

    def _add_family_sections(self, sk: Skill, src: ContextSource) -> None:
        fam = self._ontology_family(sk.family.get("ontology")) if sk.family else None
        if fam:
            sk.sections["representation"] = self._representation(fam)
            sk.family["classes"] = sorted({s["class"] for s in fam.get("parameter_slots", []) if s.get("class")} | set(fam.get("structure_types", [])))
            sk.family["structure_types"] = list(fam.get("structure_types", []))
        kb = src.by_kb_id.get((sk.family or {}).get("kb", "")[3:]) if sk.family and sk.family.get("kb") else None
        deep = ((kb or {}).get("raw") or {}).get("deep") or {}
        parts = []
        if deep.get("drawing_conventions"):
            parts.append("Drawing conventions: " + "; ".join(deep["drawing_conventions"]) + ".")
        if deep.get("common_misreadings"):
            parts.append("Common misreadings:\n" + "\n".join(f"- {m}" for m in deep["common_misreadings"]))
        if deep.get("implies"):
            parts.append("Implications (if … then …):\n" + "\n".join(f"- if {i.get('if')}: {i.get('then')}" for i in deep["implies"]))
        if deep.get("variants"):
            v = deep["variants"]
            parts.append("Variants: " + "; ".join(x if isinstance(x, str) else x.get("name", str(x)) for x in v) + ".")
        if deep.get("design_drivers"):
            parts.append("What drives the design: " + "; ".join(deep["design_drivers"]) + ".")
        if parts:
            sk.sections["conventions"] = "(unreviewed reference, from `" + kb["id"] + "`)\n" + "\n".join(parts)

    @staticmethod
    def _representation(fam: dict) -> str:
        lines = [f"Family record: {fam.get('name')} (crossing types: {', '.join(fam.get('crossing_types', [])) or '-'})."]
        if fam.get("structure_types"):
            lines.append("Structure classes: " + ", ".join(fam["structure_types"]) + ".")
        if fam.get("primary_components"):
            lines.append("Primary components: " + ", ".join(fam["primary_components"]) + ".")
        for u in fam.get("repetition_units", []):
            lines.append(f"Repeated unit: {u.get('class')} ({u.get('unit')}); count: {u.get('count_slot')}; pitch: {u.get('pitch_slot')}.")
        req = []
        for r in fam.get("required_facts", []):
            alt = " or ".join("+".join(a) for a in r.get("any_of", []))
            req.append((r.get("label") or alt) + (f" [when {json.dumps(r['when'])}]" if r.get("when") else ""))
        if req:
            lines.append("Facts a drawing of this kind normally states: " + "; ".join(req) + ".")
        if fam.get("views"):
            lines.append("Views usually drawn: " + ", ".join(fam["views"]) + ".")
        chain = (fam.get("level_chain") or {})
        if chain.get("summary"):
            lines.append("Level chain (as documented, status " + str(chain.get("status")) + "): " + "; ".join(chain["summary"]) + ".")
        if fam.get("capability_note"):
            lines.append("Note of the source's generator (not a statement about this agent): " + fam["capability_note"])
        return "\n".join(lines)

    def skill(self, ident: str) -> Skill | None:
        ident = (ident or "").strip().removeprefix("skill:")
        sk = self.skills
        if ident in sk:
            return sk[ident]
        return sk.get("family:" + ident)

    # ── discovery ────────────────────────────────────────────────────────────────

    def _terms(self) -> dict[str, list[tuple[tuple[str, ...], str, str]]]:
        """first printed word → [(label words, label as written, class it maps to)] from the source's vocabulary of drawing labels."""
        def build():
            idx: dict[str, list] = defaultdict(list)
            for src in self.sources:
                for r in src.knowledge.values():
                    raw = r.get("raw") or {}
                    if r.get("topic") == "ontology:terminology" and raw.get("term") and raw.get("maps_to"):
                        words = tuple(printed_tokens(raw["term"]))
                        if words:
                            idx[words[0]].append((words, raw["term"], raw["maps_to"]))
            return dict(idx)
        return self._once("terms", build)  # type: ignore[return-value]

    def match_labels(self, texts: list[str]) -> list[dict]:
        """Which vocabulary labels the printed words contain, as {printed, class, count}. A label matches as whole words, in order; one label
        may mean several classes ("RCC BOX" is a part and a structure), and each is returned."""
        found: Counter = Counter()
        terms = self._terms()
        for text in texts:
            toks = printed_tokens(text)
            for i, w in enumerate(toks):
                for words, label, cls in terms.get(w, ()):
                    if tuple(toks[i:i + len(words)]) == words:
                        found[(label, cls)] += 1
        return [{"printed": label, "class": cls, "count": n} for (label, cls), n in sorted(found.items())]

    def discover(self, texts: list[str], top: int = 5) -> list[dict]:
        """Rank the structure skills by the drawing's own printed words — evidence for the model to confirm on the drawing, not a classification.

        A STRUCTURE label (a printed word that names a kind of structure) is what separates one skill from another, so it dominates: a skill
        whose structure classes the drawing prints ranks above every skill that is only matched by its parts. Parts break ties and rank
        the rest: each matched part class counts by how few skills share it, and the sum is divided by the root of the skill's vocabulary,
        so a skill that mentions nearly every part (a big vocabulary) does not outrank a specific one."""
        fams = [s for s in self.skills.values() if s.family and s.family.get("classes")]
        if not fams:
            return []
        matched = self.match_labels(texts)
        if not matched:
            return []
        df = Counter(c for s in fams for c in s.family["classes"])
        rows = []
        for s in fams:
            classes = set(s.family["classes"])
            structure = set(s.family.get("structure_types", []))
            structural, parts, because, seen = 0.0, 0.0, [], set()
            # one entry per class, under the longest label that matched ("RCC BOX" rather than "BOX")
            for m in sorted(matched, key=lambda m: (-len(printed_tokens(m["printed"])), -m["count"], m["printed"], m["class"])):
                c = m["class"]
                if c not in classes or c in seen:
                    continue
                seen.add(c)
                because.append({"printed": m["printed"], "means": c.split(".")[-1], "x": m["count"], **({"structure": True} if c in structure else {})})
                if c in structure:
                    structural += 10.0 * (1 + math.log(1 + m["count"]))
                else:
                    parts += math.log(1 + len(fams) / df[c])
            if because:
                score = structural + parts / math.sqrt(len(classes))
                rows.append({"skill": s.id, "score": round(score, 2), "because": because[:8], "strong": structural > 0})
        rows.sort(key=lambda r: (-r["score"], r["skill"]))
        return rows[:top]

    # ── search ───────────────────────────────────────────────────────────────────

    def _index(self):
        def build():
            recs: dict[str, dict] = {}
            for src in self.sources:
                recs.update(src.knowledge)
            post: dict[str, dict[str, float]] = defaultdict(dict)
            for rid, r in recs.items():
                weighted = (
                    (3.0, " ".join([r.get("title") or "", " ".join(map(str, r.get("aliases") or []))])),
                    (2.0, " ".join([rid, str(r.get("kb_id") or ""), str(r.get("topic") or ""), str(r.get("kind") or "")])),
                    (1.0, " ".join([str(r.get("statement") or ""), str(r.get("interpretation") or ""), str(r.get("search_text") or "")[:1500]])),
                )
                for w, text in weighted:
                    for t in set(tokens(text)):
                        post[t][rid] = max(post[t].get(rid, 0.0), w)
            return recs, dict(post)
        return self._once("index", build)

    def search(self, query: str, categories: set[str] | None = None, topics: set[str] | None = None, families: set[str] | None = None,
               limit: int = SEARCH_LIMIT) -> list[dict]:
        recs, post = self._index()  # type: ignore[misc]
        terms = set(tokens(query))
        if not terms:
            return []
        n = len(recs)
        scores: dict[str, float] = defaultdict(float)
        for t in terms:
            plist = post.get(t)
            if not plist:
                continue
            idf = math.log(1 + n / len(plist))
            for rid, w in plist.items():
                scores[rid] += idf * w
        out = []
        for rid, sc in scores.items():
            r = recs[rid]
            if categories and r.get("category") not in categories:
                continue
            if topics and r.get("topic") not in topics and r.get("kind") not in topics:
                continue
            fam = set(r.get("applies_families") or [])
            if families and fam and not (fam & families) and "*" not in fam:
                continue
            out.append((sc / len(terms), rid))
        out.sort(key=lambda x: (-x[0], x[1]))
        return [self.view(recs[rid], round(sc, 2)) for sc, rid in out[: max(1, min(limit, SEARCH_MAX))]]

    @staticmethod
    def view(r: dict, score: float | None = None) -> dict:
        trust = r.get("trust") or {}
        expr = r.get("expression") or {}
        v = {"id": r["id"], "category": r.get("category"), "topic": r.get("topic"), "kind": r.get("kind"), "title": clip(r.get("title"), 90),
             "text": clip(r.get("statement") or r.get("interpretation") or r.get("summary") or "", HIT_CHARS),
             "review": trust.get("review_state"), "status": trust.get("evidence_status")}
        if r.get("category") == "D" or trust.get("evidence_status") == "DISPUTED":
            v["not_accepted"] = "proposed or disputed: report it, do not apply it as a rule"
        if r.get("applies_families"):
            v["families"] = r["applies_families"]
        if expr.get("text"):
            v["expression"] = expr["text"]
            v["roles"] = sorted(_roles(r))
        if score is not None:
            v["score"] = score
        return v

    # ── references ───────────────────────────────────────────────────────────────

    def record(self, ident: str) -> dict | None:
        for src in self.sources:
            r = src.knowledge.get(ident) or src.by_kb_id.get(ident) or src.by_kb_id.get(ident.removeprefix("kb:"))
            if r is not None:
                return r
        return None

    def resolves(self, ident: str) -> bool:
        """Does a library id name something that exists? (skills, knowledge, issues, sources, observations)"""
        ident = (ident or "").strip()
        if not ident:
            return False
        if ident.startswith("skill:") or ident in self.skills:
            return self.skill(ident) is not None
        if ident.startswith("component:"):
            return self.component(ident) is not None
        if self.record(ident) is not None:
            return True
        for src in self.sources:
            if ident in src.issues or ident in src.sources:
                return True
            owner, _, local = ident.partition("#")
            if local and any(o.get("local_id") == local for o in src.observations.get(owner, ())):
                return True
        return False

    def is_library_id(self, ident: str) -> bool:
        return ident.startswith(LIBRARY_ID_PREFIXES) or bool(SHEET_ID.match(ident))

    def reference(self, ident: str, full: bool = False) -> dict:
        cap = MAX_LOAD_CHARS if full else REFERENCE_CHARS
        if ident.startswith("component:"):
            c = self.component(ident)
            if c is None:
                return {"found": False, "id": ident, "hint": "the component ids are in coverage's `knowledge` (component:…)"}
            return {"found": True, "kind": "component", "id": f"component:{c['id']}", **{k: v for k, v in c.items() if k != "id"},
                    "context_only": "production defaults and relations: hypotheses to check on this drawing, never its values"}
        sk = self.skill(ident) if (ident.startswith(("skill:", "family:")) or ident in self.skills) else None
        if sk is not None:
            return {"found": True, "kind": "skill", "id": sk.id, "hint": f"load_skill(id='{sk.id}')", "title": sk.title, "purpose": sk.purpose,
                    "sections": sk.sizes()}
        r = self.record(ident)
        if r is not None:
            trust = r.get("trust") or {}
            expr = r.get("expression") or {}
            out = {"found": True, "kind": "record", "id": r["id"], "category": r.get("category"), "topic": r.get("topic"), "title": r.get("title"),
                   "statement": clip(r.get("statement"), cap), "interpretation": clip(r.get("interpretation"), cap // 2) or None,
                   "review": trust.get("review_state"), "status": trust.get("evidence_status"), "flags": trust.get("risk_flags") or [],
                   "applies_families": r.get("applies_families") or [], "context_only": "knowledge: never a value of the drawing in hand"}
            if expr.get("text"):
                out["expression"] = expr["text"]
                out["roles"] = sorted(_roles(r))
                out["evaluable"] = bool(_lhs(r))
            conflicts = self.conflicts_of(r)
            if conflicts:
                out["conflicts"] = conflicts[:6]
            if r.get("relations"):
                out["relations"] = [self._brief(c) for c in r["relations"][:8]]
            cites = r.get("citations") or []
            if cites:
                out["citations"] = [{k: c.get(k) for k in ("kind", "id", "origin", "clause", "page", "note", "resolved") if c.get(k) not in (None, "")}
                                    for c in cites[:6]]
            if r.get("source_path"):
                out["source_path"] = r["source_path"]
            out["raw_text_chars"] = len(json.dumps(r.get("raw") or {}, default=str))
            if full and (r.get("raw") or {}):
                out["raw"] = clip(json.dumps(r["raw"], ensure_ascii=False, default=str), MAX_LOAD_CHARS)
            return out
        for src in self.sources:
            if ident in src.issues:
                i = src.issues[ident]
                return {"found": True, "kind": "issue", "id": ident, "severity": i.get("severity"), "blocks": i.get("affects"),
                        "description": clip(i.get("description"), cap)}
            if "#" in ident:
                owner, _, local = ident.partition("#")
                o = next((x for x in src.observations.get(owner, ()) if x.get("local_id") == local), None)
                if o is not None:
                    return {"found": True, "kind": "observation", "id": ident, "obs_kind": o.get("obs_kind"), "raw_text": o.get("raw_text"),
                            "reading": o.get("candidate_interpretation"), "view": o.get("view"),
                            "label": "a model's reading of a picture, unreviewed: an example, never a value"}
            if ident in src.observations or ident in src.sources:
                ex = self.example(ident)
                if ex is not None:
                    return ex
                s = src.sources.get(ident, {})
                return {"found": True, "kind": "source", "id": ident, "title": s.get("title"), "family": s.get("family"),
                        "completeness": s.get("completeness"), "note": "no reading of this sheet is stored"}
        return {"found": False, "id": ident, "reason": "no record, skill, issue, sheet or observation has this id (search_library finds records by words)"}

    def conflicts_of(self, r: dict) -> list[dict]:
        """The disputes a record is part of: its own `conflicts` list, and the conflict its payload names ("KC-5" → kb:kb.conflict.kc_5)."""
        ids = [str(c if isinstance(c, str) else (c or {}).get("id", "")) for c in (r.get("conflicts") or [])]
        named = ((r.get("raw") or {}).get("payload") or {}).get("conflict")
        if isinstance(named, str) and named.strip():
            ids.append("kb.conflict." + re.sub(r"[^a-z0-9]+", "_", named.strip().lower()).strip("_"))
        out = []
        for i in dict.fromkeys(x for x in ids if x):
            c = self.record(i if i.startswith("kb:") else "kb:" + i)
            out.append({"id": c["id"] if c else i, "title": clip(c.get("title"), 100) if c else None, "status": (c or {}).get("trust", {}).get("evidence_status")})
        return out

    @staticmethod
    def _brief(x) -> dict | str:
        if isinstance(x, dict):
            return {k: clip(v, 140) for k, v in x.items() if k in ("id", "kind", "type", "with", "to", "target", "note", "why", "name") and v}
        return clip(x, 140)

    # ── grounded examples ────────────────────────────────────────────────────────

    def examples(self, query: str = "", limit: int = 12) -> list[dict]:
        """The sheets whose reading by a model is stored (a worked example of how parts, levels and relations were stated)."""
        out = []
        terms = set(tokens(query))
        for src in self.sources:
            for owner, rows in src.observations.items():
                kinds = Counter(r["obs_kind"] for r in rows)
                if not (kinds.get("part") or kinds.get("relation") or kinds.get("level")):
                    continue
                s = src.sources.get(owner, {})
                hay = set(tokens(" ".join([owner, str(s.get("title") or ""), str(s.get("family") or ""),
                                           " ".join(str(r.get("raw_text") or "") for r in rows[:60])])))
                if terms and not (terms & hay):
                    continue
                out.append({"id": owner, "title": clip(s.get("title"), 90), "family": s.get("family"), "reading": dict(sorted(kinds.items()))})
        out.sort(key=lambda r: (-sum(r["reading"].get(k, 0) for k in ("part", "relation", "level")), r["id"]))
        return out[:limit]

    def example(self, owner: str) -> dict | None:
        rows = next((src.observations.get(owner) for src in self.sources if owner in src.observations), None)
        if not rows:
            return None
        s = next((src.sources.get(owner) for src in self.sources if owner in src.sources), None) or {}
        by: dict[str, list] = defaultdict(list)
        for r in rows:
            by[r["obs_kind"]].append(r)

        def interp(r, keys):
            ci = r.get("candidate_interpretation") or {}
            return {k: clip(ci[k], 70) for k in keys if ci.get(k) not in (None, "", [])}
        out = {"found": True, "kind": "example", "id": owner, "title": clip(s.get("title"), 120), "family": s.get("family"),
               "label": "a model's reading of a picture, unreviewed: it shows how parts, levels and relations were stated on a real sheet — never a value",
               "views": [[r["local_id"], clip(r.get("raw_text"), 40), interp(r, ("type", "kind", "name", "depicts"))] for r in by.get("view", [])[:10]],
               "parts": [[r["local_id"], interp(r, ("class", "status", "parent", "variant", "side", "index"))] for r in by.get("part", [])[:40]],
               "levels": [[r["local_id"], clip(r.get("raw_text"), 32), interp(r, ("datum", "for", "value", "unit"))] for r in by.get("level", [])[:30]],
               "relations": [[r["local_id"], interp(r, ("type", "from", "to", "confidence", "evidence"))] for r in by.get("relation", [])[:40]],
               "dimensions": [[r["local_id"], clip(r.get("raw_text"), 24), interp(r, ("measures_from", "measures_to", "sets", "unit"))]
                              for r in by.get("dimension", [])[:30]],
               "doubts_and_disputes": [clip(r.get("raw_text") or json.dumps(r.get("candidate_interpretation"), default=str), 160)
                                       for r in (by.get("doubt", []) + by.get("dispute", []))[:8]]}
        return _fit(out, EXAMPLE_CHARS)


def _fit(out: dict, limit: int) -> dict:
    """Drop the tail of the longest list until the whole answer fits, and say how much was left (a bound, never a silent cut)."""
    dropped = 0
    while len(json.dumps(out, default=str)) > limit:
        key = max((k for k, v in out.items() if isinstance(v, list) and v), key=lambda k: len(json.dumps(out[k], default=str)), default=None)
        if key is None:
            break
        out[key].pop()
        dropped += 1
    if dropped:
        out["trimmed"] = f"{dropped} item(s) left out to keep this reading short"
    return out


def _lhs(r: dict) -> str | None:
    m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", str(r.get("statement") or ""))
    return m.group(1) if m and (r.get("expression") or {}).get("text") else None


def _roles(r: dict) -> set[str]:
    text = (r.get("expression") or {}).get("text")
    if not text:
        return set()
    try:
        names = names_in(text)
    except ExprError:
        return set()
    lhs = _lhs(r)
    return names | ({lhs} if lhs else set())


@lru_cache(maxsize=4)
def open_domain(name: str, root: str | None = None) -> Library | None:
    base = Path(root) if root else library_root()
    d = base / name
    return Library(d) if (d / "domain.json").is_file() else None


def for_pack(pack: dict | None) -> Library | None:
    """The library of the domain pack that is on (None: no pack, or a pack with no library)."""
    return open_domain(pack["name"]) if pack and pack.get("name") else None


def drawing_texts(items) -> list[str]:
    """The words a drawing prints: text, multi-line text, attributes and dimension overrides (a layer name or a block name is not a word)."""
    out = []
    for it in items:
        t = (getattr(it, "text", None) or "").strip()
        if t and t != "<>" and getattr(it, "dxftype", "") in ("TEXT", "MTEXT", "ATTRIB", "DIMENSION"):
            out.append(t)
    return out


# ── the tools the model is given ─────────────────────────────────────────────────

_S, _N, _B = {"type": "string"}, {"type": "number"}, {"type": "boolean"}
_LIST = {"type": "array", "items": {"type": "string"}}
LIBRARY_TOOL_SPECS = [
    ("list_skills", ("The library's skills — a workflow, recipes, and one skill per kind of structure — with what each covers, the size of each "
                     "section, and which skills match THIS drawing's own printed words (with the words that matched). A match is a lead: confirm "
                     "the cues on the drawing."),
     {"type": "object", "properties": {"match_drawing": _B, "kind": {"type": "string", "enum": ["workflow", "recipe", "family"]}, "query": _S},
      "required": []}),
    ("load_skill", ("Read one skill, section by section. Without `sections` you get the working set within a budget and the rest is listed with "
                    "its size; ask for sections by name (recognition, representation, components, conventions, rules, procedure, failure, hazards, "
                    "scope, sources …); `offset` continues a long section. Load only what the task needs."),
     {"type": "object", "properties": {"id": _S, "sections": _LIST, "offset": _N}, "required": ["id"]}),
    ("search_library", ("Find library records by words (several queries at once): vocabulary, definitions, formulas, rules, conventions, level "
                        "chains, disputes. Every hit says its category (B reference, C vocabulary, D proposed or disputed, E operational) and "
                        "review state. `scope: examples` lists sheets whose reading by a model is stored (how parts, levels, relations were stated)."),
     {"type": "object", "properties": {"queries": _LIST, "categories": _LIST, "topics": _LIST, "families": _LIST, "limit": _N,
                                      "scope": {"type": "string", "enum": ["records", "examples"]}}, "required": ["queries"]}),
    ("get_reference", ("One record in full by id (kb:…, chunk:…, ontology:…, issue:…, skill:…), or a stored example sheet (<id>-p1) as a "
                       "compact reading. Context, never a value of this drawing."),
     {"type": "object", "properties": {"id": _S, "full": _B}, "required": ["id"]}),
    ("check_rule", ("Compare a documented definition with values YOU defined: `rule` = a formula record id (search_library shows its `roles`), "
                    "`bind` = {role: the NAME of one of your values or levels} — a number is refused; `unit` = the sheet unit (U…) the "
                    "names belong to, default the open one. The result says holds / differs (expected, measured, difference) or what could not "
                    "be evaluated. Advisory: a difference is a question about which size or "
                    "datum you bound, never a reason to move a line."),
     {"type": "object", "properties": {"rule": _S, "bind": {"type": "object", "additionalProperties": _S}, "tolerance_mm": _N, "unit": _S},
      "required": ["rule", "bind"]}),
    ("record_finding", ("Say what you did with library knowledge, for the person and the run's record: `applied` (a skill or rule you used), "
                        "`assumption`, `conflict` (the library and the drawing disagree), `gap` (the drawing or the library lacks it), `proposal` "
                        "(a rule or correction you think is missing: a note for a person, never merged). `evidence`: library ids (checked: "
                        "an id that does not exist is refused) and drawing ids."),
     {"type": "object", "properties": {"findings": {"type": "array", "items": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": list(FINDING_KINDS)}, "text": _S, "evidence": _LIST, "about": _S}, "required": ["kind", "text"]}}},
      "required": ["findings"]}),
]
LIBRARY_TOOLS = {n for n, _d, _p in LIBRARY_TOOL_SPECS}
_ARGS = {n: set(p.get("properties", {})) | {"why"} for n, _d, p in LIBRARY_TOOL_SPECS}


# ── one run's use of the library ─────────────────────────────────────────────────


class KnowledgeSession:
    """The tools' implementation for ONE run: the library, the drawing's words and values (supplied by whoever owns the drawing), the
    character budget, and the trace of everything retrieved, checked and recorded."""

    def __init__(self, lib: Library, texts: Callable[[], list[str]] | None = None,
                 values: Callable[[str, str | None], tuple[float, str] | None] | None = None, budget_chars: int = RUN_BUDGET_CHARS):
        self.lib = lib
        self._texts = texts
        self._values = values
        self.budget = budget_chars
        self.used = 0
        self.trace: list[dict] = []
        self.loaded: dict[str, list[str]] = {}
        self.references: list[str] = []
        self.searches: list[str] = []
        self.checks: list[dict] = []
        self.findings: list[dict] = []
        self.refused: list[str] = []
        self._matches: list[dict] | None = None

    # the drawing's words → which skills match
    def matches(self) -> list[dict]:
        if self._matches is None:
            try:
                self._matches = self.lib.discover(self._texts() if self._texts else [])
            except Exception:  # noqa: BLE001 — a drawing that cannot be read for words has no matches; discovery never stops a run
                self._matches = []
        return self._matches

    def hint(self) -> dict:
        """What the model's first look at the sheet says about the library: it is on, which skills the drawing's words match (and which
        words), and how to use it. Nothing is loaded."""
        m = self.matches()
        return {"on": self.lib.name, "skills": len(self.lib.skills),
                "match_this_drawing": [{"skill": x["skill"], "strong": x["strong"], "printed_words": list(dict.fromkeys(b["printed"] for b in x["because"]))[:6]}
                                       for x in m[:3]] or "none: the drawing prints none of the library's vocabulary",
                "use": "list_skills, then load_skill for the one whose cues you confirm on the drawing; a match is a lead, not a classification"}

    def refresh(self) -> None:
        """The words may have changed (another unit opened): matches are computed again at the next list_skills."""
        self._matches = None

    def call(self, name: str, args: dict) -> dict:
        if name not in LIBRARY_TOOLS:
            return {"error": f"{name} is not a library tool"}
        extra = set(args) - _ARGS[name]
        if extra:
            return {"error": f"unknown argument(s) for {name}: {sorted(extra)}; it takes {sorted(_ARGS[name] - {'why'})}"}
        args = {k: v for k, v in args.items() if k != "why"}
        heavy = name in ("load_skill", "get_reference", "search_library")
        if heavy and self.used >= self.budget:
            res = {"refused": f"this run has read {self.used:,} characters of library text (its budget is {self.budget:,}): work from what you "
                              "already loaded, or ask_person; list_skills and check_rule are still open"}
        else:
            res = getattr(self, "_" + name)(**args)
        size = len(json.dumps(res, default=str))
        if heavy:
            self.used += size
        self.trace.append({"n": len(self.trace) + 1, "tool": name, "args": _short(args), "chars": size, "ok": not (res.get("error") or res.get("refused"))})
        return res

    # ── tools ────────────────────────────────────────────────────────────────────

    def _list_skills(self, match_drawing: bool = True, kind: str | None = None, query: str = "") -> dict:
        match = {m["skill"]: m for m in self.matches()} if match_drawing else {}
        terms = set(tokens(query))
        rows = []
        for sk in self.lib.skills.values():
            if kind and sk.kind != kind:
                continue
            if terms and not (terms & set(tokens(" ".join([sk.id, sk.title, sk.purpose, " ".join(sk.applies_to)])))):
                continue
            row = {"id": sk.id, "kind": sk.kind, "title": clip(sk.title, 90), "purpose": clip(sk.purpose, 200)}
            if sk.id in match:  # the words that matched are in `matches` below (once, not per skill)
                row["match"] = {k: match[sk.id][k] for k in ("score", "strong")}
            # sizes are given where the model is likely to load (a match, a recipe, a listing that is not about this drawing); a structure
            # skill that does not match lists only its section names — load_skill gives their sizes
            row["sections"] = sk.sizes() if (sk.kind != "family" or sk.id in match or not match_drawing) else list(sk.sizes())
            rows.append(row)
        rows.sort(key=lambda r: (-(r.get("match") or {}).get("score", 0), r["kind"] != "workflow", r["kind"] != "recipe", r["id"]))
        out = {"skills": rows, "library": self.lib.name}
        if match_drawing:
            out["matches"] = [{"skill": m["skill"], "score": m["score"], "strong": m["strong"], "printed_words": [b["printed"] for b in m["because"]]}
                              for m in self.matches()[:3]]
            if not self.matches():
                out["matches_note"] = ("no skill's cues match this drawing's printed words — normal for an unlabelled or unusual drawing: the "
                                       "recipes still apply, and you name everything from what the drawing shows")
        return out

    def _load_skill(self, id: str, sections: list[str] | None = None, offset: float = 0) -> dict:
        sk = self.lib.skill(id)
        if sk is None:
            return {"found": False, "id": id, "reason": "no such skill: list_skills shows the ids",
                    "ids": sorted(self.lib.skills)[:30]}
        sections = _as_list(sections)
        explicit = bool(sections)
        want = [s for s in (sections or DEFAULT_SECTIONS) if s in sk.sections]
        unknown = [s for s in sections if s not in sk.sections]
        limit = MAX_LOAD_CHARS if explicit else DEFAULT_LOAD_CHARS
        off = max(0, int(offset or 0))
        shown: dict[str, str] = {}
        left = limit
        more: dict[str, dict] = {}
        for key in want:
            text = sk.sections[key][off:] if (explicit and len(want) == 1) else sk.sections[key]
            if left <= 0 or (len(text) > left and not explicit):
                # a working-set load never cuts a section in the middle: what does not fit is listed with its size, to be asked for by name
                more[key] = {"chars": len(sk.sections[key]), "why": "over this call's budget: ask for it by name"}
                continue
            if len(text) > left:
                shown[key] = text[:left] + f"\n…[{len(text) - left} more characters: load_skill(id='{sk.id}', sections=['{key}'], offset={off + left})]"
                left = 0
            else:
                shown[key] = text
                left -= len(text)
        absent_default = [k for k in sk.sections if k not in want and not explicit]
        not_included = [{"section": k, "chars": len(sk.sections[k])} for k in absent_default] + [{"section": k, **v} for k, v in more.items()]
        self.loaded.setdefault(sk.id, [])
        for k in shown:
            if k not in self.loaded[sk.id]:
                self.loaded[sk.id].append(k)
        res = {"found": True, "id": sk.id, "title": sk.title, "kind": sk.kind, "purpose": sk.purpose, "sections": shown,
               "not_included": not_included, "trust": ("source knowledge, unreviewed: context, never a value of this drawing"
                                                       if sk.kind == "family" else "authored recipe for this agent"),
               "source": sk.source}
        if unknown:
            res["no_such_section"] = unknown
        mt = next((m for m in self.matches() if m["skill"] == sk.id), None)
        if mt:
            res["match"] = {k: mt[k] for k in ("score", "strong", "because")}
        if sk.related:
            res["related"] = sk.related
        return res

    def _search_library(self, queries: list[str] | str, categories: list[str] | None = None, topics: list[str] | None = None,
                        families: list[str] | None = None, limit: float = SEARCH_LIMIT, scope: str = "records") -> dict:
        qs = [q for q in _as_list(queries) if q.strip()]
        if not qs:
            return {"error": "give at least one query (words)"}
        self.searches.extend(qs)
        if scope == "examples":
            hits = {}
            for q in qs:
                for e in self.lib.examples(q, int(limit or SEARCH_LIMIT)):
                    hits.setdefault(e["id"], e)
            return {"examples": list(hits.values())[: int(limit or SEARCH_LIMIT)],
                    "label": "a model's reading of a picture, unreviewed; get_reference(id) shows one"}
        merged: dict[str, dict] = {}
        for q in qs[:6]:
            for h in self.lib.search(q, set(_as_list(categories)) or None, set(_as_list(topics)) or None, set(_as_list(families)) or None, int(limit or SEARCH_LIMIT)):
                if h["id"] not in merged or h["score"] > merged[h["id"]]["score"]:
                    merged[h["id"]] = h
        hits = sorted(merged.values(), key=lambda h: (-h["score"], h["id"]))[: max(1, min(int(limit or SEARCH_LIMIT), SEARCH_MAX))]
        res = {"hits": hits, "count": len(hits)}
        if not hits:
            res["note"] = "nothing matches: try other words, or the drawing's own term; an empty result is a normal answer"
        return res

    def _get_reference(self, id: str, full: bool = False) -> dict:
        res = self.lib.reference(str(id), bool(full))
        if res.get("found") and str(id) not in self.references:
            self.references.append(res.get("id", str(id)))
        return res

    def _check_rule(self, rule: str, bind: dict, tolerance_mm: float | None = None, unit: str | None = None) -> dict:
        r = self.lib.record(str(rule))
        if r is None:
            return {"ok": False, "error": f"no record {rule!r}: search_library(topics=['formula']) lists documented definitions"}
        expr = (r.get("expression") or {}).get("text")
        lhs = _lhs(r)
        base = {"rule": r["id"], "statement": clip(r.get("statement"), 200), "review": (r.get("trust") or {}).get("review_state"),
                "status": (r.get("trust") or {}).get("evidence_status")}
        if not expr or not lhs:
            return {**base, "ok": False, "result": "not_evaluable", "why": "this record is text, not a definition with an expression: apply it by reading it"}
        if (r.get("trust") or {}).get("evidence_status") in ("DISPUTED", "UNKNOWN"):
            base["caution"] = "the library marks this record " + str((r.get("trust") or {}).get("evidence_status")) + ": a difference may be the library's"
        conflicts = self.lib.conflicts_of(r)
        if conflicts:
            base["conflicts"] = conflicts[:4]
            base.setdefault("caution", "this definition is part of a recorded dispute (see conflicts): a difference may be the datum, not an error")
        roles = _roles(r)
        if not isinstance(bind, dict) or not bind:
            return {**base, "ok": False, "result": "not_evaluable", "roles": sorted(roles), "why": "bind each role to the NAME of one of your values or levels"}
        scope: dict[str, float] = {}
        resolved: dict[str, dict] = {}
        problems = []
        for role in sorted(roles):
            ref = bind.get(role)
            if ref is None:
                problems.append(f"{role}: not bound")
                continue
            if isinstance(ref, (int, float)) or re.fullmatch(r"\s*-?[0-9.]+\s*", str(ref)):
                problems.append(f"{role}: bind a NAME of a value or level you defined, not a number (the library supplies no values)")
                continue
            got = self._values(str(ref), unit) if self._values else None
            if got is None:
                problems.append(f"{role}: no value or level named {ref!r} in the open work (define it first)")
                continue
            value, u = got
            mm = value * 1000.0 if u == "m" else value
            scope[role] = mm
            resolved[role] = {"name": str(ref), "mm": round(mm, 3), "unit": u}
        extra = sorted(set(bind) - roles)
        if problems:
            return {**base, "ok": False, "result": "not_evaluable", "roles": sorted(roles), "problems": problems,
                    **({"ignored_bindings": extra} if extra else {})}
        try:
            expected = evaluate(expr, {k: v for k, v in scope.items() if k != lhs})
        except ExprError as exc:
            return {**base, "ok": False, "result": "not_evaluable", "why": str(exc)}
        measured = scope[lhs]
        tol = float(tolerance_mm) if tolerance_mm is not None else max(1.0, abs(measured) * 0.001)
        diff = measured - expected
        holds = abs(diff) <= tol
        res = {**base, "ok": True, "result": "holds" if holds else "differs", "expression": f"{lhs} = {expr}", "expected_mm": round(expected, 2),
               "measured_mm": round(measured, 2), "difference_mm": round(diff, 2), "tolerance_mm": round(tol, 2), "bound": resolved,
               "advisory": "documented definition, unreviewed: a difference is a question about which size or datum you bound, not an error to fix by moving a line"}
        if not holds:
            res["ask_yourself"] = ("is the size bound to the right pair of lines? is the level read from the datum this definition uses? "
                                   "does this drawing define the quantity differently (say so with record_finding kind conflict)?")
        self.checks.append({"rule": r["id"], "result": res["result"], "difference_mm": res["difference_mm"], "bound": {k: v["name"] for k, v in resolved.items()}})
        return res

    def _record_finding(self, findings: list[dict]) -> dict:
        if not isinstance(findings, list) or not findings:
            return {"ok": False, "error": "findings: a list of {kind, text, evidence?, about?}"}
        out = []
        for i, f in enumerate(findings[:20]):
            if not isinstance(f, dict):
                out.append({"item": i, "ok": False, "refused": "not an object"})
                continue
            kind, text = str(f.get("kind", "")), " ".join(str(f.get("text", "")).split())
            ev = [str(e).strip() for e in (f.get("evidence") or []) if str(e).strip()]
            if kind not in FINDING_KINDS:
                out.append({"item": i, "ok": False, "refused": f"kind must be one of {list(FINDING_KINDS)}"})
                continue
            if not text:
                out.append({"item": i, "ok": False, "refused": "text is empty"})
                continue
            missing = [e for e in ev if self.lib.is_library_id(e) and not self.lib.resolves(e)]
            if missing:
                self.refused.extend(missing)
                out.append({"item": i, "ok": False, "refused": f"library id(s) that do not exist: {missing} (search_library finds ids; a drawing id is accepted as stated)"})
                continue
            if len(self.findings) >= MAX_FINDINGS:
                out.append({"item": i, "ok": False, "refused": f"{MAX_FINDINGS} findings recorded already"})
                continue
            rec = {"n": len(self.findings) + 1, "kind": kind, "text": clip(text, 600), "evidence": ev[:12], "about": clip(f.get("about"), 80) or None,
                   "library": [e for e in ev if self.lib.is_library_id(e)][:12]}
            self.findings.append(rec)
            out.append({"item": i, "ok": True, "n": rec["n"]})
        return {"ok": all(o["ok"] for o in out), "items": out}

    # ── what the run's verdict says ──────────────────────────────────────────────

    def summary(self) -> dict:
        kinds = Counter(f["kind"] for f in self.findings)
        results = Counter(c["result"] for c in self.checks)
        return {"library": self.lib.name, "calls": len(self.trace), "chars_read": self.used, "budget_chars": self.budget,
                "matches": [{"skill": m["skill"], "score": m["score"], "strong": m["strong"], "printed": [b["printed"] for b in m["because"]]}
                            for m in self.matches()[:3]],
                "skills_loaded": {k: v for k, v in self.loaded.items()}, "references": self.references[:60], "searches": self.searches[:30],
                "rule_checks": {"holds": results.get("holds", 0), "differs": results.get("differs", 0),
                                "not_evaluable": results.get("not_evaluable", 0), "items": self.checks[:40]},
                "findings": {"count": len(self.findings), "by_kind": dict(kinds), "items": self.findings[:80]},
                "refused_ids": sorted(set(self.refused))[:20]}


def _as_list(x) -> list[str]:
    """A model may send one string where a list is meant (or null): both are read as the list they obviously are."""
    if x is None or x == "":
        return []
    if isinstance(x, str):
        return [x]
    return [str(v) for v in x] if isinstance(x, (list, tuple, set)) else [str(x)]


def _short(a: dict) -> dict:
    out = {}
    for k, v in a.items():
        s = json.dumps(v, default=str)
        out[k] = v if len(s) <= 120 else s[:117] + "…"
    return out


def protocol_text(pack: dict | None) -> str:
    """The paragraph appended to the system prompt when a pack with a library is on."""
    lib = for_pack(pack)
    return lib.protocol if lib else ""


def overview_rows(pack: dict | None, texts: list[str]) -> dict:
    """What the first overview says about the library: the skills' ids and the matches for THIS drawing (compact; nothing is loaded)."""
    lib = for_pack(pack)
    if lib is None:
        return {}
    skills = lib.skills
    matches = lib.discover(texts, top=3)
    return {"engineering library (on for this run; retrieve with list_skills / load_skill / search_library)": {
        "skills": {k: s.kind for k, s in sorted(skills.items())},
        "match this drawing's printed words": [[m["skill"], m["score"], [b["printed"] for b in m["because"]][:5]] for m in matches] or "none"}}
