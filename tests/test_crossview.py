"""One parametric model for a whole sheet: views drawn in projection change together, a size two views both state
is one shared parameter, every change is checked on the regenerated sheet and committed only when it holds."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import ezdxf
import pytest
from test_sheet import FIXTURES, built_sheet, rect, text

from dxf_autoparam.crossview import EMPTY_ANSWER, SheetError, SheetModel


@pytest.fixture
def sheet(tmp_path):
    return SheetModel.open(str(built_sheet(tmp_path / "sheet.dxf")))


def view(sm: SheetModel, name: str) -> str:
    return next(g.id for g in sm.layout.views() if g.name == name)


def opening(sm: SheetModel, uid: str, value: float, kind: str | None = None) -> str:
    u = sm.unit(uid)
    return next(c.id for c in u.an.clusters.values() if abs(c.value * u.sub.units_mm - value) < 1 and "x" in c.axes
                and (kind is None or c.kind.value == kind))


def xs(sm: SheetModel, sr, vid: str) -> list[float]:
    """The x of every structural vertex a view shows after a regeneration."""
    out = set()
    for i in sm.layout.group(vid).items:
        it = sm.dr.items[i]
        if it.role.value == "structural":
            for k in it.vertex_pts:
                out.add(round(sr.reg.pts.get(i, it.pts)[k][0], 3))
    return sorted(out)


def test_views_drawn_in_projection_are_local_systems_that_change_together(sheet):
    """Each view its own unit; the projection binds the size named in the elevation into its plan (one shared value) and keeps the faces in line."""
    el, pl, de = view(sheet, "ELEVATION"), view(sheet, "PLAN"), view(sheet, "DETAIL OF WALL")
    assert sheet.systems == "views" and len({sheet.unit_of_view[el], sheet.unit_of_view[pl], sheet.unit_of_view[de]}) == 3
    link = next(lk for lk in sheet.links if {lk["a"], lk["b"]} == {el, pl})
    assert link["strong"] and link["axis"] == "x" and link["planes"] == 4 and sheet.is_linked(link)
    uid, up = sheet.unit_of_view[el], sheet.unit_of_view[pl]
    p = sheet.share("ClearSpan", [(uid, opening(sheet, uid, 12000, "void"))])
    assert {b.unit: b.status for b in p.bindings} == {uid: "drives", up: "drives"}, "bound into the plan across the projection"
    r = sheet.apply({"ClearSpan": 14000})
    assert r.ok, r.errors
    assert set(r.by_view) == {el, pl}  # the elevation and its plan: nothing else moved
    # the plan's lines are where the elevation's faces are: the projection still holds
    assert set(xs(sheet, r, pl)) <= set(xs(sheet, r, el))
    assert r.measured["ClearSpan"] == {uid: pytest.approx(14000), up: pytest.approx(14000)}
    assert sheet.undo() and "ClearSpan" in sheet.current() and sheet.undo() and "ClearSpan" not in sheet.current(), "one share, one undo — the plan's too"


def test_a_sheet_saved_with_joined_units_reads_them_joined(tmp_path):
    sheet = SheetModel.open(str(built_sheet(tmp_path / "sheet.dxf")), systems="joined")
    el, pl, de = view(sheet, "ELEVATION"), view(sheet, "PLAN"), view(sheet, "DETAIL OF WALL")
    assert sheet.unit_of_view[el] == sheet.unit_of_view[pl] != sheet.unit_of_view[de]
    uid = sheet.unit_of_view[el]
    sheet.share("ClearSpan", [(uid, opening(sheet, uid, 12000, "void"))])
    r = sheet.apply({"ClearSpan": 14000})
    assert r.ok and set(r.by_view) == {el, pl} and set(xs(sheet, r, pl)) <= set(xs(sheet, r, el))
    proj = tmp_path / "joined.autoparam.json"
    sheet.save(str(proj))
    assert SheetModel.load(str(proj)).systems == "joined"
    d = json.loads(proj.read_text())
    del d["systems"]  # saved before local systems: a unit named by two views says it was joined
    proj.write_text(json.dumps(d))
    assert SheetModel.load(str(proj)).systems == "joined"


def test_a_change_that_breaks_the_sheet_is_refused_and_nothing_changes(sheet):
    uid = sheet.unit_of_view[view(sheet, "ELEVATION")]
    sheet.share("ClearSpan", [(uid, opening(sheet, uid, 12000, "void"))])
    before, history = sheet.current(), len(sheet.history)
    r = sheet.apply({"ClearSpan": 0})  # an opening of nothing: its faces collapse onto each other
    assert not r.ok and r.errors
    assert sheet.current() == before and len(sheet.history) == history
    rng = sheet.valid_range("ClearSpan")
    assert 0 < rng["min"] < 12000 and rng["min_reason"] and rng["max"] > 12000


def test_rename_keeps_value_and_effect_and_undo_brings_the_old_name_back(sheet):
    uid = sheet.unit_of_view[view(sheet, "ELEVATION")]
    sheet.share("ClearSpan", [(uid, opening(sheet, uid, 12000, "void"))])
    sheet.apply({"ClearSpan": 13000})
    sheet.rename("ClearSpan", "MainOpening")
    cur = sheet.current()
    assert "ClearSpan" not in cur and cur["MainOpening"] == pytest.approx(13000)
    assert sheet.preview({"MainOpening": 15000}).ok
    with pytest.raises(SheetError):
        sheet.preview({"ClearSpan": 15000})
    with pytest.raises(SheetError):
        sheet.rename("MainOpening", "not a name")
    assert sheet.undo()
    assert "ClearSpan" in sheet.current() and "MainOpening" not in sheet.current()
    assert sheet.redo() and "MainOpening" in sheet.current()


def test_undo_and_redo_values(sheet):
    uid = sheet.unit_of_view[view(sheet, "ELEVATION")]
    sheet.share("ClearSpan", [(uid, opening(sheet, uid, 12000, "void"))])
    sheet.apply({"ClearSpan": 13000})
    sheet.apply({"ClearSpan": 13500})
    assert sheet.current()["ClearSpan"] == pytest.approx(13500)
    sheet.undo()
    assert sheet.current()["ClearSpan"] == pytest.approx(13000)
    sheet.redo()
    assert sheet.current()["ClearSpan"] == pytest.approx(13500)


def test_live_steps_of_one_value_are_one_undo(sheet):
    """A person stepping a value: every step is committed (the drawing follows) but a single undo goes back to where the stepping began."""
    uid = sheet.unit_of_view[view(sheet, "ELEVATION")]
    sheet.share("ClearSpan", [(uid, opening(sheet, uid, 12000, "void"))])
    depth, rev = len(sheet.history), sheet.revision
    for v in (12100, 12200, 12300):
        assert sheet.apply({"ClearSpan": v}, live=True).ok
        assert sheet.current()["ClearSpan"] == pytest.approx(v)
    assert len(sheet.history) == depth + 1 and sheet.revision == rev + 3  # one undo step; the revision still moves with every step
    assert sheet.undo()
    assert sheet.current()["ClearSpan"] == pytest.approx(12000)


def test_live_steps_do_not_join_other_changes(sheet):
    uid = sheet.unit_of_view[view(sheet, "ELEVATION")]
    sheet.share("ClearSpan", [(uid, opening(sheet, uid, 12000, "void"))])
    depth = len(sheet.history)
    sheet.apply({"ClearSpan": 12100}, live=True)
    sheet.apply({"ClearSpan": 12200}, live=False)  # an applied change is its own step
    sheet.apply({"ClearSpan": 12300}, live=True)  # and a live step after it starts again
    sheet.apply({"ClearSpan": 12400}, live=True)
    assert len(sheet.history) == depth + 3
    sheet.undo()
    assert sheet.current()["ClearSpan"] == pytest.approx(12200)
    sheet.redo()
    assert sheet.current()["ClearSpan"] == pytest.approx(12400)


def test_a_refused_live_step_changes_nothing_and_keeps_the_session(sheet):
    uid = sheet.unit_of_view[view(sheet, "ELEVATION")]
    sheet.share("ClearSpan", [(uid, opening(sheet, uid, 12000, "void"))])
    sheet.apply({"ClearSpan": 12100}, live=True)
    depth, rev = len(sheet.history), sheet.revision
    assert not sheet.apply({"ClearSpan": 0}, live=True).ok
    assert sheet.current()["ClearSpan"] == pytest.approx(12100) and len(sheet.history) == depth and sheet.revision == rev
    assert sheet.apply({"ClearSpan": 12200}, live=True).ok
    assert len(sheet.history) == depth  # still the same stepping


def two_views(path: Path) -> Path:
    """Two views NOT drawn in line (one beside and below the other), each stating 3000 for its opening."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    rect(msp, 0, 0, 60000, 40000, "BORDER")
    rect(msp, 2000, 25000, 10000, 32000)
    rect(msp, 4000, 26000, 7000, 31000)
    msp.add_linear_dim(base=(0, 33500), p1=(4000, 32000), p2=(7000, 32000), dxfattribs={"layer": "DIM"}).render()
    text(msp, "SECTION A-A", 3000, 23500, 400)
    rect(msp, 30000, 5000, 44000, 12000)
    rect(msp, 33000, 6000, 36000, 11000)
    msp.add_linear_dim(base=(0, 13500), p1=(33000, 12000), p2=(36000, 12000), dxfattribs={"layer": "DIM"}).render()
    text(msp, "SIDE ELEVATION", 32000, 3500, 400)
    doc.saveas(path)
    return path


