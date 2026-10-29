"""A drawing's own legend says what its colours mean: "PROP. WORK SHOWN IN RED", "DISMANTLED WORK SHOWN IN YELLOW", or a sample line beside
"RAILWAY LAND BOUNDARY". Work to be dismantled and a boundary stay where they are drawn — a structure's value never re-sets them — and new work may
pass through dismantled work. A 7A sheet's wing walls to be dismantled had been named part of the new box: every side chosen for its span was refused."""

from __future__ import annotations

import ezdxf
import pytest
from ezdxf.colors import rgb2int
from test_intent_plan import box_sheet

from dxf_autoparam.crossview import SheetModel
from dxf_autoparam.dxf_read import read_dxf
from dxf_autoparam.legend import FG, entity_states, read_legend

ORANGE = (242, 103, 34)


@pytest.fixture(autouse=True)
def bridge_pack(monkeypatch):
    monkeypatch.setenv("AUTOPARAM_DOMAIN", "bridge")


def legend_sheet(path, rows: list[tuple[str, tuple[int, int, int] | None]], extra=None) -> str:
    """A sheet with a legend table: each row a text and, when given, a sample stroke in that colour to its right."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for k, (words, rgb) in enumerate(rows):
        y = -1000.0 * k
        msp.add_text(words, dxfattribs={"insert": (0, y), "height": 250})
        if rgb is not None:
            msp.add_line((6000, y + 120), (9000, y + 120), dxfattribs={"true_color": rgb2int(rgb)})
    msp.add_lwpolyline([(0, 5000), (4000, 5000), (4000, 8000), (0, 8000)], close=True, dxfattribs={"true_color": rgb2int((255, 0, 0))})
    msp.add_line((4000, 6000), (6000, 6000), dxfattribs={"true_color": rgb2int((205, 105, 40))})  # a near orange: drawn in the dismantling family
    msp.add_line((0, 9000), (4000, 9000), dxfattribs={"true_color": rgb2int((0, 255, 0))})
    if extra:
        extra(msp)
    doc.saveas(path)
    return str(path)


def test_the_sample_line_says_the_colour_and_outranks_the_word(tmp_path):
    dr, _ = read_dxf(legend_sheet(tmp_path / "s.dxf", [("DISMANTLED WORK SHOWN IN YELLOW", None), ("DISMANTLE WORK", ORANGE),
                                                       ("PROP. WORK SHOWN IN RED", None), ("RAILWAY LAND BOUNDARY", (0, 255, 0))]))
    lg = read_legend(dr)
    assert lg.colours["dismantled"] == ["#ffff00", "#f26722"] and lg.colours["boundary"] == ["#00ff00"] and lg.colours["proposed"] == ["#ff0000"]
    st = entity_states(dr, lg)
    by = {it.dxftype + str(round(it.pts[0][1])): st.get(it.index) for it in dr.items if it.role.value == "structural" and it.pts[0][1] >= 5000}
    assert by == {"LWPOLYLINE5000": "proposed", "LINE6000": "dismantled", "LINE9000": "boundary"}, "each by the legend colour nearest in hue"


def test_a_level_beside_its_line_or_a_note_is_not_a_legend_entry_and_a_shared_colour_says_nothing(tmp_path):
    dr, _ = read_dxf(legend_sheet(tmp_path / "s.dxf", [("PROP. ROAD LEVEL 711.477", (255, 0, 0)), ("EXISTING WORK", (255, 0, 0)),
                                                       ("PROPOSED WORK", (255, 0, 0)), ("DISMANTLED WORK SHOWN IN BLACK", None)]))
    lg = read_legend(dr)
    assert not any("LEVEL" in e["text"] for e in lg.entries), "a level is not a legend entry"
    assert "proposed" not in lg.colours and "existing" not in lg.colours, "red named for two states tells them apart from nothing"
    assert "dismantled" not in lg.colours, "what stays as drawn is never the foreground: most of the drawing is drawn in it"
    assert FG == "fg" and entity_states(dr, lg) == {}


def _with_dismantling(msp):
    msp.add_text("DISMANTLED WORK SHOWN IN YELLOW", dxfattribs={"insert": (30000, 20000), "height": 250})
    msp.add_text("DISMANTLE WORK", dxfattribs={"insert": (30000, 19000), "height": 250})
    msp.add_line((36000, 19120), (39000, 19120), dxfattribs={"true_color": rgb2int(ORANGE)})


def test_work_to_be_dismantled_stays_where_it_is_drawn_when_the_new_work_beside_it_changes(tmp_path, monkeypatch):
    from dxf_autoparam.plan_bench import box_gad

    def dismantling_box(path, b):  # the box with an old wall's stub against its right wall, drawn in the legend's dismantling colour
        g = box_gad(path, b)
        doc = ezdxf.readfile(g["path"])
        msp = doc.modelspace()
        stub = msp.add_line((7000, 1600), (8000, 1600), dxfattribs={"true_color": rgb2int(ORANGE)})
        _with_dismantling(msp)
        doc.saveas(g["path"])
        g["stub"] = stub.dxf.handle
        return g

    import test_intent_plan as T

    monkeypatch.setattr(T, "box_gad", dismantling_box)
    sm, uid, g = box_sheet(tmp_path)
    k = next(it.index for it in sm.dr.items if it.handle == g["stub"])
    assert sm.legend_states().get(k) == "dismantled"
    drawn = list(sm.dr.items[k].pts)
    r = sm.regenerate({f"{uid}.ClearSpan": 3400.0})
    assert r.ok, r.errors
    assert r.reg.pts.get(k, drawn) == pytest.approx(drawn), "the stub to be dismantled stays where it is drawn"
    assert any(p.type == "dismantled" for p in sm.unit(uid).prog.intent["parts"].values())
    assert not any(c.get("source") == "legend" for c in sm.unit(uid).answer.get("components", [])), "built in, never saved in the answer"

    monkeypatch.setattr(SheetModel, "legend_states", lambda self: {})  # the same sheet read without its legend: the stub follows the wall
    (tmp_path / "plain").mkdir()
    sm2, uid2, g2 = box_sheet(tmp_path / "plain")
    k2 = next(it.index for it in sm2.dr.items if it.handle == g2["stub"])
    moved = sm2.regenerate({f"{uid2}.ClearSpan": 3400.0}).reg.pts.get(k2, drawn)
    assert moved != pytest.approx(drawn)
