"""DXF → (Gemini proposes) → (validator decides) → parametric program.

    prog, report, info = ai_parametrize("drawing.dxf", view=0)

One call for the proposal, at most one more to repair what the validator rejected.
The geometric baseline is always there underneath: whatever Gemini gets wrong, the
drawing still regenerates exactly.
"""

from __future__ import annotations

import copy
import hashlib
import time
from pathlib import Path

from google.genai import errors as genai_errors

from ..analyse import analyse
from ..build import Decisions, build
from ..cadjson import cad_json
from ..display import scene
from ..dxf_read import read_dxf
from ..intent import unsplit_structures
from ..program import Program, from_model
from ..render import faithful_png, labelled_png, regions_png
from ..topology import of as topology_of
from ..validator import Report, apply
from ..views import detect_views, restrict
from .prompt import SYSTEM, facts_text, knowledge_text, refine_text, repair_text, task_text
from .schema import AIAnswer
from .vertex import Gemini, GeminiStopped, GeminiUnavailable


def _snapshot(an):
    return {
        "clusters": {cid: (c.name, c.accepted, list(c.gaps)) for cid, c in an.clusters.items()},
        "gap_clusters": {gid: g.cluster for gid, g in an.gaps.items()},
        "datums": {did: copy.copy(d) for did, d in an.datums.items()},
        "slot_datum": dict(an.slot_datum),
    }


def _restore(an, snap) -> None:
    for cid, (name, acc, gaps) in snap["clusters"].items():
        if cid in an.clusters:
            an.clusters[cid].name, an.clusters[cid].accepted, an.clusters[cid].gaps = name, acc, list(gaps)
    for gid, cl in snap["gap_clusters"].items():
        if gid in an.gaps:
            an.gaps[gid].cluster = cl
    an.datums = {did: copy.copy(d) for did, d in snap["datums"].items()}
    an.slot_datum = dict(snap["slot_datum"])


def prepare(path: str, view: int | None = None, region=None, drawing=None, analysis=None):
    """The drawing analysed afresh (apply() renames and splits candidates, so each validation starts clean). `drawing`:
    one view (or unit) of a sheet already read — a copy is analysed; `region` then frames its pictures. `analysis`: an
    analysis to start from instead (a sheet unit's own, so every candidate, occurrence and line id is the sheet's) —
    a copy is used, the original is never touched."""
    if analysis is not None:
        an = copy.deepcopy(analysis)
        unsplit_structures(an)
        snap = _snapshot(an)
        base = from_model(build(an, Decisions()))
        _restore(an, snap)
        return an, base, region if region is not None else an.drawing.extent, snap
    if drawing is not None:
        dr = copy.deepcopy(drawing)
        an = analyse(dr)
        snap = _snapshot(an)
        base = from_model(build(an, Decisions()))
        _restore(an, snap)
        return an, base, region if region is not None else dr.extent, snap
    dr, _ = read_dxf(path)
    if view is not None and region is None:
        views = detect_views(dr)
        region = views[view]["bbox"] if 0 <= view < len(views) else None
    if region is not None:
        restrict(dr, region)
    an = analyse(dr)
    snap = _snapshot(an)
    base = from_model(build(an, Decisions()))
    _restore(an, snap)
    return an, base, region, snap


def image_labels(an, base: Program) -> dict[str, tuple[str, float]]:
    """The set-out lines labelled on the picture (by the same ids the tools use): the lines the baseline's sizes span,
    the stated levels and the construction axes — at most 90, so the picture stays legible."""
    wanted: list[str] = []
    for p in base.params.values():
        if p.measures:
            wanted.extend(p.measures)
    wanted += [d for d, *_ in an.stated_levels] + [a for a in an.axes]
    seen, labels = set(), {}
    for d in wanted:
        if d in an.datums and d not in seen and len(labels) < 90:
            seen.add(d)
            labels[d] = (an.datums[d].axis, an.datums[d].value)
    return labels


