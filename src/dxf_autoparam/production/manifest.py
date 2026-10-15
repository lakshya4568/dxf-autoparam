"""The production knowledge as Python reads it: the generated manifests, shape-checked, queryable, and with their freshness.

A manifest is DATA about one family's production code (see `extract`): it answers questions without Node or the aagento-bridge checkout.
Whether it still describes the code is a separate, explicit question (`freshness`): the checkout's modules are fingerprinted again and compared
with the manifest's, and the bundle that would execute the rules is compared with both. Stale knowledge is reported, never silently used:
evaluating with a bundle built from other code than the manifest describes is refused, and guards are not created from stale knowledge.

    pk = knowledge()                      # the manifests shipped in the package (AUTOPARAM_PRODUCTION_KNOWLEDGE overrides the folder)
    fam = pk.family("railway_rcc_box")    # FamilyKnowledge; KnowledgeError if absent or malformed
    pk.freshness("railway_rcc_box")       # {"state": "fresh" | "stale" | "unverifiable", "checkout": …, "bundle": …}
    pk.discover(["2 CELL RCC BOX", "HALF SECTION"])   # leads from a drawing's printed words, with the words that matched
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
from collections import Counter
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from . import source as S
from .build import read_info

FORMAT = "dxf-autoparam/production-knowledge-1"
INDEX_FORMAT = "dxf-autoparam/production-index-1"
UNITS_LENGTH = {"m": 1.0, "mm": 0.001}  # a length's unit → metres
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset({"of", "the", "and", "or", "to", "in", "on", "at", "for", "a", "an", "c", "s", "x", "type", "view", "i", "ii"})


class KnowledgeError(ValueError):
    """No such family, or a manifest that is not what this code reads (it is refused whole, never half-used)."""


def default_dir() -> Path:
    env = os.environ.get("AUTOPARAM_PRODUCTION_KNOWLEDGE")
    if env:
        return Path(env)
    from importlib import resources

    return Path(str(resources.files("dxf_autoparam.knowledge").joinpath("production")))


# ── the shape a manifest must have ───────────────────────────────────────────────

_TOP = {"format": str, "family": str, "knowledge_id": str, "source": dict, "capabilities": dict, "parameters": list, "outputs": list, "findings": list}
_PARAM = {"path": str, "kind": str, "unit": str}
_OUTPUT = {"name": str, "depends_on": list}


def validate_manifest(m) -> list[str]:
    """What is wrong with a manifest (empty: nothing). Every field a reader relies on is checked, with its type."""
    probs: list[str] = []
    if not isinstance(m, dict):
        return ["not a JSON object"]
    for k, t in _TOP.items():
        if not isinstance(m.get(k), t):
            probs.append(f"{k}: expected {t.__name__}")
    if probs:
        return probs
    if m["format"] != FORMAT:
        probs.append(f"format {m['format']!r} is not {FORMAT!r} (regenerate with `dxf-autoparam production extract`)")
    src = m["source"]
    if not isinstance(src.get("sources"), dict) or not isinstance(src.get("sources_digest"), str):
        probs.append("source: sources (file → sha256) and sources_digest are required (provenance)")
    for i, p in enumerate(m["parameters"]):
        for k, t in _PARAM.items():
            if not isinstance(p, dict) or not isinstance(p.get(k), t):
                probs.append(f"parameters[{i}].{k}: expected {t.__name__}")
                break
    for i, o in enumerate(m["outputs"]):
        for k, t in _OUTPUT.items():
            if not isinstance(o, dict) or not isinstance(o.get(k), t):
                probs.append(f"outputs[{i}].{k}: expected {t.__name__}")
                break
        f = (o or {}).get("formula") if isinstance(o, dict) else None
        if f is not None and (not isinstance(f, dict) or not isinstance(f.get("status"), str)):
            probs.append(f"outputs[{i}].formula: a formula carries its status")
    return probs[:20]


@dataclass
class FamilyKnowledge:
    data: dict

    @property
    def key(self) -> str:
        return self.data["family"]

    @property
    def title(self) -> str:
        return self.data.get("title") or self.key

    @property
    def supported(self) -> bool:
        return bool(self.data["capabilities"].get("has_compute"))

    @cached_property
    def params(self) -> dict[str, dict]:
        return {p["path"]: p for p in self.data["parameters"]}

    @cached_property
    def outputs(self) -> dict[str, dict]:
        return {o["name"]: o for o in self.data["outputs"]}

    @property
    def views(self) -> list[dict]:
        v = self.data.get("views") or {}
        return v.get("views", []) if v.get("available") else []

    def defaults_model(self) -> dict:
        """The family defaults, as the production code holds them (for the bridge: an unbound field is NEVER trusted as a drawing value —
        `binding` measures what depends on it and says so)."""
        import copy

        return copy.deepcopy(self.data.get("defaults") or {})

    def length_factor(self, path: str, output: bool = False) -> tuple[float | None, str]:
        """(metres per production unit, kind) of a parameter or output; None when the knowledge does not say the unit."""
        rec = (self.outputs if output else self.params).get(path) or {}
        unit, kind = rec.get("unit", "unknown"), rec.get("kind", "unknown")
        return UNITS_LENGTH.get(unit), kind


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in _STOP and not t.isdigit()]


class ProductionKnowledge:
    def __init__(self, directory: Path | None = None):
        self.dir = Path(directory) if directory else default_dir()
        self._fam: dict[str, FamilyKnowledge] = {}
        self._fresh: dict[str, dict] = {}
        self._lock = threading.Lock()

    @cached_property
    def index(self) -> dict:
        p = self.dir / "index.json"
        try:
            idx = json.loads(p.read_text())
        except (OSError, ValueError) as exc:
            raise KnowledgeError(f"no production knowledge index at {p}: {exc}") from exc
        if idx.get("format") != INDEX_FORMAT or not isinstance(idx.get("families"), list):
            raise KnowledgeError(f"{p} is not a production knowledge index ({INDEX_FORMAT})")
        return idx

    def available(self) -> bool:
        try:
            return bool(self.index["families"])
        except KnowledgeError:
            return False

    def family_keys(self) -> list[str]:
        return [f["family"] for f in self.index["families"]]

    def family(self, key: str) -> FamilyKnowledge:
        with self._lock:
            if key in self._fam:
                return self._fam[key]
            row = next((f for f in self.index["families"] if f["family"] == key), None)
            if row is None:
                raise KnowledgeError(f"no production knowledge for {key!r}; families: {', '.join(self.family_keys())}")
            try:
                data = json.loads((self.dir / row["file"]).read_text())
            except (OSError, ValueError) as exc:
                raise KnowledgeError(f"{row['file']}: {exc}") from exc
            probs = validate_manifest(data)
            if probs:
                raise KnowledgeError(f"{row['file']} is malformed — refused whole: " + "; ".join(probs[:5]))
            fk = FamilyKnowledge(data)
            self._fam[key] = fk
            return fk

    # ── is it still the code? ────────────────────────────────────────────────────

    def freshness(self, key: str, src: S.Source | None | bool = True, bundle_dir: Path | None = None, refresh: bool = False) -> dict:
        """Whether the manifest still describes the production code, and whether the bundle that would execute it was built from that code.

        state: `fresh` (the checkout's modules hash as recorded, or there is no checkout to compare and the bundle matches), `stale` (a module
        the family's entry names, or its rule engine imports, changed — listed), `unverifiable` (no checkout and no matching bundle).
        bundle: `matches` | `differs` (built from other code: evaluation is refused) | `absent`."""
        if not refresh and key in self._fresh:
            return self._fresh[key]
        fam = self.family(key)
        want = fam.data["source"]["sources"]
        out: dict = {"family": key, "manifest_commit": fam.data["source"].get("commit"), "extracted_from_dirty": bool(fam.data["source"].get("dirty_files"))}
        checkout = S.locate() if src is True else (src or None)
        if checkout is not None:
            changed, missing = [], []
            for f, h in want.items():
                p = checkout.root / f
                if not p.is_file():
                    missing.append(f)
                elif S.sha256(p) != h:
                    changed.append(f)
            out["checkout"] = "changed" if (changed or missing) else "same"
            if changed or missing:
                out["changed_files"] = changed[:20]
                out["missing_files"] = missing[:20]
        else:
            out["checkout"] = "absent"
        info = read_info(bundle_dir)
        if info is None:
            out["bundle"] = "absent"
        else:
            built = info.get("sources", {})
            diff = sorted(f for f, h in want.items() if built.get(f) != h)
            out["bundle"] = "differs" if diff else "matches"
            if diff:
                out["bundle_differs_in"] = diff[:20]
        if out["checkout"] == "changed":
            out["state"] = "stale"
        elif out["checkout"] == "same" or out["bundle"] == "matches":
            out["state"] = "fresh"
        else:
            out["state"] = "unverifiable"
        self._fresh[key] = out
        return out

    # ── which families a drawing's words point at ────────────────────────────────

    @cached_property
    def _vocab(self) -> tuple[dict[str, Counter], dict[str, float]]:
        per: dict[str, Counter] = {}
        for row in self.index["families"]:
            if not row.get("has_compute"):
                continue
            words: Counter = Counter()
            for t in _tokens(row["title"]):
                words[t] += 3
            for t in _tokens(row["family"].replace("_", " ")):
                words[t] += 2
            try:
                fam = self.family(row["family"])
            except KnowledgeError:
                continue
            for v in fam.views:
                for lab in v.get("labels", []):
                    for t in _tokens(lab):
                        words[t] += 1
            per[row["family"]] = words
        df = Counter(t for w in per.values() for t in set(w))
        n = max(1, len(per))
        idf = {t: math.log(1 + n / c) for t, c in df.items()}
        return per, idf

    def discover(self, texts: list[str], top: int = 4) -> list[dict]:
        """Families whose title, key and view names the drawing's printed words share — weighted by how few families share each word. A lead
        for the model to confirm on the drawing, never a classification (look-alike families share most words)."""
        printed = Counter(t for s in texts for t in set(_tokens(s)))
        per, idf = self._vocab
        out = []
        for fam, words in per.items():
            hits = {t: words[t] * idf[t] for t in words if t in printed}
            score = sum(hits.values())
            if score <= 0:
                continue
            out.append({"family": fam, "score": round(score, 2), "matched_words": sorted(hits, key=lambda t: -hits[t])[:10]})
        out.sort(key=lambda r: -r["score"])
        if len(out) > 1 and out[0]["score"] < 1.25 * out[1]["score"]:
            for r in out[:2]:
                r["close_call"] = True
        return out[:top]


_PK: ProductionKnowledge | None = None


def knowledge() -> ProductionKnowledge:
    global _PK
    if _PK is None:
        _PK = ProductionKnowledge()
    return _PK


def set_knowledge(pk: ProductionKnowledge | None) -> None:
    global _PK
    _PK = pk
