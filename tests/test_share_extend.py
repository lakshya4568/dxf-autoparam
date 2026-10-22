"""A shared value takes another view: the third view that draws the same slab joins the value two views already share.

Found on a real sheet: the agent shared a slab thickness between the cross section and the long section, then opened the earth-retainer detail that
draws the same slab and asked four times to add it — "already shared" each time; the detail kept a value of its own, which a person later changed
alone. Held on a generated sheet of three separate views, each drawing one size."""

from __future__ import annotations

import ezdxf
import pytest

from dxf_autoparam.ai.sheet_ai import apply_shared
from dxf_autoparam.crossview import SheetError, SheetModel
from dxf_autoparam.generic import is_generated


def three_views(tmp_path, heights=(3250.0, 3250.0, 3250.0)):
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.dimstyles.new("GAD50", dxfattribs={"dimtxt": 2.5, "dimscale": 50, "dimgap": 0.6, "dimtad": 1})
    msp = doc.modelspace()
    for k, h in enumerate(heights):
        x0 = k * 12000.0
        msp.add_lwpolyline([(x0, 0), (x0 + 3000, 0), (x0 + 3000, h), (x0, h)], close=True)
        msp.add_lwpolyline([(x0 + 3000, 0), (x0 + 3600, 0), (x0 + 3600, h), (x0 + 3000, h)], close=True)
        msp.add_linear_dim(base=(x0 - 900, 0), p1=(x0, 0), p2=(x0, h), angle=90, dimstyle="GAD50").render()
        msp.add_linear_dim(base=(x0, h + 700), p1=(x0 + 3000, h), p2=(x0 + 3600, h), dimstyle="GAD50").render()
        msp.add_text(f"SECTION {'ABC'[k]}-{'ABC'[k]}", height=175, dxfattribs={"insert": (x0 + 800, -1200)})
    path = tmp_path / "three.dxf"
    doc.saveas(str(path))
    sm = SheetModel.open(str(path))
    assert len(sm.units) == 3
    return sm


def name_height(sm, uid: str, name: str = "WallHeight") -> str:
    u = sm.unit(uid)
    old = next(n for n, p in u.prog.params.items() if is_generated(n) and p.kind == "length" and p.measures
               and abs(p.value - max(q.value for q in u.prog.params.values() if q.kind == "length")) < 1e-6)
    sm.rename(f"{uid}.{old}", name)
    return name


@pytest.fixture
def sheet(tmp_path):
    sm = three_views(tmp_path)
    for uid in sm.units:
        name_height(sm, uid)
    return sm


def test_a_shared_value_takes_a_third_view_in_one_step(sheet):
    u1, u2, u3 = sorted(sheet.units)
    sheet.share("WallHeight", [(u1, "WallHeight"), (u2, "WallHeight")])
    depth = len(sheet.history)
    p = sheet.share("WallHeight", [(u3, "WallHeight")])
    assert sorted(b.unit for b in p.bindings) == [u1, u2, u3] and all(b.status == "drives" for b in p.bindings)
    assert len(sheet.history) == depth + 1, "one undoable step"
    r = sheet.regenerate({"WallHeight": 3500.0})
    assert r.ok and set(r.measured["WallHeight"]) == {u1, u2, u3} and all(abs(v - 3500.0) < 1e-6 for v in r.measured["WallHeight"].values())
    assert sheet.undo() and sorted(b.unit for b in sheet._shared_by_name()["WallHeight"].bindings) == [u1, u2]


def test_naming_the_views_it_has_with_the_new_one_is_the_same_as_naming_only_the_new_one(sheet):
    u1, u2, u3 = sorted(sheet.units)
    sheet.share("WallHeight", [(u1, "WallHeight"), (u2, "WallHeight")])
    res = apply_shared(sheet, {"shared": [{"name": "WallHeight", "targets": [[u2, "WallHeight"], [u3, "WallHeight"]]}]})
    assert res["applied"] and not res["refused"], res
    again = apply_shared(sheet, {"shared": [{"name": "WallHeight", "targets": [[u3, "WallHeight"]]}]})
    assert again["applied"] and not again["refused"], "asking again for what is bound already is not a refusal"


def test_a_new_view_takes_the_value_the_shared_size_has_now(sheet):
    u1, u2, u3 = sorted(sheet.units)
    sheet.share("WallHeight", [(u1, "WallHeight"), (u2, "WallHeight")])
    assert sheet.apply({"WallHeight": 3400.0}).ok
    sheet.share("WallHeight", [(u3, "WallHeight")])
    assert sheet.current()["WallHeight"] == pytest.approx(3400.0)
    r = sheet.regenerate()
    assert r.ok and r.measured["WallHeight"][u3] == pytest.approx(3400.0), "the third view follows at once"


def test_a_view_that_draws_another_size_is_refused_and_nothing_changes(tmp_path):
    sm = three_views(tmp_path, heights=(3250.0, 3250.0, 3000.0))
    for uid in sm.units:
        name_height(sm, uid)
    u1, u2, u3 = sorted(sm.units)
    sm.share("WallHeight", [(u1, "WallHeight"), (u2, "WallHeight")])
    before = (sm.revision, len(sm.history), sorted(b.unit for b in sm._shared_by_name()["WallHeight"].bindings))
    with pytest.raises(SheetError, match="do not state one size"):
        sm.share("WallHeight", [(u3, "WallHeight")])
    assert before == (sm.revision, len(sm.history), sorted(b.unit for b in sm._shared_by_name()["WallHeight"].bindings))
