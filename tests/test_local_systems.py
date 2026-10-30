"""Local systems: every view of a sheet is a unit of its own — its own set-out lines, dependency graph, values and frame — and views drawn in
projection are linked by explicit constraints (projection.py): a size one names between faces both show is ONE shared value bound in both, their
faces stay in line, and a side chosen for a shared size is chosen in both. A change regenerates the views it reaches and nothing else."""

from __future__ import annotations

import copy
import json

import ezdxf
import pytest
from test_sheet import rect, text

from dxf_autoparam.crossview import SheetModel
from dxf_autoparam.frames import view_frame
from dxf_autoparam.plan_bench import Box, box_answers, box_gad


def box(tmp_path, b: Box | None = None):
    """The generated box on local systems: its section and its plan, each committed with the generator's own answer (section first)."""
    g = box_gad(tmp_path / "box.dxf", b or Box())
    sm = SheetModel.open(g["path"])
    answers = box_answers(sm, g["box"], g["handles"])
    sec, pln = list(answers)
    for uid, ans in answers.items():
        sm.commit_answer(uid, ans)
    return sm, sec, pln, g


def pts_of(sm, sr, uid):
    """Every structural vertex of a unit's view after a regeneration, sheet coordinates."""
    u = sm.unit(uid)
    out = {}
    for k, it in enumerate(u.sub.items):
        s = u.back[k]
        if sm.dr.items[s].role.value == "structural":
            out[s] = [tuple(round(c, 6) for c in p) for p in sr.reg.pts.get(s, sm.dr.items[s].pts)]
    return out


def xs(pts):
    return sorted({round(p[0], 3) for ps in pts.values() for p in ps})


def test_every_view_is_a_unit_of_its_own_with_a_frame_that_maps_back_exactly(tmp_path):
    sm, sec, pln, _g = box(tmp_path)
    assert sm.systems == "views" and sec != pln and all(len(u.views) == 1 for u in sm.units.values())
    lk = next(lk for lk in sm.links if sm.is_linked(lk))
    assert {sm.unit_of_view[lk["a"]], sm.unit_of_view[lk["b"]]} == {sec, pln} and lk["axis"] == "x"
    for uid in (sec, pln):
        fr = view_frame(sm, sm.units[uid].views[0])
        x0, y0, x1, y1 = sm.layout.group(fr.view).bbox
        for x, y in ((x0, y0), (x1, y1), ((x0 + x1) / 2, (y0 + y1) / 3)):
            assert fr.to_sheet(*fr.to_local(x, y)) == pytest.approx((x, y), abs=1e-9)
    sec_fr = view_frame(sm, sm.units[sec].views[0])
    assert sec_fr.level and sec_fr.level["name"] == "BedLevel", "the section is read from its stated level"


def test_a_size_both_views_show_is_one_shared_value_bound_in_both(tmp_path):
    sm, sec, pln, _g = box(tmp_path)
    shared = {p.name: {b.unit: b.status for b in p.bindings} for p in sm.shared.values()}
    assert shared == {"ClearSpan": {sec: "drives", pln: "drives"}, "OuterWall": {sec: "drives", pln: "drives"}}
    assert "TopSlab" in sm.unit(sec).prog.params and "TopSlab" not in sm.unit(pln).prog.params, "a size the plan does not show stays the section's"
    assert any(p.source == "projection" for p in sm.shared.values())


def test_a_shared_change_moves_both_views_alike_and_nothing_else(tmp_path):
    sm, sec, pln, _g = box(tmp_path)
    r = sm.regenerate({"ClearSpan": 3400.0})
    assert r.ok, r.errors
    vs, vp = sm.units[sec].views[0], sm.units[pln].views[0]
    assert set(r.by_view) == {vs, vp}
    assert r.measured["ClearSpan"] == {sec: pytest.approx(3400.0), pln: pytest.approx(3400.0)}
    # the plan's faces are the section's faces, where they were drawn in line
    plan_x, sec_x = xs(pts_of(sm, r, pln)), xs(pts_of(sm, r, sec))
    drawn = sm.regenerate()
    common = set(xs(pts_of(sm, drawn, pln))) & set(xs(pts_of(sm, drawn, sec)))
    assert len(common) >= 4 and len(set(plan_x) & set(sec_x)) >= len(common), "every face drawn in line is still in line"


