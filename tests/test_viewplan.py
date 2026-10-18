"""How a unit is shown to a model that reads pictures — the decisions, as numbers: how big, how many pieces, which set-out lines, where the labels go.

The sizes are those of the live run's units (mm drawing, 1:100 sections): a longitudinal section 79.7 m wide came out as one 1500 px strip at 53 mm/px, its
250 mm text 4.7 px tall; 56 set-out lines were drawn across a plan as a green band; and about a hundred labels overlapped along the margins."""

from __future__ import annotations

import random
from itertools import pairwise

import pytest

from dxf_autoparam import viewplan as vp


def test_the_text_size_is_a_quarter_of_the_texts_without_the_titles():
    box = (0.0, 0.0, 80_000.0, 20_000.0)
    notes = [250.0] * 30 + [350.0] * 10 + [800.0] * 3  # dimension texts, notes, a view title
    assert vp.text_height(notes + [4000.0, 6000.0], box) == 250.0, "a title (taller than a twentieth of the box) does not set the text size"
    assert vp.text_height([250.0, 250.0], box) == pytest.approx(20_000 / 60), "too few texts to say: a sixtieth of the box's smaller side"
    assert vp.percentile([], 25) == 0.0 and vp.percentile([7.0], 25) == 7.0 and vp.percentile([1, 2, 3, 4], 50) == 2.5


@pytest.mark.parametrize(("name", "w", "h", "text", "tiles", "readable"), [
    ("a longitudinal section 80 m wide", 80_000.0, 17_000.0, 200.0, 5, True),
    ("a 55 m half-section pair", 55_000.0, 13_300.0, 200.0, 4, True),
    ("a 90 m plan", 90_000.0, 12_000.0, 250.0, 5, True),
    ("a 16 m detail", 16_000.0, 9_000.0, 250.0, 0, True),
    ("a 14 m detail with tiny text", 14_000.0, 10_000.0, 60.0, 6, True),
    ("a 100 m by 30 m section, text too small even so", 100_000.0, 30_000.0, 200.0, 5, False),
])
def test_a_unit_too_big_for_its_text_gets_tiles_that_make_the_text_as_readable_as_the_model_can_take(name, w, h, text, tiles, readable):
    box = (0.0, 0.0, w, h)
    plan = vp.plan_pictures(box, text)
    assert len(plan.tiles) == tiles, name
    if not tiles:
        assert plan.legible and plan.scale * text >= vp.LEGIBLE * vp.TEXT_PX
        return
    assert not plan.legible, "the overview alone could not be read"
    assert plan.tile_legible is readable and (plan.tile_scale * text >= vp.LEGIBLE * vp.TEXT_PX) is readable
    for t in plan.tiles:  # each tile, margins included, is a picture the model's budget holds
        px = (t[2] - t[0]) * plan.tile_scale + 2 * vp.GUTTER, (t[3] - t[1]) * plan.tile_scale + 2 * vp.GUTTER
        assert max(px) <= vp.MODEL_SIDE + 1e-6 and px[0] * px[1] <= vp.MODEL_AREA * 1.001, (name, px)
    ov = plan.width, (h * plan.scale + 2 * vp.GUTTER)
    assert ov[0] <= vp.MODEL_SIDE and ov[0] * ov[1] <= vp.MODEL_AREA * 1.001, "and so is the overview"


def test_the_tiles_cover_the_box_overlap_by_a_sixth_and_read_top_to_bottom_left_to_right():
    box = (0.0, 0.0, 79_700.0, 19_600.0)
    tiles, _scale = vp.plan_tiles(box, 14.0 / 200.0)
    assert len(tiles) == 6 and min(t[0] for t in tiles) == 0 and max(t[2] for t in tiles) == pytest.approx(79_700.0)
    assert min(t[1] for t in tiles) == pytest.approx(0) and max(t[3] for t in tiles) == pytest.approx(19_600.0)
    for a, b in pairwise(tiles):
        assert a[0] < b[0] and (a[2] - b[0]) / (a[2] - a[0]) == pytest.approx(vp.OVERLAP, abs=1e-6), "a feature on an edge is whole in one of the two"
    grid, _ = vp.plan_tiles((0, 0, 30_000.0, 30_000.0), 14.0 / 250.0)  # a square with small text needs both ways
    assert len(grid) == 4 and grid[0][1] > grid[2][1] and grid[0][0] < grid[1][0], "top row first, each row left to right"
    top, bottom = grid[0], grid[2]  # the rows overlap too: what lies on the seam between them is whole in one of the two
    assert (bottom[3] - top[1]) / (bottom[3] - bottom[1]) == pytest.approx(vp.OVERLAP, abs=1e-6)


