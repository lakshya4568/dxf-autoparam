"""The agent's context, measured — no model, no cost: the real run, the real engine, a scripted model.

  * a long run sends a bounded context: older turns are folded into ONE working state (the instruction, the checklist, the facts on
    record, the status) built from the sheet — the conversation keeps only the last exchanges, verbatim
  * the whole drawing is understood up front (the drawing overview, in the cached prefix) and looked at in detail on demand (a view,
    a component with a crop labelled by the same ids, annotations, layers, duplicates)
  * deterministic results are reused while their inputs are unchanged; a change invalidates only what depends on it
  * the agent's checklist and the facts it established are kept on the sheet (saved, reused, marked stale when the drawing changes)
  * batch writes: semantic decisions and renames, several per call, each judged on its own; refusals are results, not crashes

Sizes are characters of what each request re-sends besides its cached prefix (measured on the request contents); the model's own
token counts come from live runs only and are never invented here."""

from __future__ import annotations

from test_run import INSTRUCTION, session, wait

from dxf_autoparam.ai.loop import history_size
from dxf_autoparam.ai.scripted import call
from dxf_autoparam.ai.understanding_tools import component_context, drawing_overview, learned_now, notes_of, parameter_review, view_context


def reads(n: int, uid: str) -> list:
    """A run that reads a lot (and keeps its checklist up to date, so it is never nudged for looking without editing)."""
    turns = [[call("drawing_overview")]]
    for k in range(n):
        turns.append(
            [
                call("inspect_annotations", limit=15, offset=k),
                call("inspect_layers"),
                call("inspect_view", view="V01"),
                call("update_checklist", items=[{"id": f"C{k}", "text": f"looked at the notes, page {k}", "status": "done"}]),
            ]
        )
    return [*turns, [call("finish", summary="read")], [call("finish", summary="read")]]


THOUGHT = "I compared the section with the plan view and checked which set-out lines they share before planning the span change. " * 12


