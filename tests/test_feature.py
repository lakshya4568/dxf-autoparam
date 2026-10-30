"""Feature operations: a change of COUNT of a repeated unit, made as a new revision of the drawing (feature.py).

The yardstick is the generator's own drawing (`plan_bench.Box`): the box drawn at the new count is the truth, so the derived drawing is compared with
it entity by entity — outlines, hatches' places, dimensions (what they measure and say), notes. What is measured here: the repeated unit is found from
the analysis alone, adding / removing an instance gives exactly the drawing drawn at the new count, every name of the parametrization survives and the new
instance follows it, the production guards judge the new count (a view that does not follow is refused), undo / redo / save carry the revision, and
every refusal — with the reason — leaves the sheet and the disk exactly as they were.

The tests that run the production rule code need Node and the bundle (`dxf-autoparam production build`); without them they are skipped."""

from __future__ import annotations

import ast
import copy
import json
import re
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

import ezdxf
import pytest

from dxf_autoparam import feature
from dxf_autoparam.ai.production import ProductionSession
from dxf_autoparam.ai.run import ACTIVE
from dxf_autoparam.ai.scripted import ScriptedModel, call
from dxf_autoparam.crossview import SheetError, SheetModel
from dxf_autoparam.dxf_read import read_dxf
from dxf_autoparam.plan_bench import Box, box_answer, box_gad
from dxf_autoparam.production import manifest as M
from dxf_autoparam.production.bench import PLAN_DECISIONS, PLAN_INSTRUCTION, _sheet, truth_binding
from dxf_autoparam.production.bridge import default_bridge
from dxf_autoparam.workspace import SheetSession

# these tests measure the engine within ONE unit made of a section and its plan (conftest.joined_units): local systems, each view its own,
# are test_local_systems.py
pytestmark = pytest.mark.usefixtures("joined_units")

STATUS = default_bridge().status()
needs_bridge = pytest.mark.skipif(not STATUS["available"], reason=f"the production rule bridge cannot run here: {STATUS.get('reason')}")


def box(cells: int, **kw) -> Box:
    return replace(Box(cells=cells), detail=False, **kw)


def signature(dr) -> Counter:
    """A drawing as the set of what it shows, whatever its handles and order: kind, layer, points; for a dimension what it measures and says; for a note its words."""
    out: Counter = Counter()
    for it in dr.items:
        if it.anchor is not None:
            continue
        if it.dxftype == "DIMENSION":
            key = (it.dxftype, it.layer, round(it.extra["measurement"], 3), tuple((round(p[0], 3), round(p[1], 3)) for p in it.pts[1:3]), it.text)
        else:
            key = (it.dxftype, it.layer, tuple((round(p[0], 3), round(p[1], 3)) for p in it.pts), it.text if it.dxftype in ("TEXT", "MTEXT") else "")
        out[key] += 1
    return out


def generated(tmp_path: Path, b: Box) -> Counter:
    g = box_gad(tmp_path / f"truth{b.cells}.dxf", b)
    return signature(read_dxf(g["path"])[0])


def state_of(sm: SheetModel) -> dict:
    s = sm._state()
    return {"values": s["values"], "answers": s["answers"], "domain": s["domain"], "plan": s["plan"], "lineage": s["lineage"], "revision": sm.revision,
            "history": len(sm.history), "path": sm.path, "items": len(sm.dr.items)}


def files(path: Path) -> list[str]:
    return sorted(str(p.relative_to(path)) for p in path.rglob("*") if p.is_file()) if path.exists() else []


def sheet_with(tmp_path: Path, b: Box, edit=None, name: str = "s"):
    """The generated sheet, optionally with its DXF edited first (a note, a vertex, a hatch …), parametrized as the benchmark does."""
    g = box_gad(tmp_path / f"{name}.dxf", b)
    if edit is not None:
        doc = ezdxf.readfile(g["path"])
        edit(doc, doc.modelspace(), b)
        doc.saveas(g["path"])
    sm = SheetModel.open(g["path"])
    two = next(k for k, u in sm.units.items() if len(u.views) == 2)
    va, vb = sm.units[two].views
    sec = max((va, vb), key=lambda v: sm.layout.group(v).bbox[3])
    us = sm.unit_of_view[sec]
    sm.commit_answer(us, box_answer(sm, us, g["box"], g["handles"]))
    return sm, us


# ── what is found, with no structure named ───────────────────────────────────────


