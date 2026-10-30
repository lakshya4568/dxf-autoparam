"""tools/audit_run.py: how parametric is the work a run left on a sheet — measured on a copy of the saved project, never on a server."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from test_design_intent import box_sheet

# these tests measure the engine within ONE unit made of a section and its plan (conftest.joined_units): local systems, each view its own,
# are test_local_systems.py
pytestmark = pytest.mark.usefixtures("joined_units")

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("audit_run", ROOT / "tools" / "audit_run.py")
audit_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit_run)


def test_the_audit_says_per_unit_what_is_driven_what_stays_as_drawn_and_what_was_decided(tmp_path, capsys):
    sm, uid, g = box_sheet(tmp_path, 2)
    project = tmp_path / "after.autoparam.json"
    sm.save(str(project))
    out = tmp_path / "audit.md"
    assert audit_run.main([g["path"], str(project), "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert text == out.read_text(), "what is printed is what is written"
    assert "## Per unit" in text and f"| {uid} |" in text
    m = re.search(r"\*\*Sheet: (\d+) of (\d+) dimensions are driven by a named value; (\d+) stay as drawn", text)
    assert m and int(m.group(1)) > 0 and int(m.group(1)) + int(m.group(3)) == int(m.group(2))
    assert "Growth direction:" in text and "never derived" not in text, "the box was committed with its design intent"


def test_the_audit_flags_work_whose_intent_was_never_derived_and_a_sweep_finds_no_new_failure_on_a_clean_box(tmp_path, capsys):
    sm, _uid, g = box_sheet(tmp_path, 1, intent=False)
    project = tmp_path / "old.autoparam.json"
    sm.save(str(project))
    assert audit_run.main([g["path"], str(project), "--sweep"]) == 0
    text = capsys.readouterr().out
    assert "(never derived)" in text
    assert "## Sweep: every named length at ±10 %" in text and "introduce failures the sheet does not already have" in text
