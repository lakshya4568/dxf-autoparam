"""A corner drawn on another entity's sloped edge follows that edge (validator.bind_on_slopes).

Found on a real sheet: a boulder backing drawn against the battered back face of a return wall was set out from its own corner, so a wider or
deeper wall moved its face away from the backing — a corner came apart (connections.torn said so). A generated wall with a 1:10 batter and a
backing against it; each named value stepped ±10 %: nothing comes apart, and without the rule it does."""

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


def sheet(tmp_path):
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
    ans["parameters"] = [size("WallHeight", "y", 0, 3000), size("TopWidth", "x", 0, 300), size("BottomWidth", "x", 0, 600),
                         size("BackingWidth", "x", 550, 1150), size("FootingDepth", "y", -300, 0)]
    sm.commit_answer(uid, ans)
    return sm, uid


@pytest.mark.parametrize("name", ["WallHeight", "TopWidth", "BottomWidth", "BackingWidth", "FootingDepth"])
def test_a_backing_on_a_battered_face_stays_on_it(tmp_path, name):
    sm, uid = sheet(tmp_path)
    prog = sm.unit(uid).prog
    assert name in prog.params, sorted(prog.params)
    for f in (1.1, 0.9):
        r = regenerate_program(prog, {name: prog.params[name].value * f})
        assert not r.issues, r.issues
        assert torn(prog, r.pts) == [], f"{name} × {f}: a corner came apart"


def test_without_the_rule_the_backing_comes_off_the_face(tmp_path, monkeypatch):
    import dxf_autoparam.validator as V

    monkeypatch.setattr(V, "bind_on_slopes", lambda prog, rep: None)
    sm, uid = sheet(tmp_path)
    prog = sm.unit(uid).prog
    apart = [n for n in ("WallHeight", "TopWidth", "BottomWidth") for f in (1.1, 0.9)
             if torn(prog, regenerate_program(prog, {n: prog.params[n].value * f}).pts)]
    assert apart, "the case the rule is for: some step pulls the backing off the wall"


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