@pytest.mark.parametrize("cells", [2, 3, 4])
def test_the_repeated_unit_is_found_from_the_analysis_alone(tmp_path, cells):
    b = box(cells)
    sm, us, _up, _g = _sheet(b, tmp_path, "s")
    reps = feature.detect_repeats(sm.unit(us).an)
    lattice = [r for r in reps if r.axis == "x" and abs(r.pitch - (b.span + b.mid)) < 1.0]
    assert lattice and all(r.count == cells for r in lattice if r.width == b.span), "the cells (and the same bays in the plan) stand on one lattice at the pitch"
    chosen = max(feature._lattices(reps, 1.0)[0], key=lambda r: r.area)
    assert chosen.count == cells and chosen.pitch == pytest.approx(b.span + b.mid) and chosen.width == pytest.approx(b.span)


def test_the_engine_names_no_kind_of_structure():
    """No branch, name or message of the generic engine is about a kind of structure: what a thing is called comes from the knowledge, never from here."""
    words = ("cell", "wall", "slab", "box", "pier", "girder", "culvert", "bridge", "haunch", "footing", "wing", "ballast", "rail")
    for mod in ("feature.py", "feature_carry.py"):
        tree = ast.parse((Path(feature.__file__).parent / mod).read_text())
        docstrings = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                      and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(tree):
            text = n.id if isinstance(n, ast.Name) else n.attr if isinstance(n, ast.Attribute) else n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) \
                and id(n) not in docstrings else ""
            tokens = set(re.findall(r"[a-z]+", text.lower()))
            assert not tokens & {w + e for w in words for e in ("", "s")}, f"{mod}: {text!r} names a kind of structure"


# ── the derived drawing is the generator's own at the new count ──────────────────


@pytest.mark.parametrize(("n0", "n1"), [(2, 3), (3, 2), (2, 4), (4, 2), (3, 4), (4, 3), (2, 1)])
def test_changing_the_count_gives_the_drawing_the_generator_draws_at_the_new_count(tmp_path, n0, n1):
    sm, us, _up, _g = _sheet(box(n0), tmp_path, "s")
    res = sm.apply_feature(us, {"count": n1, "nouns": ["cell"]}, out_dir=str(tmp_path / "rev"))
    assert res["plan"]["status"] == "ready" and res["plan"]["from_count"] == n0 and res["plan"]["to_count"] == n1
    want, got = generated(tmp_path, box(n1)), signature(sm.dr)
    assert not (want - got) and not (got - want), f"missing {list((want - got).items())[:2]} extra {list((got - want).items())[:2]}"
    assert Path(res["path"]).parent.parent == tmp_path / "rev" and sm.dr.path == res["path"]
    assert len(files(tmp_path / "rev")) == 1, "one file: the derived drawing"


def test_a_note_that_states_the_count_is_said_when_nothing_says_what_is_counted(tmp_path):
    sm, us, _up, _g = _sheet(box(2), tmp_path, "s")
    plan = sm.plan_feature(us, {"count": 3})
    assert plan["status"] == "ready" and any("2 CELL RCC BOX" in w and "left as drawn" in w for w in plan["warnings"])
    res = sm.apply_feature(us, {"count": 3}, out_dir=str(tmp_path / "rev"))
    assert any(t.startswith("2 CELL") for t in (it.text for it in sm.dr.items if it.dxftype == "TEXT")), "never rewritten on a guess"
    assert res["plan"]["notes_rewritten"] == []


def test_an_instance_can_be_added_at_the_start_or_in_the_middle_and_the_drawing_is_the_same(tmp_path):
    want = generated(tmp_path, box(3))
    for k, at in enumerate(("start", 1, "end")):
        (tmp_path / str(k)).mkdir()
        sm, us, _up, _g = _sheet(box(2), tmp_path / str(k), "s")
        sm.apply_feature(us, {"count": 3, "at": at, "nouns": ["cell"]}, out_dir=str(tmp_path / str(k) / "rev"))
        got = signature(sm.dr)
        assert not (want - got) and not (got - want), at


def test_notes_and_dimensions_every_instance_carries_are_repeated_and_removed_with_it(tmp_path):
    def label_each_cell(_doc, msp, b):
        for k in range(b.cells):
            x = b.wall + k * (b.span + b.mid) + b.span / 2
            msp.add_text("CLEAR", height=120, dxfattribs={"layer": "TEXT", "insert": (x, 1500)})

    def truth(n):
        g = box_gad(tmp_path / f"t{n}.dxf", box(n))
        doc = ezdxf.readfile(g["path"])
        label_each_cell(doc, doc.modelspace(), box(n))
        doc.saveas(g["path"])
        return signature(read_dxf(g["path"])[0])

    sm, us = sheet_with(tmp_path, box(2), label_each_cell)
    sm.apply_feature(us, {"count": 3, "nouns": ["cell"]}, out_dir=str(tmp_path / "rev"))
    assert signature(sm.dr) == truth(3), "the label of each instance, and the dimension of each, appear once more"
    sm.apply_feature(us, {"count": 2, "nouns": ["cell"]}, out_dir=str(tmp_path / "rev"))
    assert signature(sm.dr) == truth(2)


