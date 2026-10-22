"""What the views state side by side — the agent's cross-view reading (search_drawing, compare_views, calculate).

A real sheet of nine views printed one granular fill as 850 in two views and 600 in a third, the bottom of its foundation at three levels, and one size of
3250 in two views that is exactly the difference of two stated levels. The agent saw one view at a time: nothing told it which views state the same thing,
and the engine happily shared two sizes that only happen to be equal. Here a generated two-view sheet states each of those things on purpose."""

from __future__ import annotations

import ezdxf
import pytest

from dxf_autoparam.ai import crosscheck as cc
from dxf_autoparam.ai.run import Run, SheetBench
from dxf_autoparam.crossview import SheetModel
from dxf_autoparam.workspace import SheetSession


def section(msp, x0: float, base: float, levels, title: str, granular: str, dims) -> None:
    """One section: an outline, a horizontal line and a level note per stated level, a granular-fill note, vertical dimensions between levels."""
    lo, hi = min(v for v, _ in levels), max(v for v, _ in levels)
    msp.add_lwpolyline([(x0, (lo - base) * 1000), (x0 + 3000, (lo - base) * 1000), (x0 + 3000, (hi - base) * 1000), (x0, (hi - base) * 1000)], close=True)
    for v, words in levels:
        y = (v - base) * 1000
        msp.add_line((x0 - 600, y), (x0 + 3600, y), dxfattribs={"layer": "LEVEL"})
        msp.add_text(f"{words} {v:.3f}", height=175, dxfattribs={"insert": (x0 + 3700, y + 30)})
    msp.add_text(granular, height=175, dxfattribs={"insert": (x0 + 100, (lo - base) * 1000 - 500)})
    for a, b in dims:
        msp.add_linear_dim(base=(x0 - 900, 0), p1=(x0, (a - base) * 1000), p2=(x0, (b - base) * 1000), angle=90, dimstyle="GAD50", dxfattribs={"layer": "DIM"}).render()
    msp.add_text(title, height=175, dxfattribs={"insert": (x0 + 1000, (lo - base) * 1000 - 1200)})


@pytest.fixture
def sheet(tmp_path):
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    doc.dimstyles.new("GAD50", dxfattribs={"dimtxt": 2.5, "dimscale": 50, "dimgap": 0.6, "dimtad": 1})
    msp = doc.modelspace()
    section(msp, 0, 606.0, [(606.501, "BOTT. OF FOUNDATION"), (608.051, "ROAD LEVEL"), (611.301, "TOP OF SLAB")], "SECTION A-A", "850mm GRANULAR FILLING", [(608.051, 611.301)])
    section(msp, 11000, 596.0, [(606.751, "BOTT. OF FOUNDATION"), (608.051, "ROAD LEVEL"), (611.301, "TOP OF SLAB")], "ELEVATION B-B", "600mm GRANULAR FILLING",
            [(608.051, 611.301)])
    path = tmp_path / "two_views.dxf"
    doc.saveas(str(path))
    return SheetModel.open(str(path))


def test_the_same_words_at_two_numbers_are_reported_not_linked(sheet):
    rep = cc.compare_views(sheet)
    (fill,) = rep["sizes_stated_differently"]
    assert "GRANULAR FILLING" in fill["as"] and sorted(v["mm"] for v in fill["values_mm"]) == [600.0, 850.0]
    (found,) = rep["levels_stated_differently"]
    assert sorted(v["level_m"] for v in found["values_m"]) == [606.501, 606.751], "one wording, two levels: for the person to settle"


def test_what_two_views_state_alike_is_listed_with_where(sheet):
    rep = cc.compare_views(sheet)
    levels = {r["level_m"]: r for r in rep["levels_stated_in_several_views"]}
    assert set(levels) == {608.051, 611.301} and 606.501 not in levels
    assert any("ROAD LEVEL" in n["text"] and len(n["at"]) == 2 for n in levels[608.051]["named"])
    (size,) = rep["sizes_stated_in_several_views"]
    assert size["mm"] == 3250.0 and size["stated_in"] == ["U01", "U02"]
    assert rep["read_this_way"].startswith("evidence, not a verdict"), "equal numbers are not proof of one size, and the tool says so"


def test_a_size_that_runs_between_two_stated_levels_is_named_by_them(sheet):
    (row,) = cc.compare_views(sheet)["dimensions_between_stated_levels"]
    assert row["mm"] == 3250.0 and len(row["dimensions"]) == 2
    assert row["lower"]["level_m"] == 608.051 and any("ROAD LEVEL" in n["text"] for n in row["lower"]["stated_as"])
    assert row["upper"]["level_m"] == 611.301 and any("TOP OF SLAB" in n["text"] for n in row["upper"]["stated_as"])


