"""The values the engine measured itself (ThkY1, GapX6 …) and nobody named: kept as drawn, in one undoable step, with the drawing exactly as it was —
and every one of them released again if a person wants it. What a person set, a note states or another view follows is never kept as drawn."""

from __future__ import annotations

import pytest

from dxf_autoparam import generic
from dxf_autoparam.analyse import PREFIX
from dxf_autoparam.crossview import SheetError, SheetModel
from dxf_autoparam.plan_bench import Box, box_answer, box_gad
from dxf_autoparam.workspace import SheetSession


def box_sheet(tmp_path, keep: bool = False, name: str = "box"):
    g = box_gad(tmp_path / f"{name}.dxf", Box())
    sm = SheetModel.open(g["path"])
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    sm.commit_answer(uid, box_answer(sm, uid, g["box"], g["handles"]), keep_unnamed_as_drawn=keep)
    return sm, uid


def drawing(sm: SheetModel, uid: str):
    r = sm.regenerate(units={uid})
    return {i: [tuple(p) for p in pts] for i, pts in r.reg.pts.items()}, {i: sm.dr.items[i].text if i not in r.reg.texts else r.reg.texts[i] for i in
                                                                          set(r.reg.texts)}


def same(a, b) -> bool:
    return a[0].keys() == b[0].keys() and all(abs(x[0] - y[0]) < 1e-9 and abs(x[1] - y[1]) < 1e-9 for i in a[0] for x, y in zip(a[0][i], b[0][i], strict=True))


def test_the_generated_name_pattern_covers_every_name_the_analysis_can_give():
    for prefix, _label in PREFIX.values():
        assert generic.is_generated(f"{prefix}7") and generic.is_generated(f"U01.{prefix}12") and generic.is_generated(f"U02_03.{prefix}1")
    for name in ("ClearSpan", "TopSlabThickness", "Gap", "GapX", "GapX6a", "ExistingGapX6", "U01.ClearSpan"):
        assert not generic.is_generated(name), name
    assert generic.natural("GapX2") < generic.natural("GapX10")


def test_a_commit_keeps_what_nobody_named_as_drawn_and_the_drawing_does_not_change(tmp_path):
    plain, uid = box_sheet(tmp_path, name="plain")
    kept_sm, _ = box_sheet(tmp_path, keep=True, name="kept")
    before = {n for n, p in plain.unit(uid).prog.params.items() if generic.is_generated(n) and p.source != "ai"}
    assert before, "the box has measured sizes nobody named"
    after_params = kept_sm.unit(uid).prog.params
    left = {n for n in after_params if generic.is_generated(n) and after_params[n].source != "ai"}
    rows = kept_sm.units[uid].answer["frozen"]
    assert rows and {r["name"] for r in rows} == before - left, "every generated size nobody used is recorded, with its value and what it measured"
    assert all({"name", "value", "unit", "label", "measures", "why"} <= set(r) for r in rows)
    assert not (before - left) & set(after_params), "they are no longer inputs"
    assert same(drawing(plain, uid), drawing(kept_sm, uid)), "the drawing is exactly what it was"
    assert not (set(plain.unit(uid).prog.params) - before - set(after_params)), "nothing a person or the agent named went with them"


def test_purge_is_one_undoable_step_idempotent_and_has_a_dry_run(tmp_path):
    sm, uid = box_sheet(tmp_path)
    shot = drawing(sm, uid)
    rev, n_values = sm.revision, len(sm.current())
    dry = sm.purge_unclaimed_generic_values(dry_run=True)
    assert dry["dry_run"] and dry["would_keep"] > 0 and sm.revision == rev and len(sm.current()) == n_values, "a dry run changes nothing"
    out = sm.purge_unclaimed_generic_values()
    assert out["kept"] == dry["would_keep"] and out["revision"] == rev + 1 and not out["left_as_inputs"]
    assert len(sm.current()) == n_values - out["kept"] and same(drawing(sm, uid), shot)
    again = sm.purge_unclaimed_generic_values()
    assert again["kept"] == 0 and again["revision"] == rev + 1, "idempotent: nothing left to keep, no step made"
    assert sm.undo() and len(sm.current()) == n_values and same(drawing(sm, uid), shot), "one undo gives every one back"


def test_what_a_person_changed_a_note_states_or_another_view_follows_is_not_kept_as_drawn(tmp_path):
    sm, uid = box_sheet(tmp_path)
    prog = sm.unit(uid).prog
    names = [n for n, p in prog.params.items() if generic.is_generated(n) and p.source != "ai" and p.kind == "length"]
    changed = names[0]
    assert sm.apply({f"{uid}.{changed}": prog.params[changed].value + 10}).ok
    linked = sorted(generic.linked_names(sm.unit(uid).prog) & set(names))
    assert changed not in sm.unclaimed_generic(uid), "a value a person set is theirs"
    assert not set(linked) & set(sm.unclaimed_generic(uid)), "a note that states a size keeps following it"
    sm.purge_unclaimed_generic_values()
    after = sm.unit(uid).prog.params
    assert changed in after and all(n in after for n in linked)
    # a size another view follows
    sm2, uid2 = box_sheet(tmp_path, name="shared")
    cand = next(n for n in sm2.unit(uid2).prog.params if generic.is_generated(n))
    sm2.share("SharedSize", [(uid2, cand)])
    assert cand not in sm2.unclaimed_generic(uid2), "a shared binding is a use"


