"""Engine tests: exactness, intent recovery against independently drawn variants, DXF round
trip, the generic/domain boundary, and a guard that no structure type is coded in the engine."""

from __future__ import annotations

import ast
import re
import importlib.util
from pathlib import Path

import ezdxf
import pytest

from dxf_autoparam import autoparametrize, regenerate, validate
from dxf_autoparam.dxf_read import read_dxf
from dxf_autoparam.dxf_write import audit, write_dxf
from dxf_autoparam.ir import Role

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((ROOT / "examples").glob("*.dxf"))

_spec = importlib.util.spec_from_file_location("make_examples", ROOT / "tools" / "make_examples.py")
make_examples = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_examples)


def structural_points(path: str) -> list[tuple[float, float]]:
    dr, _ = read_dxf(path)
    return [it.pts[k] for it in dr.items if it.role == Role.STRUCTURAL for k in it.vertex_pts]


def model_points(model, reg) -> list[tuple[float, float]]:
    return [reg.pts[it.index][k] for it in model.analysis.drawing.items if it.role == Role.STRUCTURAL for k in it.vertex_pts]


def same_shape(a, b, tol=1.0) -> bool:
    """Equal point sets up to the translation that pins the bounding-box centre / corners."""

    def bb(p):
        return min(x for x, _ in p), min(y for _, y in p), max(x for x, _ in p), max(y for _, y in p)

    A, B = bb(a), bb(b)
    for fx in (0.0, 0.5, 1.0):
        for fy in (0.0, 0.5, 1.0):
            dx = (A[0] + fx * (A[2] - A[0])) - (B[0] + fx * (B[2] - B[0]))
            dy = (A[1] + fy * (A[3] - A[1])) - (B[1] + fy * (B[3] - B[1]))
            moved = [(x + dx, y + dy) for x, y in b]
            if all(any(abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol for q in moved) for p in a) and all(
                any(abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol for q in a) for p in moved
            ):
                return True
    return False


# ── exactness ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_regenerating_at_the_defaults_reproduces_the_drawing_exactly(path):
    model = autoparametrize(str(path))
    v = validate(model)
    assert v["identity_max_error"] < 1e-6
    assert v["parameters"] > 0


# ── intent recovery against independently drawn variants ──────────────────────

BASE = dict(cells=3, span=2500, height=2000, wall=300, mid=250, top=300, base=350, haunch=150, pcc=150, proj=150)


@pytest.mark.parametrize(
    "change",
    [{"span": 3500}, {"height": 2600}, {"wall": 400}, {"mid": 350}, {"top": 450}, {"base": 500}, {"haunch": 250}, {"proj": 300}],
    ids=lambda c: next(iter(c)),
)
def test_one_inferred_value_reproduces_each_design_change(tmp_path, change):
    src = tmp_path / "base.dxf"
    make_examples.three_cell_box(src, **BASE)
    target = tmp_path / "target.dxf"
    make_examples.three_cell_box(target, **{**BASE, **change})
    model = autoparametrize(str(src))
    key, new = next(iter(change.items()))
    delta = new - BASE[key]
    want = structural_points(str(target))
    hits = [
        p.name
        for p in model.parameters.values()
        if p.kind not in ("level", "position")
        and not regenerate(model, {p.name: p.value + delta}).issues
        and same_shape(want, model_points(model, regenerate(model, {p.name: p.value + delta})))
    ]
    assert hits, f"no single inferred value reproduces {key} {BASE[key]} → {new}"


@pytest.mark.parametrize("cells", [1, 2, 3, 4])
def test_repeated_cells_share_one_span_and_the_overall_is_worked_out(tmp_path, cells):
    src = tmp_path / f"box{cells}.dxf"
    make_examples.three_cell_box(src, **{**BASE, "cells": cells})
    model = autoparametrize(str(src))
    spans = [p for p in model.parameters.values() if abs(p.value - BASE["span"]) < 0.5]
    assert len(spans) == 1 and spans[0].occurrences == cells
    overall = [r for r in model.results if r.dimensioned and abs(r.value - (2 * BASE["wall"] + cells * BASE["span"] + (cells - 1) * BASE["mid"])) < 0.5]
    assert overall and overall[0].form.terms.get(spans[0].name) == cells


def test_an_edit_that_breaks_the_drawing_is_reported_not_applied(tmp_path):
    src = tmp_path / "box.dxf"
    make_examples.three_cell_box(src, **BASE)
    model = autoparametrize(str(src))
    leg = next(p for p in model.parameters.values() if p.kind == "leg")
    bad = regenerate(model, {leg.name: 5000})  # a chamfer longer than the opening
    assert bad.issues


# ── DXF round trip ─────────────────────────────────────────────────────────────