def test_a_size_two_separate_views_state_is_proposed_shared_and_drives_both(tmp_path):
    sm = SheetModel.open(str(two_views(tmp_path / "two.dxf")))
    a, b = view(sm, "SECTION A-A"), view(sm, "SIDE ELEVATION")
    ua, ub = sm.unit_of_view[a], sm.unit_of_view[b]
    assert ua != ub and not any(lk["strong"] for lk in sm.links)
    prop = next(p for p in sm.shared_proposals() if p["value"] == 3000)
    assert {prop["a"][0], prop["b"][0]} == {ua, ub} and len(prop["evidence"]) == 2
    p = sm.share("Opening", [tuple(prop["a"]), tuple(prop["b"])], evidence=prop["evidence"])
    assert [b.status for b in p.bindings] == ["drives", "drives"]
    r = sm.apply({"Opening": 3600})
    assert r.ok, r.errors
    assert set(r.by_view) == {a, b}
    assert r.measured["Opening"] == {ua: pytest.approx(3600), ub: pytest.approx(3600)}
    imp = sm.impact("Opening")
    assert set(imp["views"]) == {a, b}
    # a size the views do not both state is refused as a whole
    with pytest.raises(SheetError):
        sm.share("Wrong", [(ua, opening(sm, ua, 3000)), (ub, opening(sm, ub, 14000))])
    assert "Wrong" not in sm.current()