def test_release_gives_sizes_back_as_inputs_without_moving_anything(tmp_path):
    sm, uid = box_sheet(tmp_path, keep=True)
    rows = sm.units[uid].answer["frozen"]
    assert rows
    shot = drawing(sm, uid)
    one = rows[0]["name"]
    out = sm.release_frozen(uid, [one])
    assert out["released"] == [one] and one in sm.unit(uid).prog.params and len(sm.units[uid].answer["frozen"]) == len(rows) - 1
    assert same(drawing(sm, uid), shot)
    sm.release_frozen(uid)
    assert not sm.units[uid].answer["frozen"] and {r["name"] for r in rows} <= set(sm.unit(uid).prog.params)
    with pytest.raises(SheetError):
        sm.release_frozen(uid)
    with pytest.raises(SheetError):
        sm.release_frozen(uid, ["NoSuchSize"])


def test_the_project_keeps_what_was_kept_as_drawn(tmp_path):
    sm, uid = box_sheet(tmp_path, keep=True)
    path = tmp_path / "p.autoparam.json"
    sm.save(str(path))
    back = SheetModel.load(str(path), dxf=sm.path)
    assert back.units[uid].answer["frozen"] == sm.units[uid].answer["frozen"]
    assert set(back.unit(uid).prog.params) == set(sm.unit(uid).prog.params) and same(drawing(back, uid), drawing(sm, uid))


def test_a_unit_nobody_parametrized_has_nothing_to_keep_as_drawn(tmp_path):
    g = box_gad(tmp_path / "box.dxf", Box())
    sm = SheetModel.open(g["path"])
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    sm.unit(uid)
    with pytest.raises(SheetError, match="not parametrized"):
        sm.purge_unclaimed_generic_values(uid)
    assert sm.purge_unclaimed_generic_values()["kept"] == 0, "the sheet-wide purge only touches parametrized units"


def test_the_page_is_told_which_values_are_generic_what_is_kept_and_what_is_only_measured(tmp_path):
    sm, uid = box_sheet(tmp_path, keep=True)
    sheet = SheetSession()
    sheet.sm = sm
    info = sheet.unit(uid)
    assert info["revision"] == sm.revision and info["frozen"] == sm.units[uid].answer["frozen"]
    assert {p["name"] for p in info["params"] if p["source"] == "ai"} and not any(p["generic"] for p in info["params"] if p["source"] == "ai")
    assert all(p["generic"] == generic.is_generated(p["name"]) for p in info["params"] if p["source"] != "ai")
    assert next(u for u in sheet.summary()["units"] if u["id"] == uid)["kept_as_drawn"] == len(info["frozen"])
    out = sheet.edit("purge_generic", {"dry_run": True})["result"]
    assert out["dry_run"] and out["would_keep"] == 0


def test_a_part_kept_as_drawn_can_be_unlocked_and_its_named_sizes_are_inputs_again(tmp_path):
    from test_binding import mini_gad

    from dxf_autoparam.ai.agent import Workbench
    from dxf_autoparam.ai.context import SheetScope
    from dxf_autoparam.topology import of

    sm = SheetModel.open(mini_gad(tmp_path / "mini.dxf"))
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    an = sm.pristine_analysis(uid)
    u = an.drawing.units_mm
    span = next(c.id for c in an.clusters.values() if round(c.value * u) == 2400 and "x" in c.axes)
    outer = max(of(an).regions, key=lambda r: (r.bbox[2] - r.bbox[0]) * (r.bbox[3] - r.bbox[1]))
    bench = Workbench(sm.path, analysis=an, scope=SheetScope(sm, uid))
    bench.write("define_part", {"name": "ExistingBox", "type": "box", "level": "assembly", "regions": [outer.id], "existing": True, "parametrize": False})
    bench.write("define_parameter", {"name": "ExistingSpan", "part": "ExistingBox", "candidate": span, "occurrences": ["all"]})
    bench.validate(final=True)
    sm.commit_answer(uid, bench.answer)
    sheet = SheetSession()
    sheet.sm = sm
    info = sheet.unit(uid)
    row = next(m for m in info["measured"] if m["name"] == "ExistingSpan")
    assert row["part"] == "ExistingBox" and row["held"] and row["existing"] and abs(row["value"] - 2400) < 1e-6 and row["between"]
    assert "ExistingSpan" not in {p["name"] for p in info["params"]}
    shot = drawing(sm, uid)
    out = sheet.edit("unlock_part", {"unit": uid, "part": "ExistingBox"})["result"]
    assert "ExistingBox" in out["unlocked"]
    now = sheet.unit(uid)
    assert "ExistingSpan" in {p["name"] for p in now["params"]} and not any(m["name"] == "ExistingSpan" for m in now["measured"])
    assert same(drawing(sm, uid), shot), "unlocking changes no line: it only makes the size an input"
    assert sm.apply({f"{uid}.ExistingSpan": 2600}).ok, "and now it can be edited"
    with pytest.raises(SheetError):
        sm.unlock_part(uid, "NoSuchPart")
