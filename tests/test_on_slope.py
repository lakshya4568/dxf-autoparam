"""A corner drawn on another entity's sloped edge follows that edge (validator.bind_on_slopes).

Found on a real sheet: a boulder backing drawn against the battered back face of a return wall was set out from its own corner, so a wider or
deeper wall moved its face away from the backing — a corner came apart (connections.torn said so). A generated wall with a 1:10 batter and a
backing against it; each named value stepped ±10 %: nothing comes apart. With both widths named the face turns: the corner is left, and the edit
says when the backing comes off."""

from __future__ import annotations

import copy

import ezdxf
import pytest

from dxf_autoparam.connections import torn
from dxf_autoparam.crossview import EMPTY_ANSWER, SheetModel
from dxf_autoparam.regen import regenerate_program
from dxf_autoparam.topology import of


def battered_wall(path) -> str:
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (600, 0), (300, 3000), (0, 3000)], close=True)  # the wall: vertical front, back face battered 1 in 10
    msp.add_lwpolyline([(550, 500), (1150, 500), (950, 2500), (350, 2500)], close=True)  # the backing, its left edge on the back face
    msp.add_lwpolyline([(-300, -300), (1500, -300), (1500, 0), (-300, 0)], close=True)  # a footing under both
    for base, p1, p2, angle in [((-800, 0), (0, 0), (0, 3000), 90), ((0, 3400), (0, 3000), (300, 3000), 0), ((0, -800), (0, 0), (600, 0), 0),
                                ((550, 200), (550, 500), (1150, 500), 0), ((1800, 0), (1500, -300), (1500, 0), 90)]:
        msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle).render()
    doc.saveas(str(path))
    return str(path)


def sheet(tmp_path, top_width: bool = False):
    """The wall and its backing as parts. `top_width`: the wall's top width named too — with both widths inputs its batter is a result, and
    the back face turns when either changes."""
    sm = SheetModel.open(battered_wall(tmp_path / "wall.dxf"))
    uid = next(iter(sm.units))
    u = sm.unit(uid)
    an, um = u.an, u.sub.units_mm
    regions = of(an).regions

    def region(x, y):
        return min((r for r in regions if r.bbox[0] <= x / um <= r.bbox[2] and r.bbox[1] <= y / um <= r.bbox[3]), key=lambda r: r.area).id

    def line(axis, at):
        return min((d for d in an.datums.values() if d.axis == axis), key=lambda d: abs(d.value * um - at)).id

    def size(name, axis, lo, hi):
        return {"name": name, "label": name, "kind": "length", "from_datum": line(axis, lo), "to_datum": line(axis, hi), "value": abs(hi - lo)}

    ans = copy.deepcopy(EMPTY_ANSWER)
    ans["components"] = [{"name": "Wall", "type": "wall", "regions": [region(100, 1500)]}, {"name": "Backing", "type": "fill", "regions": [region(750, 1500)]},
                         {"name": "Footing", "type": "footing", "regions": [region(700, -150)]}]
    ans["parameters"] = [size("WallHeight", "y", 0, 3000), size("BottomWidth", "x", 0, 600), size("BackingWidth", "x", 550, 1150),
                         size("FootingDepth", "y", -300, 0), *([size("TopWidth", "x", 0, 300)] if top_width else [])]
    sm.commit_answer(uid, ans)
    return sm, uid


@pytest.mark.parametrize("name", ["WallHeight", "BottomWidth", "BackingWidth", "FootingDepth"])
def test_a_backing_on_a_battered_face_stays_on_it(tmp_path, name):
    sm, uid = sheet(tmp_path)
    prog = sm.unit(uid).prog
    assert name in prog.params, sorted(prog.params)
    for f in (1.1, 0.9):
        r = regenerate_program(prog, {name: prog.params[name].value * f})
        assert not r.issues, r.issues
        assert torn(prog, r.pts) == [], f"{name} × {f}: a corner came apart"


def test_a_face_that_turns_is_left_and_the_edit_says_the_backing_came_off(tmp_path):
    """With both widths named the batter is a result: the face turns when either changes. A corner bound to a turning edge is no chain the
    design intent can stack through, so it is left — and the change says what came apart, for the person to settle."""
    sm, uid = sheet(tmp_path, top_width=True)
    prog = sm.unit(uid).prog
    assert not any("sloped edge" in str(w) for w in prog.origin_why.values()), "nothing bound to a turning face"
    r = sm.regenerate({f"{uid}.TopWidth": prog.params["TopWidth"].value * 0.9})  # a narrower top: the face leans away from the backing
    assert r.ok and any("pulled them apart" in w and "Backing" in w for w in r.warnings), r.warnings


def test_a_corner_a_named_value_drives_is_left_to_it(tmp_path):
    """Found on the real sheet: the rule rebound the one line a named size drove (a backing's thickness), the size was left worked out, and every
    change on the sheet was refused. A corner on a slope that a named value sets out stays with the value; the value keeps driving its lines."""
    sm = SheetModel.open(battered_wall(tmp_path / "wall.dxf"))
    uid = next(iter(sm.units))
    u = sm.unit(uid)
    an, um = u.an, u.sub.units_mm

    def line(axis, at):
        return min((d for d in an.datums.values() if d.axis == axis), key=lambda d: abs(d.value * um - at)).id

    ans = copy.deepcopy(EMPTY_ANSWER)
    ans["parameters"] = [{"name": "WallHeight", "label": "WallHeight", "kind": "length", "from_datum": line("y", 0), "to_datum": line("y", 3000), "value": 3000},
                         {"name": "BackingSetBack", "label": "BackingSetBack", "kind": "length", "from_datum": line("x", 0), "to_datum": line("x", 550), "value": 550}]
    sm.commit_answer(uid, ans)
    prog = sm.unit(uid).prog
    a, b = prog.params["BackingSetBack"].measures
    v0, v1 = prog.datum_values(), prog.datum_values({"BackingSetBack": 551.0})
    assert abs(abs(v1[b] - v1[a]) - abs(v0[b] - v0[a])) * um == pytest.approx(1.0), "the named value still drives its two lines"
    assert sm.apply({f"{uid}.WallHeight": 3300.0}).ok and sm.apply({f"{uid}.BackingSetBack": 600.0}).ok