def test_save_and_load_the_project(tmp_path, sheet):
    uid = sheet.unit_of_view[view(sheet, "ELEVATION")]
    sheet.share("ClearSpan", [(uid, opening(sheet, uid, 12000, "void"))])
    sheet.apply({"ClearSpan": 13000})
    proj = tmp_path / "sheet.autoparam.json"
    sheet.save(str(proj))
    sm2 = SheetModel.load(str(proj))
    assert sm2.current()["ClearSpan"] == pytest.approx(13000)
    r1, r2 = sheet.regenerate(), sm2.regenerate()
    assert r1.reg.pts == r2.reg.pts


def test_export_writes_every_regenerated_view_into_the_original(tmp_path, sheet):
    uid = sheet.unit_of_view[view(sheet, "ELEVATION")]
    sheet.share("ClearSpan", [(uid, opening(sheet, uid, 12000, "void"))])
    sheet.apply({"ClearSpan": 14000})
    out = tmp_path / "out.dxf"
    rep = sheet.export(str(out))
    assert rep["audit"]["errors"] == 0 and rep["updated"] > 0 and not rep["errors"]
    doc = ezdxf.readfile(str(out))
    widths = sorted(round(d.get_measurement()) for d in doc.modelspace().query("DIMENSION") if abs(d.get_measurement() - 14000) < 1)
    assert widths == [14000]  # the opening's dimension now reads the new size