def test_the_symmetric_centre_stays_the_centre(tmp_path):
    sm, us, _up, _g = _sheet(box(3), tmp_path, "s")
    sm.apply_feature(us, {"count": 4}, out_dir=str(tmp_path / "rev"))
    w = box(4).width
    centre = [it for it in sm.dr.items if it.layer == "CENTRE"]
    assert len(centre) == 1 and centre[0].pts[0][0] == pytest.approx(w / 2), "the centre line is the middle of the structure, not an instance's"


# ── the parametrization, by name ─────────────────────────────────────────────────


def test_the_new_revision_keeps_every_name_and_the_new_instance_follows_them(tmp_path):
    sm, us, _up, _g = _sheet(box(2), tmp_path, "s")
    old = sm.unit(us)
    names = {p["name"] for p in old.answer["parameters"]} | {lv["name"] for lv in old.answer["levels"]}
    parts = {c["name"] for c in old.answer["components"]}
    sm.apply_feature(us, {"count": 3}, out_dir=str(tmp_path / "rev"))
    new = sm.unit(us)
    assert names <= set(new.prog.params), "every value somebody named is still a value"
    got = {c["name"] for c in new.answer["components"]}
    copies = got - parts
    assert parts <= got and len(copies) == 6 and all(c.endswith("Copy1") for c in copies), copies
    span = next(p for p in new.answer["parameters"] if p["name"] == "ClearSpan")
    assert len(new.an.clusters[span["candidate"]].gaps) == 3 and span["value"] == pytest.approx(3000.0), "one value, now three cells' worth"
    r = sm.apply({f"{us}.ClearSpan": 2600.0})
    assert r.ok, r.errors
    assert sum(1 for i in r.changed if sm.dr.items[i].dxftype == "LWPOLYLINE") >= 10, "the added instance moves with it"


def test_values_changed_before_the_change_of_count_become_the_drawing_and_one_undo_restores_everything(tmp_path):
    sm, us, _up, _g = _sheet(box(2), tmp_path, "s")
    assert sm.apply({f"{us}.TopSlab": 400.0}).ok
    before = state_of(sm)
    res = sm.apply_feature(us, {"count": 3, "nouns": ["cell"]}, out_dir=str(tmp_path / "rev"))
    assert any("values changed since the import" in w for w in res["plan"]["warnings"]) and sm.values == {}
    want, got = generated(tmp_path, box(3, top=400.0)), signature(sm.dr)
    assert {k for k in (want - got)} | {k for k in (got - want)} <= {k for k in (want - got) | (got - want) if k[1] == "CENTRE"}, \
        "only the centre line's end differs: the regeneration never moved it with the slab, with or without a change of count"
    assert len(files(tmp_path / "rev")) == 1, "the intermediate drawing is not left behind"
    assert sm.undo()
    assert sm.values == {us: {"TopSlab": 400.0}} and len(sm.dr.items) == before["items"] and sm.path == before["path"]


def test_undo_redo_and_the_project_file_carry_the_revision(tmp_path):
    sm, us, _up, g = _sheet(box(2), tmp_path, "s")
    first = sm.path
    sm.apply_feature(us, {"count": 3}, out_dir=str(tmp_path / "rev"))
    second, n_items = sm.path, len(sm.dr.items)
    assert second != first and sm.lineage[0]["from"] == first and sm.lineage[0]["to_count"] == 3
    proj = tmp_path / "p.autoparam.json"
    sm.save(str(proj))
    assert json.loads(proj.read_text())["dxf"] == second
    loaded = SheetModel.load(str(proj))
    assert loaded.path == second and len(loaded.dr.items) == n_items and loaded.lineage == sm.lineage
    assert {c["name"] for c in loaded.unit(us).answer["components"]} == {c["name"] for c in sm.unit(us).answer["components"]}
    assert sm.undo() and sm.path == g["path"] and len(sm.dr.items) == len(read_dxf(g["path"])[0].items) and sm.lineage == []
    (tmp_path / "fresh").mkdir()
    fresh = _sheet(box(2), tmp_path / "fresh", "s")[0]
    assert {c["name"] for c in sm.unit(us).answer["components"]} == {c["name"] for c in fresh.unit(us).answer["components"]}
    assert sm.redo() and sm.path == second and len(sm.dr.items) == n_items and sm.lineage == loaded.lineage


