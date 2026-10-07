"""The engine's own drafting rules, whatever the AI says: slopes keep their angle, annotations follow
what they state, levels read from the drawing's own level datum, existing work held only on request."""

from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest
from ezdxf.enums import TextEntityAlignment

from dxf_autoparam.analyse import analyse
from dxf_autoparam.dxf_read import read_dxf
from dxf_autoparam.dxf_write import write_dxf
from dxf_autoparam.regen import regenerate_program
from dxf_autoparam.validator import Report, apply, baseline

ROOT = Path(__file__).resolve().parents[1]
HALF = ROOT / "examples" / "rcc_box_half_section_half_elevation.dxf"


def half():
    dr, _ = read_dxf(str(HALF))
    return analyse(dr)


def test_a_stated_slope_keeps_its_angle_when_the_structure_gets_taller():
    an = half()
    rep = Report()
    prog = baseline(an, rep=rep)
    slopes = {d: e for d, e in prog.formulas.items() if prog.origin.get(d) == "slope"}
    assert slopes, rep.findings
    # the 1V:1.5H wing slope: its toe follows 1.5 × the height it spans
    toe, expr = next((d, e) for d, e in slopes.items() if "1.5" in e)
    near = expr.split()[0]
    ys = [n for n in expr.replace("(", " ").replace(")", " ").split() if n.startswith("y")]
    tall = max((p for p in prog.params.values() if p.kind == "length" and "Y" in p.name), key=lambda p: p.value)
    before = prog.datum_values()
    after = prog.datum_values({tall.name: tall.value + 600})
    u = an.drawing.units_mm
    run = (after[toe] - after[near]) * u
    rise = (after[ys[0]] - after[ys[1]]) * u
    assert run == pytest.approx(1.5 * rise, abs=1e-6)
    assert before != after


def test_changing_a_level_rewrites_its_note_and_the_levels_that_follow():
    an = half()
    stated = {w: d for d, _i, w, _v in an.stated_levels}
    bed = next(d for w, d in stated.items() if "BED" in w)
    ans = {"structure_type": "", "family": "rcc_box", "views": [], "summary": "", "components": [], "parameters": [],
           "datum_formulas": [], "relations": [], "questions": [], "levels": [{"datum": bed, "name": "BedLevel", "role": "site_input"}]}
    prog, rep = apply(an, ans)
    assert not rep.errors()
    r = regenerate_program(prog, {"BedLevel": 97.0})
    texts = [r.texts.get(it.index, it.text) for it in an.drawing.items if it.text]
    assert any("BED LEVEL 97.000" in t for t in texts), texts
    assert any(t.startswith("TOP OF SLAB") and "101.900" in t for t in texts), texts  # follows: 101.000 + 0.900


def test_a_note_stating_a_size_follows_it(tmp_path):
    an = half()
    prog = baseline(an)
    linked = {an.drawing.items[i].text: ls for i, ls in prog.text_links.items()}
    note = next(t for t in linked if "GRANULAR" in t)
    ref = next(r for tok, r, _d in linked[note] if tok == "850")
    r = regenerate_program(prog, {ref: 900})
    assert any("900THK. GRANULAR" in (r.texts.get(it.index) or "") for it in an.drawing.items)
    assert not any("SCALE" in (an.drawing.items[i].text or "") for i in prog.text_links)  # 1:100 is not a size


def test_the_level_datum_is_found_on_a_sheet_drawn_anywhere(tmp_path):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    y0 = 5000.0  # drawn with bed level at y = 5000, not at 96100
    for y, label in ((y0, "BED LEVEL 96.100"), (y0 + 4000, "SOFFIT 100.100"), (y0 + 4400, "TOP OF SLAB 100.500")):
        msp.add_line((0, y), (8000, y))
        msp.add_text(label, height=150).set_placement((-3000, y + 50), align=TextEntityAlignment.BOTTOM_LEFT)
    msp.add_lwpolyline([(1000, y0), (7000, y0), (7000, y0 + 4400), (1000, y0 + 4400)], close=True)
    path = tmp_path / "offset.dxf"
    doc.saveas(path)
    dr, _ = read_dxf(str(path))
    an = analyse(dr)
    assert an.level_offset_mm == pytest.approx(96100 - y0)
    assert len(an.stated_levels) == 3


def test_existing_structures_are_parametric_unless_held(tmp_path):
    an = half()
    big = next(c for c in an.clusters.values() if abs(c.value * an.drawing.units_mm - 10700) < 0.5)  # the clear span
    pair = an.gaps[big.gaps[0]]
    ans = {"structure_type": "", "family": "rcc_box", "views": [], "summary": "", "levels": [], "datum_formulas": [], "relations": [],
           "questions": [], "parameters": [{"name": "ExistingSpan", "label": "", "component": "Old", "kind": "length",
                                            "candidate": big.id, "value": big.value * an.drawing.units_mm}],
           "components": [{"name": "Old", "type": "box", "existing": True, "outlines": [], "datums": [pair.a, pair.b]}]}
    free, _ = apply(an, ans)
    assert "ExistingSpan" in free.params  # parametric by default
    an2 = half()
    held, _rep = apply(an2, ans, hold_existing=True)
    assert "ExistingSpan" not in held.params
    assert held.origin.get(pair.a) == "existing" or held.origin.get(pair.b) == "existing"
    out = tmp_path / "held.dxf"
    write_dxf(held, regenerate_program(held), str(out))
