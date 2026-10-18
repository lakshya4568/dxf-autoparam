"""The pictures the model reads: sized by the drawing's own text, in tiles when one picture cannot hold it, with the set-out lines under the drawing and in
the margin — never over a note — and never sent twice while the model still has them.

A live run gave the model one 1500 px strip per unit whatever its size: a section 79.7 m wide came out at 53 mm/px with its 200 mm text 4 px tall, and the
set-out lines were drawn across the drawing, full strength, over every note."""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from dxf_autoparam import viewplan as vp
from dxf_autoparam.ai.loop import pack
from dxf_autoparam.ai.run import Run, SheetBench, _bound_tables
from dxf_autoparam.crossview import SheetModel
from dxf_autoparam.plan_bench import Box, box_gad
from dxf_autoparam.viewimg import Pictures, box_around
from dxf_autoparam.workspace import SheetSession


@pytest.fixture(scope="module")
def wide(tmp_path_factory):
    """An 8-cell box 43 m wide: a section and a plan, with dimensions and notes at drawing scale 1:50."""
    g = box_gad(tmp_path_factory.mktemp("pics") / "wide.dxf", Box(cells=8, span=4000.0))
    sm = SheetModel.open(g["path"])
    uid = next(iter(sm.units))
    sm.unit(uid)
    return sm, uid, Pictures(sm), box_around([sm.layout.group(v).bbox for v in sm.units[uid].views])


def test_a_wide_unit_gets_an_overview_and_tiles_at_a_scale_where_its_text_can_be_read(wide):
    _sm, uid, pics, box = wide
    ps = pics.unit_set(uid, box)
    plan, ov, tiles = ps["plan"], ps["overview"]["meta"], [t["meta"] for t in ps["tiles"]]
    assert len(tiles) >= 3 and not ov["legible"], "one picture of 43 m cannot hold text drawn for 1:50"
    assert ov["kind"] == "overview" and all(t["kind"] == "tile" for t in tiles)
    assert all(t["mm_per_px"] < ov["mm_per_px"] / 2 for t in tiles), "each tile is much closer than the overview"
    assert all(t["legible"] and t["text_px"] >= vp.LEGIBLE * vp.TEXT_PX for t in tiles), [t["text_px"] for t in tiles]
    for m in [ov, *tiles]:  # nothing bigger than the model reads
        w, h = m["frame"]["size"]
        assert max(w, h) <= vp.MODEL_SIDE and w * h <= vp.MODEL_AREA * 1.001, m["frame"]["size"]
    assert [t["name"] for t in ov["tiles"]] == [f"TILE_{k}" for k in range(1, len(tiles) + 1)], "the overview says which part of it each tile is"
    covered = [t["box"] for t in ov["tiles"]]
    assert min(b[0] for b in covered) <= box[0] + 0.05 * (box[2] - box[0]) and max(b[2] for b in covered) >= box[2] - 0.05 * (box[2] - box[0])
    assert plan.tiles and ps["overview"]["id"] != ps["tiles"][0]["id"]


def test_a_unit_whose_text_is_readable_in_one_picture_is_one_picture(tmp_path):
    sm = SheetModel.open(box_gad(tmp_path / "small.dxf", Box(cells=1, span=3000.0))["path"])
    uid = next(iter(sm.units))
    sm.unit(uid)
    pics = Pictures(sm)
    ps = pics.unit_set(uid, box_around([sm.layout.group(v).bbox for v in sm.units[uid].views]))
    assert ps["tiles"] == [] and ps["overview"]["meta"]["legible"] and ps["overview"]["meta"]["kind"] == "overview"


def test_the_picture_is_the_width_its_own_text_needs_not_a_fixed_one(wide):
    _sm, uid, pics, box = wide
    near = (box[0] + 15_000.0, box[1], box[0] + 22_000.0, box[3])
    a = pics.picture(box=near, unit=uid, state="drawn", ids="entities", caption="near", width=None, kind="zoom")["meta"]
    b = pics.picture(box=box, unit=uid, state="drawn", ids="none", caption="far", width=None, kind="zoom")["meta"]
    assert a["text_px"] > b["text_px"] and a["frame"]["size"] != b["frame"]["size"]
    assert a["text_px"] >= vp.LEGIBLE * vp.TEXT_PX and a["legible"], "a crop of 10 m is read at its own scale"


