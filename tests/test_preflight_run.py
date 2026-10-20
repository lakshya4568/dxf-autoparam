"""tools/preflight_run.py: the checks before a paid run — a server that is down or older than the code on disk, a drawing that is not open, an autosave that
is not safe, credentials that do not work — each stops the run; a copy of the saved work and the code state are kept."""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_sheet import built_sheet
from test_workspace_api import _InProcessServer, _start_server

from dxf_autoparam import autosave as keep
from dxf_autoparam.workspace import SheetSession

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("preflight_run", ROOT / "tools" / "preflight_run.py")
pf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pf)


@pytest.fixture(autouse=True)
def quiet_machine(monkeypatch):
    """No gcloud, no model: the checks that need them are made to answer."""
    monkeypatch.setattr(pf, "adc_ok", lambda: (True, ""))
    monkeypatch.setattr(pf, "vertex_config", lambda: SimpleNamespace(model="test-model", thinking="high", fallback_model="test-fallback", fallback_thinking="high", explicit_cache=True))
    pf.LINES.clear()


def served(tmp_path):
    sheet = SheetSession()
    sheet.autosave = keep.Autosave(sheet, root=tmp_path / "state", every=60)
    sheet.open(str(built_sheet(tmp_path / "sheet.dxf")))
    base, httpd = _start_server(sheet)
    if isinstance(base, _InProcessServer):
        pytest.skip("sockets are blocked here")
    return sheet, base, httpd


def levels(capsys) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in capsys.readouterr().out.splitlines():
        out.setdefault(line.split()[0], []).append(line)
    return out


def test_a_ready_server_passes_and_the_run_is_given_a_copy_of_the_saved_work_and_the_code_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pf, "newest_source_mtime", lambda: 0.0)
    sheet, base, httpd = served(tmp_path)
    try:
        sheet.sm.set_plan({"summary": "work that is saved"})
        assert sheet.autosave.flush() is True
        keep_dir = tmp_path / "run"
        assert pf.main(["--url", base, "--save", str(keep_dir)]) == 0
        out = levels(capsys)
        assert "FAIL" not in out and any("runs the code on disk" in ln for ln in out["PASS"])
        assert any("copied" in ln for ln in out["PASS"]) and (keep_dir / "before.autoparam.json").exists()
        assert any("model test-model" in ln for ln in out["PASS"]) and any("has no price" in ln for ln in out["WARN"])
        assert (keep_dir / "preflight.txt").read_text().count("PASS") >= 5 and (keep_dir / "code-state.txt").read_text().startswith("branch ")
    finally:
        httpd.shutdown()


def test_a_server_older_than_the_code_or_no_server_or_no_credentials_stops_the_run(tmp_path, monkeypatch, capsys):
    _sheet, base, httpd = served(tmp_path)
    try:
        monkeypatch.setattr(pf, "newest_source_mtime", lambda: time.time() + 100)
        assert pf.main(["--url", base]) == 1
        assert any("OLDER than the newest source edit" in ln for ln in levels(capsys)["FAIL"])
        pf.LINES.clear()
        monkeypatch.setattr(pf, "newest_source_mtime", lambda: 0.0)
        monkeypatch.setattr(pf, "adc_ok", lambda: (False, "run `gcloud auth application-default login`"))
        assert pf.main(["--url", base]) == 1
        assert any("credentials do not work" in ln for ln in levels(capsys)["FAIL"])
    finally:
        httpd.shutdown()
    pf.LINES.clear()
    assert pf.main(["--url", "http://127.0.0.1:1"]) == 1
    assert any("no server answers" in ln for ln in levels(capsys)["FAIL"])


def test_work_another_server_keeps_is_not_started_on(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pf, "newest_source_mtime", lambda: 0.0)
    sheet, base, httpd = served(tmp_path)
    try:
        sheet.autosave.foreign = {"pid": 1, "port": 8999}
        assert pf.main(["--url", base]) == 1
        assert any("another server keeps this drawing's saved work" in ln for ln in levels(capsys)["FAIL"])
    finally:
        httpd.shutdown()