def test_a_value_of_one_view_moves_that_view_only(tmp_path):
    sm, sec, pln, _g = box(tmp_path)
    before = pts_of(sm, sm.regenerate(), pln)
    r = sm.regenerate({f"{sec}.TopSlab": 450.0})
    assert r.ok, r.errors
    assert set(r.by_view) == {sm.units[sec].views[0]}, "the plan shows no top slab: nothing of it moves"
    assert pts_of(sm, r, pln) == before


def person_plans(sm, uid):
    from dxf_autoparam import design_intent

    return [p for p in (sm.unit(uid).answer or {}).get("plans", []) if p.get("status") == "accepted" and not design_intent.derived(p)]


@pytest.mark.parametrize("mode", ["start", "end", "centre"])
def test_a_side_chosen_in_one_view_is_chosen_in_the_view_drawn_in_projection(tmp_path, mode):
    sm, sec, pln, _g = box(tmp_path, Box(cells=1))  # one cell: the span's two lines are the faces that stay or move
    got = sm.anchor("ClearSpan", sec, mode)
    assert got["mode"] == mode and [x["unit"] for x in got["projection"]] == [pln] and got["projection"][0]["mode"] == mode
    r = sm.regenerate({"ClearSpan": 3400.0})
    assert r.ok, r.errors
    for uid in (sec, pln):
        g = next(x for x in sm.growth("ClearSpan") if x["unit"] == uid)
        stays = g["from"] if mode == "start" else g["to"] if mode == "end" else None
        u = sm.unit(uid)
        now = u.prog.datum_values({"ClearSpan": 3400.0})
        if stays:
            assert now[stays] == pytest.approx(u.an.datums[stays].value), f"{uid}: {stays} stays"
        else:
            mid0 = (u.an.datums[g["from"]].value + u.an.datums[g["to"]].value) / 2
            assert (now[g["from"]] + now[g["to"]]) / 2 == pytest.approx(mid0), f"{uid}: its centre stays"
    assert person_plans(sm, sec) and person_plans(sm, pln)
    assert sm.undo() and not person_plans(sm, sec) and not person_plans(sm, pln), "one undo takes the choice back in both views"


@pytest.mark.parametrize("mode", ["start", "end"])
def test_bottom_and_top_stay_on_a_vertical_size(tmp_path, mode):
    sm, sec, _pln, _g = box(tmp_path)
    name = f"{sec}.TopSlab"
    got = sm.anchor(name, sec, mode)
    g = next(x for x in sm.growth(name))
    stays = g["from"] if mode == "start" else g["to"]  # start = the lower line (bottom), end = the upper (top)
    u = sm.unit(sec)
    assert u.an.datums[g["from"]].value < u.an.datums[g["to"]].value and got["mode"] == mode
    assert u.prog.datum_values({"TopSlab": 450.0})[stays] == pytest.approx(u.an.datums[stays].value)


def test_a_view_that_takes_a_shared_size_on_another_side_is_refused_with_both_views_named(tmp_path):
    sm, sec, pln, _g = box(tmp_path)
    sm._anchor_one("ClearSpan", pln, "end")  # one view alone (no projection): what the constraint exists to catch
    r = sm.regenerate({"ClearSpan": 3400.0})
    assert not r.ok and {f["check"] for f in r.failures} == {"PROJECTION"}
    f = r.failures[0]
    vs, vp = sm.units[sec].views[0], sm.units[pln].views[0]
    assert vs in f["message"] and vp in f["message"] and "ClearSpan" in f["values"]
    kinds = {e["kind"] for e in sm.explain(r, {"ClearSpan": 3400.0})}
    assert kinds == {"incomplete_model"}


