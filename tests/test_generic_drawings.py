"""The same properties on every drawing we have — no AI, no rules per drawing. A new drawing that fails here shows a
gap in the engine, fixed once for all drawings (see dxf_autoparam.robustness)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dxf_autoparam.robustness import check_view, views_of

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT.parent / "aagento-bridge" / "public" / "test-fixtures" / "dxf"
PATHS = sorted(ROOT.glob("examples/*.dxf")) + sorted(p for p in FIXTURES.glob("*.dxf") if p.name != "mib173.dxf")  # mib173: 105 s, run by hand
CASES = [(p, r) for p in PATHS for r in views_of(str(p))]


@pytest.mark.parametrize("path, region", CASES, ids=[f"{p.stem}-{i}" for i, (p, _r) in enumerate(CASES)])
def test_every_named_size_drives_or_is_explained_on_any_drawing(path, region, tmp_path):
    row = check_view(str(path), region, 12, str(tmp_path))
    assert row["identity_mm"] < 1e-3
    assert not row["lost"], row["lost"]  # never silently lost
    assert not row["unexplained"], row["unexplained"]
    assert row["breaks_explained"], row["breaks"]
    assert len(row["driving"]) >= row["named"] // 3  # most named sizes drive on their own
    if row.get("export"):
        assert row["export"]["updated"] > 0 and row["export"]["audit_errors"] == 0