# ── refusals: the reason, and nothing changed ────────────────────────────────────


def refuse(sm: SheetModel, us: str, tmp_path: Path, request: dict, match: str) -> dict:
    before = state_of(sm)
    plan = sm.plan_feature(us, request)
    assert plan["status"] in ("refused", "needs_decision") and re_search(match, " | ".join(plan["refusals"] + [q["text"] for q in plan["questions"]])), plan
    with pytest.raises(SheetError, match="nothing changed"):
        sm.apply_feature(us, request, out_dir=str(tmp_path / "rev"))
    assert state_of(sm) == before and files(tmp_path / "rev") == [] and not (tmp_path / "rev").exists(), "the sheet and the disk are as they were"
    return plan


def re_search(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE | re.DOTALL) is not None


def test_a_single_instance_shows_no_pitch_and_the_count_must_be_the_one_drawn(tmp_path):
    sm, us, _up, _g = _sheet(box(1), tmp_path, "s")
    plan = refuse(sm, us, tmp_path, {"count": 2, "current": 1}, "no repeated unit stands out")
    assert plan["status"] == "needs_decision" and plan["questions"][0]["options"], "the candidates are offered, by id: nothing is guessed"
    (tmp_path / "b").mkdir()
    sm2, us2, _up2, _g2 = _sheet(box(3), tmp_path / "b", "s")
    refuse(sm2, us2, tmp_path, {"count": 3}, "already shows 3")
    refuse(sm2, us2, tmp_path, {"count": 5, "current": 2}, r"shows 3 instance\(s\), not 2 as stated")
    refuse(sm2, us2, tmp_path, {"count": 0}, "at least 1")
    refuse(sm2, us2, tmp_path, {"count": 4, "at": -1}, "'end', 'start'")


def test_another_view_the_grown_one_would_run_into_is_never_moved(tmp_path):
    sm, us, _up, _g = _sheet(replace(Box(cells=2), detail=True, detail_x=9500), tmp_path, "s")
    plan = refuse(sm, us, tmp_path, {"count": 3}, r"grow by 3300 mm into L01")
    assert "make room first" in plan["refusals"][0]
    assert sm.plan_feature(us, {"count": 1})["status"] == "ready", "a removal never grows into anything"
    (tmp_path / "far").mkdir()
    sm2, us2, _up2, _g2 = _sheet(replace(Box(cells=2), detail=True, detail_x=12000), tmp_path / "far", "s")
    sm2.apply_feature(us2, {"count": 3, "nouns": ["cell"]}, out_dir=str(tmp_path / "far" / "rev"))
    want, got = generated(tmp_path, replace(Box(cells=3), detail=True, detail_x=12000)), signature(sm2.dr)
    assert not (want - got) and not (got - want), "a view with room to spare is left exactly where it is"


def test_what_stands_apart_beyond_the_unit_is_for_the_person_to_say_it_moves_or_stays(tmp_path):
    b = replace(Box(cells=2), detail=True)  # the pitching detail sits at the right, in the structure's own view, touching nothing
    sm, us, _up, _g = _sheet(b, tmp_path, "s")
    plan = refuse(sm, us, tmp_path, {"count": 3}, "touch nothing of the structure")
    assert plan["status"] == "needs_decision" and plan["questions"][0]["options"] == ["move", "keep"] and plan["questions"][0]["about"] == "detached"
    refuse(sm, us, tmp_path, {"count": 3, "detached": "keep"}, r"stays where it is but the structure would grow over it")
    refuse(sm, us, tmp_path, {"count": 3, "detached": "sideways"}, "'move'")
    sm.apply_feature(us, {"count": 3, "detached": "move", "nouns": ["cell"]}, out_dir=str(tmp_path / "rev"))
    want, got = generated(tmp_path, replace(Box(cells=3), detail=True, detail_x=b.width + 1400 + 3300)), signature(sm.dr)
    assert not (want - got) and not (got - want), "it kept its distance from the structure"
    (tmp_path / "keep").mkdir()
    sm2, us2, _up2, _g2 = _sheet(b, tmp_path / "keep", "s")
    plan = refuse(sm2, us2, tmp_path / "keep", {"count": 1, "detached": "keep"}, r"reads as other views than the original")
    assert "label L01" in plan["refusals"][0], "kept far from the shrunk structure the detail would read as a view of its own: the drawing's views would change"