def run(tmp_path, n: int, **options):
    """A long run; the model's own turns carry thought summaries the size a live run's do (~1.4 k characters)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    sheet, _uid, _g, gem = session(tmp_path, reads(n, "U01_02"), thoughts=[THOUGHT] * (n + 4))
    r = sheet.start_run({"instruction": INSTRUCTION, "scope": {"kind": "drawing"}, "options": options})
    p = wait(sheet, r["run"], timeout=180)
    return sheet, gem, p


def test_a_long_run_sends_a_bounded_context_and_a_full_one_grows(tmp_path):
    _s1, compact_gem, p1 = run(tmp_path / "a", 24)
    _s2, full_gem, p2 = run(tmp_path / "b", 24, full_history=True)
    c_sizes = [history_size(r["history"])["chars"] for r in compact_gem.requests]
    f_sizes = [history_size(r["history"])["chars"] for r in full_gem.requests]
    c_turns = [history_size(r["history"])["model_turns"] for r in compact_gem.requests]
    assert len(c_sizes) == len(f_sizes) >= 24
    # the full conversation keeps every model turn (its thoughts are never trimmed): it grows; the compacted one keeps a bounded window
    assert history_size(full_gem.requests[-1]["history"])["model_turns"] >= 24
    assert max(c_turns) <= 12
    assert c_sizes[-2] < 0.75 * f_sizes[-2], (c_sizes[-2], f_sizes[-2])
    assert sum(c_sizes) < 0.75 * sum(f_sizes), (sum(c_sizes), sum(f_sizes))
    # the working state stands at the head of the compacted conversation: the person's words, the checklist, the status
    head = compact_gem.requests[-1]["history"][0].parts[0].text
    assert "THE PERSON'S INSTRUCTION" in head and INSTRUCTION[:40] in head and "CHECKLIST" in head and "WORKING STATE" in head
    assert "THE SHEET, UNIT BY UNIT: " in head and "units parametrized" in head, "where the task stands survives the fold: coverage is not asked again for it"
    assert any(e["kind"] == "note" and "context compacted" in e.get("text", "") for e in p1["events"])
    # what is done is done once: both runs did the same work
    assert len([e for e in p1["events"] if e["kind"] == "tool"]) == len([e for e in p2["events"] if e["kind"] == "tool"])


def test_an_unchanged_result_is_not_sent_twice(tmp_path):
    _s, gem, _p = run(tmp_path, 10)
    markers = [
        fr.response["result"] for seen in gem.seen for fr in seen if isinstance(fr.response.get("result"), dict) and fr.response["result"].get("unchanged")
    ]
    assert len(markers) >= 10, "inspect_layers / inspect_view asked again with nothing changed: answered with a pointer"
    assert all("same_as" in m and m["revision"] is not None for m in markers)


def test_the_whole_drawing_is_in_the_cached_prefix_once(tmp_path):
    _s, gem, _p = run(tmp_path, 2)
    prefix_text = next(p.text for p in gem.requests[0]["prefix"] if getattr(p, "text", None))
    assert "DRAWING OVERVIEW" in prefix_text and '"views"' in prefix_text and '"layers"' in prefix_text
    assert all(r["prefix"] is gem.requests[0]["prefix"] or r["prefix"] == gem.requests[0]["prefix"] for r in gem.requests), (
        "the prefix does not change during the run"
    )


def test_overview_view_and_component_contexts_name_exact_geometry(tmp_path):
    sheet, uid, _g, _gem = session(tmp_path, [])
    sm = sheet.sm
    ov = drawing_overview(sm)
    assert {v["id"] for v in ov["views"]} >= set(sm.unit_of_view) and ov["layers"] and ov["annotations"]["total"] > 0
    assert ov["drawing"]["faithful"] is True
    vc = view_context(sm, "V01")
    assert vc["view"]["unit"] and "components" in vc and "dimensions" in vc and "notes" in vc
    u = sm.unit(uid)
    part = next(iter(u.prog.intent["parts"]))
    rec, unit, _ents, _box = component_context(sm, uid, part=part)
    assert unit == uid and rec["entities"] and all(e["points_mm"] and e["local_mm"] and e["handle"] for e in rec["entities"])
    x0, _y0 = rec["component"]["local_origin_mm"]
    e0 = rec["entities"][0]
    assert abs(e0["points_mm"][0][0] - x0 - e0["local_mm"][0][0]) < 0.11, "local coordinates are measured from the component's own corner"


def test_a_component_crop_is_labelled_with_the_ids_the_tools_use(tmp_path):
    sheet, uid, _g, _gem = session(tmp_path, [])
    from dxf_autoparam.ai.run import Run, SheetBench

    sheet.get_pictures()
    run_ = Run(sheet, "R9", "look", {"kind": "drawing"})
    bench = SheetBench(run_)
    part = next(iter(sheet.sm.unit(uid).prog.intent["parts"]))
    rec = bench.understanding.call("inspect_component", {"unit": uid, "part": part, "picture": True})
    labelled = {t["id"] for t in rec["_image"]["meta"].get("entities_labelled", [])}
    assert {e["id"] for e in rec["entities"]} & labelled, "the crop's labels are the ids of the entity list"


def test_results_are_reused_and_a_change_invalidates_only_what_depends_on_it(tmp_path):
    sheet, uid, _g, _gem = session(tmp_path, [])
    sm = sheet.sm
    drawing_overview(sm)
    h, m = sm.memo.hits, sm.memo.misses
    drawing_overview(sm)
    assert sm.memo.hits > h and sm.memo.misses == m
    u = sm.unit(uid)
    name = next(n for n, p in u.prog.params.items() if p.kind == "length")
    assert sm.apply({f"{uid}.{name}": u.prog.params[name].value + 100}).ok
    before = sm.memo.misses
    drawing_overview(sm)  # the overview carries the values: recomputed …
    stats = sm.memo.stats()
    assert sm.memo.misses == before + 1, stats
    assert any("drawing_overview" in line for line in stats["recent"])
    assert not any("sheet_annotations" in line for line in stats["recent"]), "… the notes' associations are not: values do not change them"


def test_checklist_and_facts_are_kept_saved_and_marked_stale(tmp_path):
    sheet, _uid, _g, _gem = session(tmp_path, [])
    sm = sheet.sm
    from dxf_autoparam.ai.run import Run, SheetBench

    bench = SheetBench(Run(sheet, "R9", "look", {"kind": "drawing"}))
    bench.write("update_checklist", {"items": [{"id": "A", "text": "read the sheet", "status": "done"}, {"text": "plan the span", "status": "todo"}]})
    bench.write(
        "record_learned",
        {
            "facts": [
                {"fact": "V01 and V02 are one box in projection", "about": "views", "evidence": "they share 6 set-out lines"},
                {"fact": "no evidence given"},
            ]
        },
    )
    assert [c["text"] for c in notes_of(sm)["checklist"]] == ["read the sheet", "plan the span"]
    assert [f["fact"] for f in learned_now(sm)] == ["V01 and V02 are one box in projection"], "a fact without evidence is not kept"
    path = tmp_path / "p.json"
    sm.save(str(path))
    from dxf_autoparam.crossview import SheetModel

    back = SheetModel.load(str(path))
    assert notes_of(back)["checklist"] and learned_now(back)[0]["fact"].startswith("V01")
    # the views change (merged): what was learned about them is marked stale, not trusted blindly
    vs = [g.id for g in sm.layout.views()][:2]
    sm.merge_views(vs)
    assert learned_now(sm)[0].get("stale") is True


def test_batch_semantics_and_renames_are_judged_item_by_item(tmp_path):
    sheet, uid, _g, _gem = session(tmp_path, [])
    sm = sheet.sm
    from dxf_autoparam.ai.run import Run, SheetBench

    bench = SheetBench(Run(sheet, "R9", "look", {"kind": "drawing"}))
    layer = sm.dr.items[0].layer
    item, _note = bench.write(
        "accept_semantics",
        {
            "status": [
                {"by": "layer", "key": layer, "status": "proposed", "why": "the box is new work"},
                {"by": "layer", "key": "NOPE", "status": "existing", "why": "x"},
            ]
        },
    )
    v = bench.verdict(item)
    assert v["accepted"] == 1 and v["rejected"] and sm.semantics["status"][-1]["who"] == "agent"
    rev = sm.revision
    assert sm.undo() and not sm.semantics["status"] and sm.revision == rev + 1
    u = sm.unit(uid)
    a, b = list(u.prog.params)[:2]
    item, _note = bench.write("rename_values", {"items": [{"from": f"{uid}.{a}", "to": "ClearSpanTest"}, {"from": f"{uid}.{b}", "to": "not pascal"}]})
    v = bench.verdict(item)
    assert v["renamed"] and v["rejected"]
    assert "ClearSpanTest" in sm.unit(uid).prog.params


def test_review_proposes_names_from_evidence_and_never_merges_equal_values(tmp_path):
    sheet, uid, _g, _gem = session(tmp_path, [])
    rev = parameter_review(sheet.sm, uid)
    assert rev["values"] and set(rev["counts"]) <= {
        "shared",
        "named_input",
        "level",
        "worked_out",
        "duplicate_candidate",
        "local_measurement",
        "independent_input",
        "generic_input",
    }
    for r in rev["values"]:
        if r["class"] == "duplicate_candidate":
            assert "equal is not the same design value" in " ".join(r["evidence"])
    assert any("rename_values keeps" in rule for rule in rev["rules"])


def test_a_refused_read_is_a_result_not_a_crash(tmp_path):
    sheet, _uid, _g, _gem = session(
        tmp_path, [[call("impact_plan", name="NoSuchValue")], [call("inspect_view", view="V99")], [call("finish", summary="x")], [call("finish", summary="x")]]
    )
    r = sheet.start_run({"instruction": INSTRUCTION, "scope": {"kind": "drawing"}})
    p = wait(sheet, r["run"], timeout=60)
    bad = [e for e in p["events"] if e["kind"] == "tool" and e["name"] in ("impact_plan", "inspect_view")]
    assert len(bad) == 2 and all(not e["ok"] for e in bad)
    assert p["status"] not in ("error",)


def test_one_name_for_two_sizes_is_asked_before_finish(tmp_path):
    # a live run (7A, 2026-10-26) named the existing box's 600 mm slab and the proposed box's 500 mm slab both TopSlabThickness: a hint said so and was
    # passed over, the person met two values of one name. It is an open matter now, asked once before finish like a coverage gap.
    sheet, _uid, _g, _gem = session(tmp_path, [])
    from dxf_autoparam.ai.run import Run, SheetBench

    bench = SheetBench(Run(sheet, "R9", "Make the drawing parametric.", {"kind": "drawing"}))
    sheet.sm.unlinked_repeats = lambda: [{"name": "TopSlabThickness", "units": ["U05", "U08"], "joined": False, "values": {"U05": 600.0, "U08": 500.0}, "same": False}]
    open_ = bench.open_matters()
    assert any(m.startswith("one name, two sizes: TopSlabThickness") and "rename_values" in m for m in open_), open_