def test_repeated_and_combined_changes_regenerate_the_same_and_come_back_exactly(tmp_path):
    sm, sec, pln, _g = box(tmp_path)
    drawn = sm.regenerate()
    combo = {"ClearSpan": 3300.0, "OuterWall": 350.0, f"{sec}.TopSlab": 420.0, f"{sec}.BottomSlab": 380.0}
    now = sm.current()
    orig = {k: now[k] for k in combo}
    a, b = sm.regenerate(combo), sm.regenerate(combo)
    assert a.ok and b.ok and a.reg.pts == b.reg.pts
    for _ in range(3):
        assert sm.apply(combo).ok
        assert sm.apply(orig).ok
    back = sm.regenerate()
    for uid in (sec, pln):
        got, want = pts_of(sm, back, uid), pts_of(sm, drawn, uid)
        assert got.keys() == want.keys()
        for k in got:
            assert got[k] == pytest.approx(want[k], abs=1e-6)


def test_the_project_keeps_its_local_systems_and_their_links(tmp_path):
    sm, _sec, _pln, _g = box(tmp_path)
    sm.apply({"ClearSpan": 3200.0})
    proj = tmp_path / "box.autoparam.json"
    sm.save(str(proj))
    assert json.loads(proj.read_text())["systems"] == "views"
    sm2 = SheetModel.load(str(proj))
    assert sm2.systems == "views" and set(sm2.units) == set(sm.units)
    assert {p.name: {b.unit for b in p.bindings} for p in sm2.shared.values()} == {p.name: {b.unit for b in p.bindings} for p in sm.shared.values()}
    assert sm2.regenerate().reg.pts == sm.regenerate().reg.pts