def images_for(an, base: Program, region) -> list[bytes]:
    dr = an.drawing
    pts = {it.index: it.pts for it in dr.items}
    sc = scene(an, pts, {}, {})
    labels = image_labels(an, base)
    x0, y0, x1, y1 = dr.extent
    pad = 0.08 * max(x1 - x0, y1 - y0, 1.0)
    bbox = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
    view = [p for p in sc if p.get("role") != "fixed"]
    return [faithful_png(dr.path, region), labelled_png(view, labels, bbox), regions_png(view, topology_of(an).regions, bbox)]


def _context(path: str, view, region):
    an, base, region, snap = prepare(path, view, region)
    facts = cad_json(an, base, for_ai=True)
    images = images_for(an, base, region)
    src = hashlib.sha256(Path(an.drawing.path).read_bytes()).hexdigest()
    keys = [f"faithful:{src}:{region}", "", ""]  # the faithful render is not byte-stable; its source is
    return an, snap, facts, images, keys, region


def ai_parametrize(path: str, view: int | None = None, region=None, rounds: int = 2, log=print,
                   hold_existing: bool = False, selection: dict | None = None, instructions: str = "",
                   gem: Gemini | None = None, on_event=None, stop=None) -> tuple[Program, Report, dict]:
    """Gemini proposes (following the person's `instructions`, if any), the validator decides, up to `rounds - 1`
    repair rounds. `gem`: a client to reuse (its prompt cache survives for follow-ups; the caller closes it).
    `on_event`: progress — Gemini's thought summaries and each round's verdict — as it happens."""
    t0 = time.perf_counter()
    an, snap, facts, images, keys, region = _context(path, view, region)
    texts = [knowledge_text(), facts_text(facts), task_text(instructions)]
    own = gem is None
    gem = gem or Gemini()
    try:
        log(f"asking {gem.cfg.model} @{gem.cfg.thinking} ({len(facts['topology']['regions'])} regions, {len(facts['entities'])} entities, "
            f"{len(facts.get('candidates', []))} candidate values, {len(images)} images)…")
        return _rounds(gem, an, snap, texts, images, keys, rounds, log, hold_existing, selection, t0, path, region, "parametrize", on_event,
                       instructions, stop)
    finally:
        if own:
            for problem in gem.close():  # this run's prompt caches; they would expire on their own anyway
                log(f"prompt cache not deleted: {problem}")


def ai_refine(path: str, previous: dict, request: str, region=None, rounds: int = 2, log=print, hold_existing: bool = False,
              selection: dict | None = None, instructions: str = "", gem: Gemini | None = None, on_event=None,
              stop=None) -> tuple[Program, Report, dict]:
    """A person's follow-up on an answer ("make the wing length a parameter", "R12 and R13 are one part", "keep the
    tracks as drawn"): Gemini revises its previous answer; the drawing, its facts and pictures — the cached prefix —
    are unchanged, so only the request and the previous answer are new input."""
    t0 = time.perf_counter()
    an, snap, facts, images, keys, region = _context(path, None, region)
    _restore(an, snap)
    _prog, rep = apply(an, previous, hold_existing=hold_existing, selection=selection)
    _restore(an, snap)
    texts = [knowledge_text(), facts_text(facts), refine_text(previous, request, rep.errors(), instructions)]
    own = gem is None
    gem = gem or Gemini()
    try:
        log(f"asking {gem.cfg.model} @{gem.cfg.thinking} to revise: {request[:80]}")
        return _rounds(gem, an, snap, texts, images, keys, rounds, log, hold_existing, selection, t0, path, region, "revise", on_event,
                       instructions, stop)
    finally:
        if own:
            for problem in gem.close():
                log(f"prompt cache not deleted: {problem}")