def test_an_outline_with_detail_inside_the_repeated_unit_is_not_stretched(tmp_path):
    def a_notch_in_the_top_slab(_doc, msp, b):
        top = [e for e in msp if e.dxftype() == "LWPOLYLINE"][1]
        pts = list(top.get_points("xy"))
        mid = b.wall + (b.cells - 1) * (b.span + b.mid) + b.span / 2  # the last cell: the unit that is repeated
        top.set_points([pts[0], (mid, pts[0][1]), (mid, pts[0][1] + 40), (mid + 10, pts[0][1] + 40), (mid + 10, pts[0][1]), pts[1], pts[2], pts[3]])

    sm, us = sheet_with(tmp_path, box(2), a_notch_in_the_top_slab)
    refuse(sm, us, tmp_path, {"count": 3}, r"vertices inside the repeated unit")


def test_a_sloped_edge_across_the_repeated_unit_is_not_stretched(tmp_path):
    def slope(_doc, msp, b):
        found = next(e for e in msp if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "FOUNDATION")
        pts = list(found.get_points("xy"))
        pts[1] = (pts[1][0], pts[1][1] - 100)  # the foundation's bottom edge runs downhill
        found.set_points(pts)

    sm, us = sheet_with(tmp_path, box(2), slope)
    refuse(sm, us, tmp_path, {"count": 3}, "not parallel to the axis")


def test_a_note_that_only_one_instance_carries_is_neither_copied_nor_removed(tmp_path):
    def one_note(_doc, msp, b):
        msp.add_text("ONLY HERE", height=120, dxfattribs={"layer": "TEXT", "insert": (b.wall + b.span * 0.3, 1500)})  # in the first instance only

    sm, us = sheet_with(tmp_path, box(3), one_note)
    refuse(sm, us, tmp_path, {"count": 4, "at": "start"}, r"TEXT .* no other instance has one like it")
    refuse(sm, us, tmp_path, {"count": 2, "at": "start"}, r"no other instance has one like it")
    assert sm.plan_feature(us, {"count": 4})["status"] == "ready", "an instance elsewhere is repeated without it: the note stays where it was"


def test_a_dimension_that_measures_part_of_the_repeated_unit_is_refused(tmp_path):
    def half_a_cell(_doc, msp, b):
        msp.add_linear_dim(base=(0, 4200), p1=(0, 2000), p2=(b.wall + (b.cells - 1) * (b.span + b.mid) + b.span / 2, 2000), dimstyle="GAD50", dxfattribs={"layer": "DIM"}).render()

    sm, us = sheet_with(tmp_path, box(2), half_a_cell)
    refuse(sm, us, tmp_path, {"count": 3}, r"DIMENSION .* lies across the edge of the repeated unit")


def test_a_hatch_with_a_curved_boundary_is_not_stretched_and_a_straight_one_in_a_region_is_copied(tmp_path):
    def curved(_doc, msp, b):
        h = msp.add_hatch(color=2, dxfattribs={"layer": "STRUCTURE"})
        e = h.paths.add_edge_path()
        e.add_line((0, -900), (b.width, -900))
        e.add_line((b.width, -900), (b.width, -500))
        e.add_arc((b.width / 2, -500), 400, 0, 180, ccw=True)
        e.add_line((0, -500), (0, -900))

    sm, us = sheet_with(tmp_path, box(2), curved)
    refuse(sm, us, tmp_path, {"count": 3}, r"HATCH .* curved boundary")


def test_a_view_stored_as_a_block_that_would_be_reshaped_is_refused(tmp_path):
    def into_a_block(doc, msp, b):
        blk = doc.blocks.new("VIEWBLOCK")
        for e in list(msp):
            if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "STRUCTURE":
                blk.add_lwpolyline(list(e.get_points("xy")), close=True, dxfattribs={"layer": "STRUCTURE"})
                msp.delete_entity(e)
        msp.add_blockref("VIEWBLOCK", (0, 0))

    g = box_gad(tmp_path / "blk.dxf", box(2))
    doc = ezdxf.readfile(g["path"])
    into_a_block(doc, doc.modelspace(), box(2))
    doc.saveas(g["path"])
    sm = SheetModel.open(g["path"])
    uid = max(sm.units, key=lambda k: len(sm.units[k].items))
    plan = sm.plan_feature(uid, {"count": 3})
    assert plan["status"] == "refused" and re_search(r"block reference .* explode the block first|no repeated unit", " ".join(plan["refusals"])), plan["refusals"]