def test_the_set_out_lines_are_in_the_margin_and_under_the_drawing_never_over_it(wide):
    _sm, uid, pics, box = wide
    tile = pics.unit_set(uid, box)["tiles"][1]
    img = Image.open(io.BytesIO(tile["png"])).convert("RGB")
    w, h = img.size
    pad = tile["meta"]["frame"]["pad"]
    assert pad == vp.GUTTER
    # the margin holds ticks and labels, and nothing the drawing ran on into: the outermost columns are white all the way down
    assert all(img.getpixel((x, y)) == (255, 255, 255) for x in range(6) for y in range(0, h, 7))
    # a line of the drawing lies ON a set-out line (that is what a set-out line is): where they coincide the pixel is the drawing's own black,
    # not a blue tint of a hairline drawn over it
    xs = [d for d in tile["meta"]["lines_labelled"] if d["axis"] == "x"]
    assert xs, "the tile labels its x lines"
    fr = tile["meta"]["frame"]
    scale, ox = fr["scale_px_per_unit"], fr["origin"][0]
    clean = counted = 0
    for d in xs:
        px = round(pad + (d["at"] - ox) * scale)
        if pad + 5 < px < w - pad - 5:
            counted += 1
            clean += any(max(c) < 60 and abs(c[2] - c[0]) < 12 for c in (img.getpixel((px, y)) for y in range(pad + 20, h - pad - 20)))
    # measured: 15 of 15 as drawn; the same hairlines laid OVER the drawing tint it blue and leave 7 of 15 — so "nearly all", not "one"
    assert counted >= 5 and clean >= 0.9 * counted, f"the drawing's own lines are drawn at full strength on their set-out lines: {clean} of {counted}"