@pytest.mark.skipif(not (FIXTURES / "gad_ezdxf_a.dxf").exists(), reason="aagento-bridge fixtures not present")
def test_a_real_sheet_section_and_plan_follow_one_barrel_length(tmp_path):
    sm = SheetModel.open(str(FIXTURES / "gad_ezdxf_a.dxf"))
    sec, plan = view(sm, "LONGITUDINAL SECTION(X-X)"), view(sm, "PLAN TOP")
    uid = sm.unit_of_view[sec]
    assert sm.unit_of_view[plan] != uid  # drawn in projection: two local systems, linked
    cid = opening(sm, uid, 11740)
    p = sm.share("BarrelLength", [(uid, cid)], evidence=["written in both views"])
    assert [b.status for b in p.bindings] == ["drives", "drives"] and {b.unit for b in p.bindings} == {uid, sm.unit_of_view[plan]}
    # which end the barrel grows at is the person's decision: the upstream end stays, the downstream end moves — in the plan as well
    got = sm.anchor("BarrelLength", uid, "start")
    assert got["mode"] == "start" and [x["mode"] for x in got["projection"]] == ["start"]
    for v in (10000, 13000):
        r = sm.preview({"BarrelLength": v})
        assert r.ok, r.errors[:3]
        assert r.by_view.get(sec, 0) > 50 and r.by_view.get(plan, 0) > 50
        assert set(r.by_view) == {sec, plan}  # the other views stay as drawn
    sm.apply({"BarrelLength": 13000})
    rep = sm.export(str(tmp_path / "a.dxf"))
    assert rep["audit"]["errors"] == 0
    # the notes that state the barrel length in the section and in the plan now state the new one; the other
    # view's own note (another barrel) is left as it was
    doc = ezdxf.readfile(str(tmp_path / "a.dxf"))
    notes = sorted(e.text for e in doc.modelspace().query("MTEXT") if "BARREL LENGTH" in e.text)
    assert notes == ["BARREL LENGTH = 13000", "BARREL LENGTH = 13000 mm"], notes  # the two reshaped views, written out
    kept = [e.text for b in doc.blocks for e in b.query("MTEXT") if "BARREL LENGTH" in e.text]
    assert "BARREL LENGTH = 15950" in kept  # the untouched view keeps its block, and its own note


def test_how_a_value_grows_is_measured_and_can_be_chosen(sheet):
    uid = sheet.unit_of_view[view(sheet, "ELEVATION")]
    sheet.share("ClearSpan", [(uid, opening(sheet, uid, 12000, "void"))])
    g = sheet.growth("ClearSpan")[0]
    assert g["mode"] in ("end", "start", "centre") and g["why"]
    for mode in ("start", "end"):
        got = sheet.anchor("ClearSpan", uid, mode)
        assert got["mode"] == mode
        fixed = g["from"] if mode == "start" else g["to"]  # the mode names the line that stays
        r = sheet.preview({"ClearSpan": 13000})
        assert r.ok
        u = sheet.unit(uid)
        assert abs(sheet.unit(uid).prog.datum_values({"ClearSpan": 13000})[fixed] - u.an.datums[fixed].value) < 1e-9
    assert sheet.undo()  # the choice is undone like any other edit