def test_a_stale_plan_is_refused_whole(tmp_path):
    sm, us, _up, _g = _sheet(box(2), tmp_path, "s")
    rev = sm.revision
    assert sm.apply({f"{us}.TopSlab": 350.0}).ok
    with pytest.raises(SheetError, match="stale"):
        sm.apply_feature(us, {"count": 3}, expected_revision=rev, out_dir=str(tmp_path / "rev"))
    plan = sm.plan_feature(us, {"count": 3})
    with pytest.raises(SheetError, match="is not the plan this sheet would make now"):
        sm.apply_feature(us, {"count": 3}, plan_id="F_other", out_dir=str(tmp_path / "rev"))
    assert plan["status"] == "ready" and not (tmp_path / "rev").exists()


def test_accepted_plans_cannot_be_carried_to_another_count_and_the_person_decides(tmp_path):
    sm, us, _up, _g = _sheet(box(2), tmp_path, "s")
    sm.apply_plan(us, {"instruction": PLAN_INSTRUCTION.format(v="2500"), "decisions": PLAN_DECISIONS})
    plan = refuse(sm, us, tmp_path, {"count": 3}, "accepted plan")
    assert plan["status"] == "needs_decision" and plan["questions"][0]["options"] == ["drop_plans", "leave the count"]


# ── the production guards judge the new count ────────────────────────────────────


@needs_bridge
@pytest.mark.parametrize(("n0", "n1"), [(2, 3), (3, 2)])
def test_the_production_model_holds_at_the_new_count_and_its_stated_count_follows(tmp_path, n0, n1):
    b = box(n0)
    sm, us, _up, _g = _sheet(b, tmp_path, "s")
    acc = sm.bind_domain(truth_binding(sm, us, b))
    assert acc["guards"] == ["total_w", "total_h"]
    bid = sm.domain[0]["id"]
    res = sm.apply_feature(us, {"count": n1, "binding": bid, "field": "project.cells", "nouns": ["cells"]}, out_dir=str(tmp_path / "rev"))
    cfg = sm.domain[0]["config"]["project.cells"]
    assert cfg["value"] == n1 and "feature operation" in cfg["basis"] and f"{n0} → {n1}" in cfg["basis"]
    rep = sm.domain_report()[0]
    assert rep["outputs"]["total_w"]["result"] == "holds" and rep["outputs"]["total_w"]["measured"] == pytest.approx(box(n1).width)
    assert rep["outputs"]["total_h"]["result"] == "holds" and res["plan"]["status"] == "ready"
    assert sm.undo() and sm.domain[0]["config"]["project.cells"]["value"] == n0


@needs_bridge
def test_a_count_the_binding_still_states_wrongly_is_caught_by_the_guard_and_nothing_changes(tmp_path):
    b = box(2)
    sm, us, _up, _g = _sheet(b, tmp_path, "s")
    sm.bind_domain(truth_binding(sm, us, b))
    plan = refuse(sm, us, tmp_path, {"count": 3}, r"production rule .*total_w")  # the count was not tied to its field: the production model still says 2
    assert plan["status"] == "refused"
    refuse(sm, us, tmp_path, {"count": 3, "binding": sm.domain[0]["id"], "field": "project.no_such"}, "does not state project.no_such")


@needs_bridge
def test_a_view_that_does_not_follow_the_change_is_refused_by_the_guard(tmp_path):
    b = box(2)
    sm, us, up, _g = _sheet(b, tmp_path, "s", unlink=True)
    sm.bind_domain(truth_binding(sm, us, b, plan_unit=up))
    assert us != up
    refuse(sm, us, tmp_path, {"count": 3, "binding": sm.domain[0]["id"], "field": "project.cells"}, r"production rule .*total_w .*7000 mm")


# ── through the agent's tools ────────────────────────────────────────────────────


def _bench_session(sm, us):
    class _Bench:
        def __init__(self):
            self.sm, self.units, self.active = sm, {}, us
            self.run = type("R", (), {"scope": {"units": [us]}})()

        @staticmethod
        def _lock():
            import contextlib

            return contextlib.nullcontext()

    return ProductionSession(M.knowledge(), _Bench())