def side_by_side(path) -> str:
    """A box cross section and its longitudinal section side by side at one scale: the same four horizontal faces (bottom, soffit of the bottom
    slab, underside and top of the top slab) — drawn in projection on y."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()

    rect(msp, 0, 0, 84100, 59400, "BORDER")
    rect(msp, 1000, 1000, 83100, 58400, "BORDER")
    y0, h = 25000, 6000  # the faces both views show: y0, y0 + 600 (the bottom slab's top), y0 + h − 600, y0 + h

    def dim(p1, p2, base, angle=0):
        msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dxfattribs={"layer": "DIM"}).render()

    rect(msp, 8000, y0, 16000, y0 + h)
    rect(msp, 8600, y0 + 600, 15400, y0 + h - 600)
    msp.add_line((12000, y0 - 800), (12000, y0 + h + 800), dxfattribs={"layer": "CENTRE"})
    dim((8600, y0 + h / 2), (15400, y0 + h / 2), (0, y0 + h + 1200))
    dim((16000, y0), (16000, y0 + 600), (17200, 0), 90)
    text(msp, "CROSS SECTION A-A (SCALE 1:100)", 8500, y0 - 2400, 400)
    rect(msp, 30000, y0, 62000, y0 + h)
    rect(msp, 30000, y0 + 600, 62000, y0 + h - 600)
    for x in (38000, 46000, 54000):  # the barrel's joints: the longitudinal view's own vertical faces
        msp.add_line((x, y0), (x, y0 + h))
    dim((30000, y0 + h), (62000, y0 + h), (0, y0 + h + 1200))
    text(msp, "LONGITUDINAL SECTION (SCALE 1:100)", 38000, y0 - 2400, 400)
    doc.saveas(path)
    return str(path)


def test_a_level_on_a_face_both_views_show_is_one_level(tmp_path):
    sm = SheetModel.open(side_by_side(tmp_path / "s.dxf"))
    lk = next((lk for lk in sm.links if sm.is_linked(lk)), None)
    assert lk is not None and lk["axis"] == "y", sm.links
    ua, ub = sm.unit_of_view[lk["a"]], sm.unit_of_view[lk["b"]]
    an = sm.analysis(ua)
    bottom = min((d for d in an.datums.values() if d.axis == "y"), key=lambda d: d.value)
    ans = {"structure_type": "", "family": "other", "views": [], "summary": "", "components": [], "line_roles": [], "parameters": [], "datum_formulas": [],
           "relations": [], "behaviours": [], "constraints": [], "questions": [], "levels": [{"datum": bottom.id, "name": "BedLevel", "role": "site_input"}]}
    res = sm.commit_answer(ua, ans)
    assert [r for r in res.get("projection", []) if r.get("bound")], res.get("projection")
    p = next(p for p in sm.shared.values() if p.name == "BedLevel")
    assert p.unit == "m" and {b.unit for b in p.bindings} == {ua, ub}
    r = sm.regenerate({"BedLevel": p.value + 0.5})
    assert r.ok, r.errors
    assert set(r.by_view) == {lk["a"], lk["b"]}, "both views stand on the level: both rise"


def png(w: int = 64, h: int = 40) -> str:
    import base64
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def test_a_run_gets_the_sheet_s_brief_and_the_person_s_picture_and_the_plan_shares_what_the_section_names(tmp_path):
    """The harness on local systems, scripted (no model): the instruction goes to the model with the engine's brief of the sheet and the person's
    picture; the agent names the span in the section; the sheet binds it into the plan drawn in projection under it."""
    from test_run import wait

    from dxf_autoparam.ai.scripted import ScriptedModel, call
    from dxf_autoparam.workspace import SheetSession

    g = box_gad(tmp_path / "box.dxf", Box())
    sheet = SheetSession(g["path"])
    answers = box_answers(sheet.sm, g["box"], g["handles"])
    sec, pln = list(answers)
    span = next(p for p in answers[sec]["parameters"] if p["name"] == "ClearSpan")
    quote = "Name the clear span of the box."
    gem = ScriptedModel([[call("account_instruction", items=[{"quote": quote, "kind": "parametrize", "meaning": "the span is ClearSpan", "handled_by": "values"}])],
                         [call("open_unit", unit=sec)],
                         [call("define_parameters", items=[{"name": "ClearSpan", "candidate": span["candidate"], "occurrences": span["occurrences"]}])],
                         *[[call("finish", summary="the span is named ClearSpan")]] * 4])
    sheet.gem_factory = lambda: gem
    rid = sheet.start_run({"instruction": quote, "scope": {"kind": "drawing"}, "pictures": [{"name": "site.png", "data": png()}]})["run"]
    p = wait(sheet, rid)
    events = sheet.runs[rid].events
    brief = next(e["text"] for e in events if e["kind"] == "brief")
    assert "drawn in projection" in brief and "ONE shared value" in brief and "site.png" in brief
    assert next(e for e in events if e["kind"] == "run_start")["pictures"][0]["id"] == "P1"
    first = gem.requests[0]
    said = [getattr(x, "text", None) or "" for x in first["prefix"]]
    assert any("THE PERSON'S PICTURE P1 (site.png" in s for s in said), "the picture goes in the start every request repeats"
    assert sum(1 for x in first["prefix"] if getattr(x, "inline_data", None) is not None) >= 2, "the sheet's picture and the person's"
    assert "WHAT THE ENGINE KNOWS OF THIS SHEET" in first["history"][0].parts[0].text and quote in first["history"][0].parts[0].text
    shared = next((q for q in sheet.sm.shared.values() if q.name == "ClearSpan"), None)
    assert shared is not None and {b.unit for b in shared.bindings} == {sec, pln}, (p["status"], p.get("verdict", {}).get("remaining"))
    assert sheet.runs[rid].attachments[0].png[:8] == b"\x89PNG\r\n\x1a\n"


def test_a_picture_that_is_not_one_or_too_many_is_refused_with_the_reason():
    from dxf_autoparam.ai.attachments import MAX_COUNT, AttachmentError, read

    assert read([{"name": "a.png", "data": png(3000, 1000)}])[0].size == (2048, 683), "brought within the longest side the model gets"
    with pytest.raises(AttachmentError, match="PNG, JPEG or WebP|not a picture"):
        read([{"name": "notes.txt", "data": "data:text/plain;base64,aGVsbG8="}])
    with pytest.raises(AttachmentError, match="at most"):
        read([{"name": f"{k}.png", "data": png()} for k in range(MAX_COUNT + 1)])
    with pytest.raises(AttachmentError, match="base64"):
        read([{"name": "x.png", "data": "not base64 at all!"}])


def test_a_size_drawn_a_millimetre_apart_in_two_views_is_one_value_that_both_follow(tmp_path):
    """Drafting noise: the plan draws the box's span 1 mm off the section's. The projection binds it (views state one size within a
    millimetre); at the values as drawn each view measures its own drawn size (no view 'did not follow'); changed, both measure the new value."""
    g = box_gad(tmp_path / "box.dxf", Box(cells=1))
    doc = ezdxf.readfile(g["path"])
    hidden = sorted((e for e in doc.modelspace().query("LINE") if e.dxf.layer == "HIDDEN"), key=lambda e: e.dxf.start.x)
    right = hidden[-1]
    right.dxf.start = (right.dxf.start.x + 1.0, right.dxf.start.y)
    right.dxf.end = (right.dxf.end.x + 1.0, right.dxf.end.y)
    doc.saveas(g["path"])
    sm = SheetModel.open(g["path"])
    answers = box_answers(sm, g["box"], g["handles"])
    sec, pln = list(answers)
    for uid, ans in answers.items():
        sm.commit_answer(uid, ans)
    p = next(q for q in sm.shared.values() if q.name == "ClearSpan")
    assert {b.unit for b in p.bindings} == {sec, pln}
    assert sm.regenerate().ok and sm.regenerate(units={sec, pln}).ok, "as drawn, each view is its own drawn size"
    r = sm.regenerate({"ClearSpan": p.value + 400})
    assert r.ok, r.errors
    assert r.measured["ClearSpan"] == {sec: pytest.approx(p.value + 400), pln: pytest.approx(p.value + 400)}


def test_a_view_that_calls_another_size_by_the_shared_name_is_not_given_two_sizes_of_one_name(tmp_path):
    """Sharing a size under a view's own name renames it to the shared one — refused when that view already calls ANOTHER size by the shared
    name (it renamed first and the view held two sizes under one name: what the projection's binding met with the bench's placeholder names)."""
    from test_crossview import opening, two_views, view

    from dxf_autoparam.crossview import EMPTY_ANSWER, SheetError

    sm = SheetModel.open(str(two_views(tmp_path / "two.dxf")))
    ua, ub = sm.unit_of_view[view(sm, "SECTION A-A")], sm.unit_of_view[view(sm, "SIDE ELEVATION")]
    other = next(c.id for c in sm.unit(ub).an.clusters.values() if abs(c.value * sm.unit(ub).sub.units_mm - 3000) > 1 and "x" in c.axes)

    def named(uid, *pairs):
        u = sm.unit(uid)
        return {**copy.deepcopy(EMPTY_ANSWER), "parameters": [{"name": n, "label": n, "component": "", "kind": "length", "candidate": c,
                                                              "value": u.an.clusters[c].value * u.sub.units_mm} for n, c in pairs]}

    sm.set_answer(ua, named(ua, ("Opening", opening(sm, ua, 3000))))
    sm.set_answer(ub, named(ub, ("SideOpening", opening(sm, ub, 3000)), ("Opening", other)))
    with pytest.raises(SheetError, match="already names something else"):
        sm.share("Opening", [(ua, "Opening"), (ub, "SideOpening")])
    names = [q["name"] for q in sm.unit(ub).answer["parameters"]]
    assert sorted(names) == ["Opening", "SideOpening"] and "Opening" not in {q.name for q in sm.shared.values()}, "nothing changed"