def mini_gad(path) -> str:
    """A very small GAD: a one-cell box in section, its plan drawn in line below it (the same four wall faces), and a
    separate wall detail that states the wall again. The wall dimensions are taken along the slab beneath the walls,
    so the inner face's dimension point lies on that face's line but on no drawn vertex."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.dimstyles.new("GAD50", dxfattribs={"dimtxt": 2.5, "dimscale": 50, "dimgap": 0.6, "dimtad": 1})
    msp = doc.modelspace()

    def box(x0, y0, x1, y1):
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True)

    def dim(p1, p2, base, angle=0):
        msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle="GAD50", dxfattribs={"layer": "DIM"}).render()

    def title(s, x, y):
        msp.add_text(s, height=175, dxfattribs={"layer": "TEXT", "insert": (x, y), "halign": 1, "align_point": (x, y)})

    box(0, 0, 3000, 2600)
    box(300, 300, 2700, 2300)
    dim((300, 1300), (2700, 1300), (0, 1300))
    dim((0, 0), (300, 0), (0, -350))
    dim((2700, 0), (3000, 0), (0, -350))
    dim((3000, 0), (3000, 2600), (3500, 0), 90)
    title("CROSS SECTION A-A", 1500, -900)
    box(0, -6400, 3000, -2400)
    for x in (300, 2700):
        msp.add_line((x, -6400), (x, -2400), dxfattribs={"layer": "HIDDEN"})
    dim((0, -6400), (0, -2400), (-500, 0), 90)
    dim((0, -6400), (3000, -6400), (0, -6800))
    title("PLAN", 1500, -7400)
    box(7000, -3000, 7300, -800)
    msp.add_line((6700, -3000), (7600, -3000))
    dim((7000, -800), (7300, -800), (0, -500))
    title("DETAIL OF SIDE WALL", 7150, -3600)
    doc.saveas(path)
    return str(path)


def dim_labels(sm, sr) -> list[str]:
    from dxf_autoparam.display import primitives

    return [next(p["text"] for p in primitives(it, sr.reg.pts.get(it.index, it.pts), None, None, sm.dr.units_mm) if p["k"] == "t")
            for it in sm.dr.items if it.dxftype == "DIMENSION"]


def test_a_size_a_unit_already_named_is_linked_across_views_as_is(tmp_path):
    """Parametrized first, linked after (the Gemini stages in order): the shared name is the very size the unit already
    calls by that name — it is bound, not refused as a namesake; a namesake of another size is still refused. (The section and its plan
    analysed as one unit, as a sheet saved with joined units: the candidate ids are that unit's.)"""
    sm = SheetModel.open(mini_gad(tmp_path / "mini.dxf"), systems="joined")
    uid = next(k for k, u in sm.units.items() if len(u.views) == 2)
    other = next(k for k in sm.units if k != uid)
    answer = {**copy.deepcopy(EMPTY_ANSWER), "parameters": [
        {"name": "OuterWall", "label": "Outer wall", "component": "", "kind": "length", "candidate": "c0", "value": 300.0},
        {"name": "ClearSpan", "label": "Clear span", "component": "", "kind": "length", "candidate": "c3", "value": 2400.0}]}
    sm.set_answer(uid, answer)
    assert sm.unit(uid).prog.params["OuterWall"].value == pytest.approx(300)
    with pytest.raises(SheetError, match="already names something else"):
        sm.share("ClearSpan", [(uid, "c0"), (other, "c0")])   # the wall is not the clear span
    p = sm.share("OuterWall", [(uid, "c0"), (other, "c0")])
    assert [b.status for b in p.bindings] == ["drives", "drives"]
    sr = sm.preview({"OuterWall": 400.0})
    assert sr.ok and set(sr.by_view) >= {"V01", "V02", "V03"}


def test_a_dimension_point_off_any_vertex_follows_the_line_it_lies_on(tmp_path):
    """The wall dimension is taken along the slab: its inner point (300, 0) lies on the inner face's line but on no
    drawn vertex. It follows that face, so the dimension reads the new wall, not 300 carried along with the corner."""
    sm = SheetModel.open(mini_gad(tmp_path / "mini.dxf"))
    uid = sm.unit_of_view[view(sm, "CROSS SECTION A-A")]
    wall = next(n for n, p in sm.unit(uid).prog.params.items() if round(p.value) == 300 and p.measures and sm.unit(uid).an.datums[p.measures[0]].axis == "x")
    sr = sm.preview({f"{uid}.{wall}": 400.0})
    assert sr.ok, sr.errors
    assert dim_labels(sm, sr).count("400") >= 2   # both wall dimensions under the section