def test_labels_never_exceed_what_fits_and_the_overview_labels_fewer_than_a_tile(wide):
    _sm, uid, pics, box = wide
    ps = pics.unit_set(uid, box)
    ov = ps["overview"]["meta"]
    fr = ov["frame"]
    x_ov = [d for d in ov["lines_labelled"] if d["axis"] == "x"]
    assert len(x_ov) <= int((fr["size"][0] - 2 * fr["pad"]) // 44)
    tile = ps["tiles"][0]["meta"]
    x_tile = [d for d in tile["lines_labelled"] if d["axis"] == "x"]
    assert len(x_tile) <= int((tile["frame"]["size"][0] - 2 * tile["frame"]["pad"]) // vp.MIN_LINE_PX)
    assert ov["lines_in_frame"] >= len(ov["lines_labelled"]) and tile["lines_in_frame"] >= len(tile["lines_labelled"])


def test_a_picture_the_model_still_has_is_named_not_sent_again(wide):
    sm, uid, pics, _box = wide
    sheet = SheetSession()
    sheet.sm = sm
    sheet.pictures = pics
    bench = SheetBench(Run(sheet, "R9", "Make this whole drawing parametric.", {"kind": "drawing"}))
    bench.set_turn(3)
    first = bench.open_unit(uid)
    n = 1 + len(first["pictures"].get("tiles", []))
    assert len(first["_images"]) == n and "pictures_already_shown" not in first
    assert first["pictures"]["tiles"][0]["image"] in {p["id"] for p in first["_images"]}
    bench.set_turn(5)  # two turns later the pictures are in the conversation still
    again = bench.open_unit(uid)
    assert "_images" not in again and set(again["pictures_already_shown"]["ids"]) == {first["image"], *(t["image"] for t in first["pictures"]["tiles"])}
    assert bench.pictures_deduped == n and again["image"] == first["image"], "the same pictures, named"
    bench.set_turn(9)  # four turns on, the conversation has let them go: they are sent again
    later = bench.open_unit(uid)
    assert len(later["_images"]) == n and "pictures_already_shown" not in later
    # the person's record of what the model was shown has them all, once
    assert {first["image"], *(t["image"] for t in first["pictures"]["tiles"])} <= set(bench.run.images)
    row = bench.run.images[first["image"]]
    assert row["kind"] == "overview" and row["mm_per_px"] and row["tiles"]


def _bench_over(wide, rid: str):
    sm, uid, pics, _box = wide
    sheet = SheetSession()
    sheet.sm = sm
    sheet.pictures = pics
    run = Run(sheet, rid, "Make this whole drawing parametric.", {"kind": "drawing"})
    run.bench = bench = SheetBench(run)  # as a started run has it: the run reads the turn off its bench
    return bench, uid


def test_the_person_is_told_of_each_picture_that_was_sent_and_not_of_those_only_named(wide):
    bench, uid = _bench_over(wide, "R10")
    events = lambda: [e for e in bench.run.events if e["kind"] == "image"]
    bench.set_turn(3)
    first = bench.open_unit(uid)
    sent = events()
    assert [e["id"] for e in sent] == [p["id"] for p in first["_images"]] and len(sent) >= 4
    assert sent[0]["pic"]["kind"] == "overview" and {e["pic"]["kind"] for e in sent[1:]} == {"tile"}
    assert all(e["why"] == f"open_unit {uid}" and e["pic"]["turn"] == 3 and e["pic"]["mm_per_px"] and e["unit"] == uid for e in sent)
    assert [e["pic"]["caption"] for e in sent[1:]] == [f"{uid} · TILE_{k}" for k in range(1, len(sent))], "a tile is named as the overview marks it"
    assert sent[0]["pic"]["tiles"] == [f"TILE_{k}" for k in range(1, len(sent))]
    bench.set_turn(5)
    again = bench.open_unit(uid)  # the model still has them: they are named to it, and not announced to the person as given again
    assert "_images" not in again and len(events()) == len(sent)


def test_inspect_view_with_a_picture_hands_over_the_picture_and_then_says_the_model_has_it(wide):
    bench, uid = _bench_over(wide, "R11")
    view = bench.sm.units[uid].views[0]
    bench.set_turn(2)
    first = bench.understanding.call("inspect_view", {"view": view, "picture": True})
    assert len(first["_images"]) == 1 and first["picture"]["image"] == first["_images"][0]["id"]
    bench.set_turn(3)
    again = bench.understanding.call("inspect_view", {"view": view, "picture": True})
    assert "_images" not in again and again["pictures_already_shown"]["ids"] == [first["picture"]["image"]]


def test_a_result_with_several_pictures_sends_them_all_next_to_its_numbers():
    class Call:
        name = "open_unit"

    res = {"unit": "U01", "_images": [{"png": b"\x89PNG-1"}, {"png": b"\x89PNG-2"}, {"png": b"\x89PNG-3"}]}
    part = pack(Call(), res)
    assert len(part.function_response.parts) == 3 and "_images" not in res and part.function_response.response == {"result": {"unit": "U01"}}
    one = pack(Call(), {"unit": "U01", "_image": {"png": b"x"}})
    assert len(one.function_response.parts) == 1
    assert pack(Call(), {"unit": "U01"}).function_response.parts is None or not pack(Call(), {"unit": "U01"}).function_response.parts


def test_the_two_big_tables_are_bounded_by_what_matters_and_the_rest_is_counted():
    lines = [[f"x{k}", float(k * 100), f"x{k - 1} + {k}"] for k in range(551)]
    regions = [[f"R{k}", float(10 + k), float(10 + k), "x1/x2/y1/y2", "", "", "R1:b", "a note" if k == 5 else ""] for k in range(376)]
    ov = {"CONTEXT": {"drawing": "x" * 9000}, "regions [id, width, height]": regions, "lines [id, at mm, set out as]": lines, "texts": []}
    score = {f"x{k}": float(k % 17) for k in range(551)}
    out, left = _bound_tables(ov, score, anchors={"x3", "x540"})
    assert len(json.dumps(out, separators=(",", ":"))) <= 30000 and left and left["lines_left_out"] > 0 and left["regions_left_out"] > 0
    kept_lines = {r[0] for r in out["lines [id, at mm, set out as]"]}
    assert {"x3", "x540"} <= kept_lines, "an anchor is always kept"
    kept_scores = [score[i] for i in kept_lines if i in score and i not in {"x3", "x540"}]
    dropped_scores = [score[f"x{k}"] for k in range(551) if f"x{k}" not in kept_lines]
    assert min(kept_scores) >= max(dropped_scores), "then the highest scores: nothing kept scores below anything left out"
    kept_regions = [r[0] for r in out["regions [id, width, height]"]]
    assert "R5" in kept_regions, "a region with a note inside is always kept"
    assert "R375" in kept_regions and "R0" not in kept_regions, "then the largest"
    assert out["lines [id, at mm, set out as]"][-1][0] == "…" and "inspect_lines" in out["lines [id, at mm, set out as]"][-1][2]
    small, none = _bound_tables({"lines [id, at mm, set out as]": lines[:20], "regions [id, width, height]": regions[:20]}, score, set())
    assert none is None and small["lines [id, at mm, set out as]"] == lines[:20], "a small overview is whole"