def test_units_and_focus_narrow_what_is_compared(sheet):
    only_fill = cc.compare_views(sheet, focus="granular filling")
    assert only_fill["sizes_stated_differently"] and not only_fill["levels_stated_differently"] and not only_fill["dimensions_between_stated_levels"]
    assert cc.compare_views(sheet, units=["U01"])["sizes_stated_differently"] == [], "one view alone has nothing to compare with"


def test_words_in_a_different_order_are_not_the_same_words():
    weight = cc.weights(["TOP OF BOTTOM SLAB", "BOTTOM OF TOP SLAB", "BOTT. OF FOUNDATION", "BOT. OF FOUNDATION"])
    assert cc.similarity(cc.words_of("TOP OF BOTTOM SLAB"), cc.words_of("BOTTOM OF TOP SLAB"), weight) < cc.SIMILAR, "two faces of two slabs"
    assert cc.similarity(cc.words_of("BOTT. OF FOUNDATION"), cc.words_of("BOT. OF FOUNDATION"), weight) >= cc.SIMILAR, "a clipped word is the same word"
    assert cc.similarity([], cc.words_of("SLAB"), weight) == 0.0


def test_search_finds_words_and_numbers_across_the_whole_sheet(sheet):
    hits = cc.search_drawing(sheet, words=["granular"])["hits"]
    assert sorted(h["unit"] for h in hits if h["kind"] == "note") == ["U01", "U02"] and all({"view", "id"} <= set(h) for h in hits)
    by_number = cc.search_drawing(sheet, numbers=[3250])["hits"]
    assert [h["kind"] for h in by_number] == ["dimension", "dimension"] and {h["unit"] for h in by_number} == {"U01", "U02"}
    assert {h["kind"] for h in cc.search_drawing(sheet, words=["foundation", "slab"], kinds=["level"])["hits"]} == {"level"}
    assert cc.search_drawing(sheet)["error"], "nothing to look for is said, not answered with everything"


def test_calculate_is_arithmetic_over_named_values_and_nothing_else():
    values = {"TopSlab": (611.301, "m"), "RoadLevel": (608.051, "m"), "Cover": (150.0, "mm")}
    got = cc.calculate("TopSlab - RoadLevel + 2 * Cover", values.get)
    assert got["result_mm"] == pytest.approx(3550.0) and got["terms"]["TopSlab"] == {"mm": 611301.0, "given_as": "611.301 m"}
    assert cc.calculate("max(Cover, 200) / 2", values.get)["result_mm"] == 100.0
    assert "RoadLvl" in cc.calculate("RoadLvl + 1", values.get)["error"], "an unknown name is named"
    for hostile in ("__import__('os').getcwd()", "Cover.real", "[1, 2]", "open('x')"):
        assert "error" in cc.calculate(hostile, values.get), hostile
    assert "error" in cc.calculate("1 / 0", values.get) and "error" in cc.calculate("", values.get)


def test_the_tools_are_the_agent_s_own_read_tools(tmp_path, sheet):
    s = SheetSession()
    s.sm = sheet
    bench = SheetBench(Run(s, "R1", "Which views state the granular fill?", {"kind": "drawing"}))
    for name in ("search_drawing", "compare_views", "calculate"):
        assert bench.is_read(name)
    assert bench.read("compare_views", {"focus": "granular"})["sizes_stated_differently"]
    uid = next(iter(sheet.units))
    bench.open(uid)
    name = next(n for n, p in sheet.unit(uid).prog.params.items() if p.kind == "length")
    value = sheet.unit(uid).prog.params[name].value
    assert bench.read("calculate", {"expression": f"{name} * 2"})["result_mm"] == pytest.approx(2 * value)


def test_a_dimension_says_which_named_value_of_its_unit_already_measures_it_and_whether_it_is_shared(sheet):
    """The evidence is actionable: share_sizes takes a unit's own value by its name, so the rows name it — and say when a shared value binds it already."""
    from dxf_autoparam.generic import is_generated

    def named(uid: str) -> str:
        d = next(d for d in cc.statements(sheet)["all_dims"] if d["unit"] == uid)
        old = next(n for n, p in sheet.unit(uid).prog.params.items() if is_generated(n) and p.measures and frozenset(p.measures) == frozenset(d["between"]))
        sheet.rename(f"{uid}.{old}", "TopHeight")
        return "TopHeight"

    for uid in ("U01", "U02"):
        named(uid)
    (row,) = cc.compare_views(sheet)["dimensions_between_stated_levels"]
    assert [d["value"] for d in row["dimensions"]] == ["TopHeight", "TopHeight"] and not any("shared_as" in d for d in row["dimensions"])
    sheet.share("TopHeight", [("U01", "TopHeight"), ("U02", "TopHeight")])
    (row,) = cc.compare_views(sheet)["dimensions_between_stated_levels"]
    assert [d["shared_as"] for d in row["dimensions"]] == ["TopHeight", "TopHeight"]
    (size,) = cc.compare_views(sheet)["sizes_stated_in_several_views"]
    assert {s["value"] for s in size["as"] if isinstance(s, dict)} == {"TopHeight"}