@needs_bridge
def test_assess_change_offers_the_operation_where_the_drawing_can_take_it_and_says_why_where_it_cannot(tmp_path):
    b = box(2)
    sm, us, _up, _g = _sheet(b, tmp_path, "s")
    sm.bind_domain(truth_binding(sm, us, b))
    ses = _bench_session(sm, us)
    res = ses._assess_change({"project.cells": 3}, family="railway_rcc_box")
    row = res["fields"][0]
    assert row["status"] == "feature_operation" and row["can_apply"] is True and "why" not in row
    assert row["operation"]["count"] == 3 and row["operation"]["field"] == "project.cells" and row["operation"]["binding"] == sm.domain[0]["id"]
    assert row["feature_operation"]["effects"]["copied"] == 8 and row["feature_operation"]["grows_mm"] == pytest.approx(3300.0)
    assert res["outputs"]["total_w"]["after"] - res["outputs"]["total_w"]["before"] == pytest.approx(b.span + b.mid)
    assert "propose_plan(operation=" in row["how"] and res["verdict"].startswith("every changed field can be applied")
    before = state_of(sm)
    for bad in (2.5, 0, True):
        r = ses._assess_change({"project.cells": bad}, family="railway_rcc_box")["fields"][0]
        assert r["status"] == "topology_change" and r["can_apply"] is False and "whole number" in json.dumps(r["feature_operation"])
    assert state_of(sm) == before, "assessing never changes the sheet"
    (tmp_path / "d").mkdir()
    sm2, us2, _up2, _g2 = _sheet(replace(Box(cells=2), detail=True), tmp_path / "d", "s")
    sm2.bind_domain(truth_binding(sm2, us2, replace(Box(cells=2), detail=True)))
    r = _bench_session(sm2, us2)._assess_change({"project.cells": 3}, family="railway_rcc_box")["fields"][0]
    assert r["status"] == "topology_change" and r["can_apply"] is False and r["feature_operation"]["status"] == "needs_decision"
    assert "touch nothing of the structure" in r["why"] and "detached" in r["why"] and r["operation"]["count"] == 3
    (tmp_path / "e").mkdir()
    sm3, us3, _up3, _g3 = _sheet(replace(Box(cells=2), detail=True, detail_x=9500), tmp_path / "e", "s")
    sm3.bind_domain(truth_binding(sm3, us3, replace(Box(cells=2), detail=True, detail_x=9500)))
    r = _bench_session(sm3, us3)._assess_change({"project.cells": 3}, family="railway_rcc_box")["fields"][0]
    assert r["status"] == "topology_change" and r["can_apply"] is False and "into L01" in r["why"] and r["feature_operation"]["status"] == "refused"