def test_more_than_the_limit_is_the_most_tiles_allowed_at_the_finest_scale_that_can_be_had_and_it_says_so():
    plan = vp.plan_pictures((0, 0, 400_000.0, 20_000.0), 250.0)
    assert len(plan.tiles) == vp.TILE_MAX and not plan.tile_legible
    assert plan.tile_scale * 250.0 < vp.LEGIBLE * vp.TEXT_PX
    box = (0, 0, 80_000.0, 17_000.0)
    assert len(vp.plan_pictures(box, 200.0).tiles) == 5 and vp.plan_pictures((0, 0, 89_000.0, 29_000.0), 200.0).tile_scale < vp.plan_pictures(box, 200.0).tile_scale, \
        "the same unit cropped to what is drawn gets a finer scale: blank space costs pixels"


def _cluster(cx: float, cy: float, n: int = 8, spread: float = 2_500.0) -> list[tuple[float, float]]:
    return [(cx + spread * ((k % 4) - 1.5) / 1.5, cy + spread * ((k // 4) - 0.5)) for k in range(n)]


def _held(tiles, texts) -> float:
    return sum(1 for x, y in texts if any(t[0] <= x <= t[2] and t[1] <= y <= t[3] for t in tiles)) / max(len(texts), 1)


FOUR_PLACES = [pt for c in ((10_000.0, 10_000.0), (50_000.0, 12_000.0), (80_000.0, 30_000.0), (30_000.0, 38_000.0)) for pt in _cluster(*c)]


def test_the_biggest_tile_is_the_one_whose_picture_at_the_ideal_scale_is_just_what_the_model_reads():
    ideal = 14.0 / 250.0
    tw, th = vp.tile_size(ideal)
    assert vp.max_scale(tw, th) == pytest.approx(ideal, rel=1e-6), "no bigger: its picture would be shrunk again, and its text with it"
    assert vp.tile_size(ideal, landscape=False) == (th, tw) and tw > th


def test_tiles_are_placed_where_the_text_is_when_that_reads_it_at_the_ideal_scale_with_no_more_tiles():
    """90 m by 45 m drawn for 1:100 with its notes in four places: a grid of six tiles is too coarse for all of it, but the four places can be read at the ideal scale."""
    box = (0.0, 0.0, 90_000.0, 45_000.0)
    by_extent = vp.plan_pictures(box, 250.0)
    assert not by_extent.placed and not by_extent.tile_legible or by_extent.tile_scale < by_extent.ideal_scale, "by extent alone the limit of six tiles is too coarse"
    plan = vp.plan_pictures(box, 250.0, texts=FOUR_PLACES)
    assert plan.placed and plan.tile_legible and plan.tile_scale == pytest.approx(plan.ideal_scale) and 1 < len(plan.tiles) <= vp.TILE_MAX
    assert _held(plan.tiles, FOUR_PLACES) >= vp.COVER_MIN, "the tiles hold the unit's text"
    assert all(sum(1 for x, y in FOUR_PLACES if t[0] <= x <= t[2] and t[1] <= y <= t[3]) >= 1 for t in plan.tiles), "and none is made for nothing"
    for t in plan.tiles:
        assert box[0] <= t[0] and t[2] <= box[2] and box[1] <= t[1] and t[3] <= box[3] and vp.max_scale(t[2] - t[0], t[3] - t[1]) >= plan.ideal_scale - 1e-9


def test_tiles_read_top_row_first_and_left_to_right():
    tiles, held = vp.cover_tiles((0.0, 0.0, 90_000.0, 45_000.0), FOUR_PLACES, 14.0 / 250.0)
    rows = [round((t[1] + t[3]) / 2 / (0.5 * (tiles[0][3] - tiles[0][1]))) for t in tiles]
    assert held >= vp.COVER_MIN and rows == sorted(rows, reverse=True), "rows from the top"
    for a, b in pairwise(tiles):
        if round((a[1] + a[3]) / 2 / (0.5 * (a[3] - a[1]))) == round((b[1] + b[3]) / 2 / (0.5 * (b[3] - b[1]))):
            assert a[0] <= b[0]
    assert vp.cover_tiles((0.0, 0.0, 90_000.0, 45_000.0), [], 14.0 / 250.0) == ([], 0.0)


def test_text_that_cannot_be_held_by_six_tiles_is_not_given_up_for_the_ideal_scale():
    """Notes spread evenly cannot all be in six tiles of the ideal scale: the tiles are then the grid by extent (coarser, all of the unit), never six
    tiles that hold a third of the text."""
    box = (0.0, 0.0, 90_000.0, 45_000.0)
    for seed in range(5):
        rng = random.Random(seed)
        texts = [(rng.uniform(0, 90_000.0), rng.uniform(0, 45_000.0)) for _ in range(60)]
        plan = vp.plan_pictures(box, 250.0, texts=texts)
        assert (not plan.placed and plan.tiles == vp.plan_tiles(box, plan.ideal_scale)[0]) or _held(plan.tiles, texts) >= vp.COVER_MIN, seed
    assert vp.plan_pictures(box, 250.0, texts=[]).placed is False, "no texts known: the grid by extent"


def test_all_the_text_in_one_place_is_one_close_up_of_that_place():
    box = (0.0, 0.0, 90_000.0, 20_000.0)
    texts = _cluster(20_000.0, 10_000.0, n=12, spread=2_000.0)
    plan = vp.plan_pictures(box, 250.0, texts=texts)
    assert plan.placed and len(plan.tiles) == 1 and plan.tile_legible, "one tile, at the ideal scale"
    assert plan.tiles[0][2] - plan.tiles[0][0] < 0.5 * (box[2] - box[0]) and _held(plan.tiles, texts) == 1.0, "a close-up of where the text is, not the overview again"
    assert vp.plan_pictures((0.0, 0.0, 8_000.0, 6_000.0), 100.0).tiles == [], "text readable as drawn: no tiles"


def test_a_grid_tile_with_next_to_nothing_in_it_is_left_out_and_a_unit_with_no_text_has_no_tile():
    tiles, _ = vp.plan_tiles((0.0, 0.0, 90_000.0, 20_000.0), 14.0 / 250.0)
    texts = _cluster(5_000.0, 10_000.0, n=12)
    kept = vp.with_text(tiles, texts)
    assert kept and len(kept) < len(tiles) and all(t[0] < 20_000.0 for t in kept)
    assert vp.with_text(tiles, []) == []


def test_the_biggest_scale_a_box_can_have_respects_both_the_side_and_the_area():
    s = vp.max_scale(10_000.0, 10_000.0)
    assert (10_000 * s + 2 * vp.GUTTER) * (10_000 * s + 2 * vp.GUTTER) == pytest.approx(vp.MODEL_AREA, rel=1e-6) or 10_000 * s + 2 * vp.GUTTER == vp.MODEL_SIDE
    wide = vp.max_scale(100_000.0, 500.0)  # a strip: the side limit decides
    assert 100_000 * wide + 2 * vp.GUTTER == pytest.approx(vp.MODEL_SIDE)
    assert vp.picture_width((0, 0, 100.0, 100.0), 50.0) >= 480, "a small box is still a picture"
    assert vp.picture_width((0, 0, 1e9, 1e9), 1.0) <= vp.MODEL_SIDE


def test_set_out_lines_are_scored_by_what_stands_on_them():
    anchor, plain = vp.salience(True, False, 5, 40, 0), vp.salience(False, False, 5, 40, 0)
    assert anchor - plain == 3.0
    assert vp.salience(False, True, 0, 40, 0) == 2.0 and vp.salience(False, False, 40, 40, 0) == 1.5 and vp.salience(False, False, 0, 40, 3) == 3.0
    assert vp.salience(False, False, 0, 0, 0) == 0.0


def lines(n, anchors=(), start=0.0, step=3.0):
    return [vp.Line(f"y{k}", start + k * step, 0.1 * (k % 7), f"y{k}" in anchors) for k in range(n)]


def test_only_as_many_lines_are_labelled_as_fit_and_the_anchors_come_first():
    ls = lines(120, anchors={"y3", "y50", "y99"})
    keep, bands = vp.admit(ls, span_px=1000.0)
    assert len(keep) <= 1000 // 22 and {"y3", "y50", "y99"} <= {x.id for x in keep}
    assert [x.pos for x in keep] == sorted(x.pos for x in keep)
    assert all(b.count >= 3 for b in bands) and sum(b.count for b in bands) <= 120 - len(keep)
    assert all(abs(a.pos - b.pos) >= 2.0 for a, b in pairwise(keep))
    # more anchors than room: the best anchors, and still no more labels than fit — a label that does not fit is a label on top of another
    many = [vp.Line(f"y{k}", 10.0 + k * 12.0, float(k), True) for k in range(60)]
    keep, _bands = vp.admit(many, span_px=440.0)
    assert len(keep) == 20 and {x.id for x in keep} == {f"y{k}" for k in range(40, 60)}, "the 20 highest-scoring anchors"
    assert len(vp.admit(lines(200), span_px=1000.0, min_gap=44.0)[0]) <= 22, "an overview wants fewer, the primary lines"


def test_the_fine_lines_left_out_are_one_band_not_fifty_six_lines():
    ls = [vp.Line(f"y{k}", 100.0 + (k - 21) * 4.0, 0.2, False) for k in range(21, 78)] + [vp.Line("y5", 20.0, 3.0, True), vp.Line("y90", 900.0, 3.0, True)]
    keep, bands = vp.admit(ls, span_px=700.0, min_gap=22.0)
    assert {"y5", "y90"} <= {x.id for x in keep}
    assert bands, "the staircase is a band"
    first = bands[0]
    assert first.label == f"{first.first}..{first.last} ({first.count} lines — zoom)" and first.count >= 3
    assert vp.admit([vp.Line("y1", 5.0, 1.0, False), vp.Line("y2", 6.0, 1.0, False)], 100.0)[1] == [], "two lines are not a band"


def test_pool_adjacent_violators_is_the_monotone_sequence_nearest_to_the_input():
    assert vp.pava([1, 2, 3]) == [1, 2, 3]
    assert vp.pava([3, 1]) == [2, 2] and vp.pava([1, 3, 2, 4]) == [1, 2.5, 2.5, 4] and vp.pava([]) == []
    rng = random.Random(7)
    for _ in range(200):
        z = [rng.uniform(-50, 50) for _ in range(rng.randint(1, 30))]
        y = vp.pava(z)
        assert all(a <= b + 1e-9 for a, b in pairwise(y))
        assert sse(y, z) <= sse(sorted(z), z) + 1e-9, "nearer than the plain sorted sequence"


def sse(a, b) -> float:
    return sum((p - q) ** 2 for p, q in zip(a, b, strict=True))


def gaps_ok(x, widths, gap):
    return all(b - a >= (widths[i] + widths[i + 1]) / 2 + gap - 1e-9 for i, (a, b) in enumerate(pairwise(x)))


def test_labels_are_moved_the_least_that_stops_them_overlapping():
    # already apart: they stay where they are
    assert vp.pack_labels([50, 150, 250], [30, 30, 30], 0, 400) == [50, 150, 250]
    # crowded: moved apart, in order, inside the span
    x = vp.pack_labels([100, 101, 102, 103], [40, 40, 40, 40], 0, 400)
    assert gaps_ok(x, [40] * 4, vp.LABEL_GAP) and x == sorted(x) and x[0] >= 20 and x[-1] <= 380
    assert sum(x) / 4 == pytest.approx(101.5, abs=0.01), "spread about where they were, not shoved aside"
    # against a wall: still inside
    x = vp.pack_labels([2, 3, 4], [40, 40, 40], 0, 400)
    assert x[0] >= 20 - 1e-9 and gaps_ok(x, [40] * 3, vp.LABEL_GAP)
    x = vp.pack_labels([398, 399, 400], [40, 40, 40], 0, 400)
    assert x[-1] <= 380 + 1e-9 and gaps_ok(x, [40] * 3, vp.LABEL_GAP)
    # more than fits: evenly spread, in order
    x = vp.pack_labels([10] * 30, [40] * 30, 0, 400)
    assert x == sorted(x) and x[0] >= 20 - 1e-9 and x[-1] <= 380 + 1e-9
    assert vp.pack_labels([], [], 0, 10) == [] and vp.pack_labels([5.0], [10.0], 0, 100) == [5.0] or vp.pack_labels([5.0], [10.0], 0, 100) == [5.0 + 0.0]


def test_no_two_labels_ever_overlap_whatever_the_crowd_and_the_packing_is_never_worse_than_pushing_to_the_right():
    rng = random.Random(11)
    for _ in range(300):
        n = rng.randint(2, 25)
        widths = [rng.uniform(14, 44) for _ in range(n)]
        lo, hi = 0.0, 1400.0
        targets = sorted(rng.uniform(lo, hi) for _ in range(n))
        x = vp.pack_labels(targets, widths, lo, hi)
        total = sum(widths) + vp.LABEL_GAP * (n - 1)
        if total <= hi - lo:
            assert gaps_ok(x, widths, vp.LABEL_GAP), (targets, widths, x)
            assert x[0] - widths[0] / 2 >= lo - 1e-6 and x[-1] + widths[-1] / 2 <= hi + 1e-6
            # the naive way: each label as far right as its predecessor needs
            naive = [max(targets[0], lo + widths[0] / 2)]
            for i in range(1, n):
                naive.append(max(targets[i], naive[-1] + (widths[i - 1] + widths[i]) / 2 + vp.LABEL_GAP))
            over = naive[-1] - (hi - widths[-1] / 2)
            if over > 0:
                naive = [v - over for v in naive]
            if gaps_ok(naive, widths, vp.LABEL_GAP) and naive[0] - widths[0] / 2 >= lo - 1e-6:
                assert sse(x, targets) <= sse(naive, targets) + 1e-6
        assert x == sorted(x)


def test_neighbours_go_on_different_tracks():
    assert vp.assign_tracks(9) == [0, 1, 2, 3, 0, 1, 2, 3, 0]
    t = vp.assign_tracks(40)
    assert all(a != b for a, b in pairwise(t)) and vp.assign_tracks(0) == []