def _rounds(gem, an, snap, texts, images, keys, rounds, log, hold_existing, selection, t0, path, region, label, on_event, instructions="",
            stop=None):
    def emit(event: dict) -> None:
        if on_event:
            on_event(event)

    def verdict(r: int, rep: Report) -> None:
        log(f"round {r}: accepted {rep.accepted}, rejected {rep.rejected}")
        emit({"kind": "round", "round": r, "accepted": rep.accepted, "rejected": rep.rejected,
              "errors": [f"{e['code']} {e['item']}: {e['message']}"[:220] for e in rep.errors()][:8]})

    # knowledge + CAD JSON (and the pictures) repeat in every round: they are the cached prefix
    answer, usage = gem.ask(SYSTEM, texts, images, AIAnswer, label=label, image_keys=keys, shared=2, on_event=emit, stop=stop)
    usages = [usage]
    prog, rep = apply(an, answer, hold_existing=hold_existing, selection=selection)
    verdict(1, rep)
    best = (len(rep.errors()), answer)  # a repair round may do worse: the round with the fewest rejections is kept
    for r in range(1, rounds):
        errors = rep.errors()
        if not errors:
            break
        try:
            fixed, usage = gem.ask(SYSTEM, texts[:-1] + [repair_text(answer, errors, instructions)], images, AIAnswer, label=f"repair{r}", image_keys=keys,
                                   shared=2, on_event=emit, stop=stop)
        except GeminiStopped:  # the person stopped the repair: what was validated so far stands
            log(f"stopped during repair round {r}; keeping the validated round")
            emit({"kind": "stopped", "text": f"stopped during repair {r}: the best validated round so far is kept"})
            rep.warn("AI", "repair", f"stopped by the person during repair round {r}; the best validated round is kept")
            break
        except (GeminiUnavailable, genai_errors.APIError) as exc:  # the repair improves, it is not required: keep what was validated
            log(f"repair round failed ({exc}); keeping the validated round {r}")
            emit({"kind": "retry", "label": f"repair{r}", "why": f"no answer ({str(exc)[:120]}); round {r} kept"})
            rep.warn("AI", "repair", f"repair round did not answer ({str(exc)[:120]}); round {r} kept as validated")
            break
        usages.append(usage)
        _restore(an, snap)
        answer = fixed
        prog, rep = apply(an, answer, hold_existing=hold_existing, selection=selection)
        verdict(r + 1, rep)
        if len(rep.errors()) <= best[0]:
            best = (len(rep.errors()), answer)
    _restore(an, snap)
    if best[1] is not answer:  # an earlier round was better; apply it again on a fresh reading
        answer = best[1]
        prog, rep = reapply(path, answer, region, hold_existing=hold_existing, selection=selection)
        log(f"kept the round with {best[0]} rejection(s)")
        emit({"kind": "note", "text": f"kept the round with {best[0]} rejection(s)"})
    info = {"answer": answer, "path": path, "usage": usages, "seconds": round(time.perf_counter() - t0, 1), "region": region,
            "tokens_in": sum(u.get("input_tokens", 0) + u.get("wasted", {}).get("input_tokens", 0) for u in usages if not u.get("cached")),
            "tokens_out": sum(u.get("output_tokens", 0) + u.get("thinking_tokens", 0) + u.get("wasted", {}).get("output_tokens", 0)
                              + u.get("wasted", {}).get("thinking_tokens", 0) for u in usages if not u.get("cached")),
            "tokens_cached": sum(u.get("vertex_cached_tokens", 0) for u in usages if not u.get("cached"))}
    return prog, rep, info


def reapply(path: str, answer: dict, region=None, hold_existing: bool = False, selection: dict | None = None) -> tuple[Program, Report]:
    """Re-apply a validated answer with different choices (hold existing work, a person's selection) — no AI call."""
    an, _base, _region, _snap = prepare(path, None, region)
    return apply(an, answer, hold_existing=hold_existing, selection=selection)