def _wait(sheet, rid, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        p = sheet.run_progress(rid, 0)
        if p["status"] not in ACTIVE:
            return p
        time.sleep(0.03)
    raise AssertionError(sheet.run_progress(rid, 0)["status"])


READ = call("account_instruction", items=[
    {"quote": "Bind the production model", "kind": "process", "meaning": "keep what holds", "handled_by": "none", "why": "a check"},
    {"quote": "Add a cell", "kind": "change_value", "meaning": "the stated count is 3", "handled_by": "plan", "why": "a change of count"}])
INSTRUCTION = "Bind the production model. Add a cell."


def _run(sheet, sm, us, b, extra_script, options=None):
    tb = truth_binding(sm, us, b)
    script = [[READ],
              [call("bind_production_model", family="railway_rcc_box", unit=us, inputs=tb["inputs"], config=tb["config"], outputs=tb["outputs"])],
              [call("assess_change", family="railway_rcc_box", changes={"project.cells": b.cells + 1})], *extra_script,
              [call("finish", summary="a cell was added")]]
    gem = ScriptedModel(script)
    sheet.gem_factory = lambda: gem
    p = _wait(sheet, sheet.start_run({"instruction": INSTRUCTION, "options": {"domain": "bridge", **(options or {})}})["run"])
    out = []
    for turn in gem.seen:
        for fr in turn:
            r = fr.response["result"]
            out += [r, r["result"]] if isinstance(r, dict) and isinstance(r.get("result"), dict) else [r]  # a write comes with the engine's status beside it
    return gem, p, out


@needs_bridge
def test_propose_plan_with_the_operation_adds_the_cell_and_the_production_guards_hold(tmp_path):
    b = box(2)
    sm, us, _up, _g = _sheet(b, tmp_path, "s")
    sheet = SheetSession()
    sheet.sm = sm
    operation = {"kind": "set_count", "count": 3, "unit": us, "binding": f"railway_rcc_box@{us}", "field": "project.cells", "nouns": ["cell", "cells"]}
    _gem, p, results = _run(sheet, sm, us, b, [[call("propose_plan", operation=operation)]])
    assess = next(r for r in results if isinstance(r, dict) and r.get("fields"))
    assert assess["fields"][0]["status"] == "feature_operation" and assess["fields"][0]["operation"]["count"] == 3
    verdict = next(r for r in results if isinstance(r, dict) and r.get("plan") == "accepted and applied")
    assert verdict["ok"] and verdict["from_count"] == 2 and verdict["to_count"] == 3 and verdict["effects"]["copied"] == 8
    want, got = generated(tmp_path, box(3)), signature(sm.dr)
    assert not (want - got) and not (got - want)
    assert sm.domain[0]["config"]["project.cells"]["value"] == 3 and sm.lineage and sm.lineage[0]["to_count"] == 3
    rep = sm.domain_report()[0]
    assert rep["outputs"]["total_w"]["result"] == "holds"
    assert p["status"] in ("completed", "partial"), p["verdict"]["remaining"]


@needs_bridge
def test_propose_plan_with_an_operation_the_drawing_cannot_take_changes_nothing(tmp_path):
    b = replace(Box(cells=2), detail=True, detail_x=9500)
    sm, us, _up, _g = _sheet(b, tmp_path, "s")
    sheet = SheetSession()
    sheet.sm = sm
    before = state_of(sm)
    operation = {"kind": "set_count", "count": 3, "unit": us, "binding": f"railway_rcc_box@{us}", "field": "project.cells"}
    _gem, _p, results = _run(sheet, sm, us, b, [[call("propose_plan", operation=operation)]])
    refused = next(r for r in results if isinstance(r, dict) and r.get("plan") == "refused")
    assert refused["ok"] is False and "into L01" in json.dumps(refused["rejected"]) and refused["note"] == "nothing was changed"
    after = state_of(sm)
    assert after["path"] == before["path"] and after["items"] == before["items"] and after["lineage"] == [] \
        and after["domain"][0]["config"]["project.cells"]["value"] == 2


@needs_bridge
def test_the_person_can_ask_to_approve_a_change_of_count_before_the_sheet_changes(tmp_path):
    b = box(2)
    sm, us, _up, _g = _sheet(b, tmp_path, "s")
    sheet = SheetSession()
    sheet.sm = sm
    operation = {"kind": "set_count", "count": 3, "unit": us, "binding": f"railway_rcc_box@{us}", "field": "project.cells"}
    _gem, p, results = _run(sheet, sm, us, b, [[call("propose_plan", operation=operation)], [call("finish", summary="the plan waits")]], {"confirm_plan": True})
    assert p["status"] == "awaiting_user" and any("Apply this change of count? 2 → 3" in q["text"] for q in p["questions"])
    assert len(sm.dr.items) == 33 and sm.lineage == [], "nothing changes while the question is open"
    q = next(q for q in p["questions"] if q["about"] == "feature")
    sheet.continue_run({"run": p.get("run", sheet.current_run), "answers": {q["id"]: "apply"}})
    p = _wait(sheet, sheet.current_run)
    assert len(sm.dr.items) == 41 and sm.lineage[0]["to_count"] == 3, p["status"]
    assert json.dumps(results)


def test_a_session_state_copy_is_independent(tmp_path):
    """The candidate is built on copies: planning twice, or planning then applying, gives the same plan and leaves the sheet alone."""
    sm, us, _up, _g = _sheet(box(2), tmp_path, "s")
    before = copy.deepcopy(state_of(sm))
    a = sm.plan_feature(us, {"count": 3})
    b = sm.plan_feature(us, {"count": 3})
    assert a == b and state_of(sm) == before
    res = sm.apply_feature(us, {"count": 3}, plan_id=a["id"], out_dir=str(tmp_path / "rev"))
    assert res["plan"]["id"] == a["id"]


def test_the_page_is_told_to_load_the_sheet_again_when_the_drawing_is_another_revision(tmp_path):
    sm, us, _up, _g = _sheet(box(2), tmp_path, "s")
    sheet = SheetSession()
    sheet.sm = sm
    sheet.geometry()
    assert "reload" not in sheet._commit_delta(), "a value change keeps the page's entities: only what moved comes back"
    sm.apply_feature(us, {"count": 3}, out_dir=str(tmp_path / "rev"))
    assert sheet._commit_delta() == {"reload": True, "delta": [], "errors": []}
    assert len(sheet.geometry()["prims"]) > 0 and "reload" not in sheet._commit_delta()
    assert sheet.history("undo")["reload"] is True