def test_written_dxf_is_clean_and_reads_back_as_the_same_model(tmp_path):
    src = tmp_path / "box.dxf"
    make_examples.three_cell_box(src, **BASE)
    model = autoparametrize(str(src))
    span = next(p for p in model.parameters.values() if abs(p.value - BASE["span"]) < 0.5)
    out = tmp_path / "out.dxf"
    rep = write_dxf(model, regenerate(model, {span.name: 3200}), str(out))
    assert rep["dimensions_rendered"] > 0
    a = audit(str(out))
    assert a["errors"] == 0
    assert len(ezdxf.readfile(src).modelspace()) == len(ezdxf.readfile(out).modelspace())
    again = autoparametrize(str(out))
    assert any(abs(p.value - 3200) < 0.5 and p.occurrences == BASE["cells"] for p in again.parameters.values())
    texts = [e.dxf.text for e in ezdxf.readfile(out).modelspace().query("TEXT")]
    assert any("3.200" in t for t in texts), texts  # the note stating the span follows it


# ── generic engine, optional domain ───────────────────────────────────────────


def test_the_domain_pack_only_names_and_pins():
    path = str(ROOT / "examples" / "rcc_box_half_section_half_elevation.dxf")
    from dxf_autoparam.analyse import analyse
    from dxf_autoparam.domains import PACKS

    dr, _ = read_dxf(path)
    dec = PACKS["bridge"](analyse(dr))
    assert not dec.accept and not dec.reject and not dec.anchor
    assert dec.pin  # stated site levels found
    plain = autoparametrize(path)
    with_pack = autoparametrize(path, domain="bridge")
    assert validate(plain)["identity_max_error"] < 1e-6
    assert validate(with_pack)["identity_max_error"] < 1e-6


ENGINE = ["ir.py", "dxf_read.py", "analyse.py", "build.py", "regen.py", "dxf_write.py", "views.py", "pipeline.py"]
STRUCTURE_WORDS = ["culvert", "girder", "slab", "pier", "abutment", "haunch", "rcc", "psc", "bridge", "wing", "deck",
                   "kerb", "ballast", "rail", "formation", "hfl", "cushion", "footing", "pile", "well", "box", "barrel"]


@pytest.mark.parametrize("module", ENGINE)
def test_no_structure_type_is_coded_in_the_engine(module):
    """Identifiers and string literals of the generic engine carry no structure vocabulary
    (comments and docstrings may use examples; code may not)."""
    tree = ast.parse((ROOT / "src" / "dxf_autoparam" / module).read_text())
    docstrings = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
                  and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    found = []
    for n in ast.walk(tree):
        words = []
        if isinstance(n, ast.Name):
            words = [n.id]
        elif isinstance(n, ast.Attribute):
            words = [n.attr]
        elif isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            words = [n.name]
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
            words = [n.value]
        for w in words:
            # whole words of identifiers and strings: snake_case, camelCase and prose
            tokens = {t.lower().rstrip("s") for t in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", w)}
            found += [s for s in STRUCTURE_WORDS if s in tokens]
    assert not found, f"{module} mentions {sorted(set(found))}"


# ── real drawings, when present ───────────────────────────────────────────────

REAL = [ROOT.parent / "aagento-bridge/public/test-fixtures/dxf/mib173.dxf", ROOT.parent / "final-output/claude-gad/final.dxf"]


@pytest.mark.parametrize("path", REAL, ids=[p.name for p in REAL])
def test_real_drawings_parametrize_exactly_and_write_cleanly(tmp_path, path):
    if not path.exists():
        pytest.skip("fixture not on this machine")
    model = autoparametrize(str(path), domain="bridge")
    v = validate(model)
    assert v["identity_max_error"] < 1e-6
    assert v["regenerate_ok"] >= 0.8 * v["parameters"]
    top = max(model.parameters.values(), key=lambda p: p.affects)
    out = tmp_path / "regen.dxf"
    write_dxf(model, regenerate(model, {top.name: top.value * 1.05}, check=False), str(out))
    assert audit(str(out))["errors"] == 0


def test_library_families_benchmark_floor():
    """Intent recovery on the 17 library families must not regress (measured 69/177 shape, 59 strict)."""
    from dxf_autoparam.bench import run

    fixtures = ROOT / "fixtures" / "library"
    if not fixtures.exists():
        pytest.skip("library fixtures not generated")
    r = run(fixtures, verbose=False, only="section")
    assert sum(x.identity_error < 1e-6 for x in r) == len(r)
    by = {x.id: x for x in r}
    assert by["ir.box_culvert.section"].recovered == by["ir.box_culvert.section"].params
    assert by["ir.girder_deck.section"].recovered >= 8
    assert by["ir.retaining_wall.section"].recovered >= 6
