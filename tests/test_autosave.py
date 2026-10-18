"""The work is kept on disk while it is made: a server that is closed or killed loses nothing, a drawing opened again gets its work back, a clean
start keeps the old work aside, and a file that does not read is reported, never dropped."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_sheet import built_sheet

from dxf_autoparam import autosave as keep
from dxf_autoparam.workspace import SheetSession


def session(tmp_path: Path, name: str = "sheet.dxf", every: float = 0.05, dxf: Path | None = None) -> tuple[SheetSession, Path]:
    dxf = dxf or built_sheet(tmp_path / name)
    sheet = SheetSession()
    sheet.autosave = keep.Autosave(sheet, root=tmp_path / "state", every=every)
    sheet.open(str(dxf))
    return sheet, dxf


def wait_for(cond, seconds: float = 5.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_opening_a_drawing_and_doing_nothing_writes_nothing(tmp_path):
    sheet, _dxf = session(tmp_path)
    assert sheet.autosave.flush() is False and sheet.autosave.flush() is False
    assert not (tmp_path / "state").exists() or not list((tmp_path / "state").glob("*.json"))
    assert sheet.summary()["autosave"]["restored"] is None


def test_a_change_is_written_even_when_it_does_not_bump_the_revision_and_a_new_session_gets_it_back(tmp_path):
    sheet, dxf = session(tmp_path)
    rev0 = sheet.sm.revision
    sheet.set_prefs({"baseline": {"on": False, "color": "#112233"}})  # saved with the project, but no undoable step
    assert sheet.sm.revision == rev0
    assert sheet.autosave.flush() is True
    sheet.sm.set_plan({"summary": "the clear span follows the box"})  # an undoable step: the revision moves
    assert sheet.autosave.flush() is True and sheet.autosave.flush() is False, "written once per change, not on every look"
    path = keep.project_path(str(dxf), tmp_path / "state")
    saved = json.loads(path.read_text())
    assert saved["revision"] == sheet.sm.revision > rev0 and saved["plan"]["summary"] == "the clear span follows the box"

    # the server is closed; the same drawing is served again
    again = SheetSession()
    again.autosave = keep.Autosave(again, root=tmp_path / "state")
    again.open(str(dxf))
    assert again.sm.revision == sheet.sm.revision, "the page shows the revision it showed"
    assert again.sm.stated_plan == {"summary": "the clear span follows the box"}
    assert again.sm.prefs["baseline"]["color"] == "#112233" and again.sm.prefs["baseline"]["on"] is False
    info = again.summary()["autosave"]
    assert info["restored"]["from"] == "the autosave" and info["restored"]["revision"] == sheet.sm.revision and info["error"] is None
    assert again.autosave.flush() is False, "what was opened is the baseline: no write until something changes"


def test_the_thread_saves_what_changed_and_stop_writes_the_last_second(tmp_path):
    sheet, dxf = session(tmp_path, every=0.05)
    sheet.autosave.start()
    path = keep.project_path(str(dxf), tmp_path / "state")
    sheet.sm.set_plan({"summary": "one"})
    assert wait_for(path.exists), "the thread wrote it without being asked"
    sheet.autosave.every = 3600  # no more looks: only stop() can write the next change
    sheet.sm.set_plan({"summary": "two"})
    sheet.autosave.stop()
    assert json.loads(path.read_text())["plan"]["summary"] == "two"


def test_a_clean_start_keeps_the_old_work_aside_under_a_dated_name(tmp_path):
    sheet, dxf = session(tmp_path)
    sheet.sm.set_plan({"summary": "work that took an hour"})
    sheet.autosave.flush()
    path = keep.project_path(str(dxf), tmp_path / "state")
    fresh = SheetSession()
    fresh.autosave = keep.Autosave(fresh, root=tmp_path / "state")
    fresh.open(str(dxf), fresh=True)
    assert fresh.sm.stated_plan == {} and not path.exists()
    kept = list((tmp_path / "state").glob("*.replaced.json"))
    assert len(kept) == 1 and json.loads(kept[0].read_text())["plan"]["summary"] == "work that took an hour"
    assert fresh.summary()["autosave"]["restored"] is None
    assert fresh.autosave.flush() is False, "the clean start is the baseline too: the old work is not overwritten by it"


def test_the_same_drawing_is_the_same_work_wherever_it_sits_and_an_edited_drawing_is_another(tmp_path):
    a = built_sheet(tmp_path / "one.dxf")
    b = tmp_path / "elsewhere" / "one.dxf"
    b.parent.mkdir()
    b.write_bytes(a.read_bytes())
    assert keep.project_path(str(a), tmp_path) == keep.project_path(str(b), tmp_path)
    c = tmp_path / "edited.dxf"
    c.write_bytes(a.read_bytes() + b"\n")
    assert keep.drawing_key(str(c)).split("-")[-1] != keep.drawing_key(str(a)).split("-")[-1]
    odd = tmp_path / "20A (7).dxf"
    odd.write_bytes(a.read_bytes())
    assert " " not in keep.project_path(str(odd), tmp_path).name and "(" not in keep.project_path(str(odd), tmp_path).name


def test_a_file_that_does_not_read_is_reported_and_kept_and_the_previous_one_is_used(tmp_path):
    sheet, dxf = session(tmp_path)
    path = keep.project_path(str(dxf), tmp_path / "state")
    sheet.sm.set_plan({"summary": "good"})
    sheet.autosave.flush()
    path.write_text("{ this is not json")  # a disk problem, an editor, a copy that stopped half way
    assert keep.restore(str(dxf), tmp_path / "state")[0] is None
    assert not path.exists() and path.with_name(path.name.removesuffix(".json") + ".unreadable.json").exists(), "kept aside, not deleted"

    # with a good previous generation, that one opens and the problem is said
    sheet2, dxf2 = session(tmp_path, "other.dxf")
    p2 = keep.project_path(str(dxf2), tmp_path / "state")
    sheet2.sm.set_plan({"summary": "older"})
    sheet2.autosave.flush()
    p2.replace(keep.prev_of(p2))
    p2.write_text("not json either")
    sm, info = keep.restore(str(dxf2), tmp_path / "state")
    assert sm is not None and sm.stated_plan == {"summary": "older"} and info["from"] == "the previous autosave"
    assert info["problems"] and p2.name in info["problems"][0]


def test_a_write_cannot_leave_half_a_file_and_the_generation_before_is_kept_when_it_is_old(tmp_path, monkeypatch):
    path = tmp_path / "p.autoparam.json"
    keep.write_atomic(path, '{"n": 1}')
    assert not keep.prev_of(path).exists(), "a file a second old is not a state to go back to"
    old = time.time() - 3600
    os.utime(path, (old, old))
    keep.write_atomic(path, '{"n": 2}')
    assert json.loads(path.read_text()) == {"n": 2} and json.loads(keep.prev_of(path).read_text()) == {"n": 1}

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(keep.os, "replace", boom)
    with pytest.raises(OSError):
        keep.write_atomic(path, '{"n": 3}')
    assert json.loads(path.read_text()) == {"n": 2}, "the file in place is whole"
    assert not [f for f in tmp_path.iterdir() if f.name.endswith(".tmp")], "no temporary file is left behind"


def test_a_failed_save_is_shown_not_fatal(tmp_path, monkeypatch):
    sheet, _dxf = session(tmp_path)
    sheet.sm.set_plan({"summary": "x"})

    def boom(path, text):
        raise OSError("read-only file system")

    monkeypatch.setattr(keep, "write_atomic", boom)
    assert sheet.autosave.flush() is False
    assert "read-only file system" in sheet.summary()["autosave"]["error"]
    monkeypatch.undo()
    assert sheet.autosave.flush() is True and sheet.summary()["autosave"]["error"] is None, "tried again, and the error is gone"


def test_the_project_format_keeps_the_revision_and_still_opens_files_saved_without_one(tmp_path):
    sheet, dxf = session(tmp_path)
    sheet.sm.set_plan({"summary": "a"})
    sheet.sm.set_plan({"summary": "b"})
    project = tmp_path / "p.autoparam.json"
    sheet.sm.save(str(project))
    from dxf_autoparam.crossview import SheetModel

    assert SheetModel.load(str(project), dxf=str(dxf)).revision == sheet.sm.revision
    d = json.loads(project.read_text())
    d.pop("revision")
    project.write_text(json.dumps(d))
    assert SheetModel.load(str(project), dxf=str(dxf)).revision == 0, "a file from before the revision was kept"


def _server_child(dxf, state, hup: str) -> subprocess.Popen:
    """A real server process with SIGHUP set to `hup` (SIG_DFL, or SIG_IGN as under nohup) whose first edit happens inside it and is never looked at by
    the autosave thread again — so only the shutdown can save it. Returns once it has said where it listens."""
    code = (
        "import signal\n"
        f"signal.signal(signal.SIGHUP, signal.{hup})  # a test run under nohup hands its children an ignored SIGHUP: each test says which it is about\n"
        "from dxf_autoparam import server\n"
        "from dxf_autoparam.workspace import SheetSession\n"
        "orig = SheetSession.open\n"
        "def opened(self, *a, **k):\n"
        "    r = orig(self, *a, **k)\n"
        "    self.sm.set_plan({'summary': 'made just before the terminal closed'})\n"
        "    self.autosave.every = 3600  # the thread will not look again: only the shutdown can save it\n"
        "    return r\n"
        "SheetSession.open = opened\n"
        f"server.serve({str(dxf)!r}, port=0, state_dir={str(state)!r})\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    line = ""
    end = time.time() + 60
    while time.time() < end and "dxf-autoparam on http" not in line:
        line = proc.stdout.readline()
        assert line or proc.poll() is None, "the server ended before it was ready"
    assert "dxf-autoparam on http" in line, "the server did not come up"
    return proc


def _ends_within(proc: subprocess.Popen, sig: signal.Signals, seconds: float = 30) -> None:
    proc.send_signal(sig)
    try:
        proc.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail(f"the server did not end within {seconds:g} s of {sig.name}; what it said:\n{proc.communicate(timeout=10)[0][-1500:]}")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_closing_the_terminal_or_killing_the_server_saves_the_work_first(tmp_path):
    """The case that lost a 62-minute run: the server's terminal was closed. A real server process, a real SIGHUP / SIGTERM."""
    dxf = built_sheet(tmp_path / "sheet.dxf")
    state = tmp_path / "state"
    for sig in (signal.SIGHUP, signal.SIGTERM):
        proc = _server_child(dxf, state, "SIG_DFL")
        try:
            _ends_within(proc, sig)
        finally:
            if proc.poll() is None:
                proc.kill()
        path = keep.project_path(str(dxf), state)
        assert path.exists(), f"{sig.name}: the work was not saved"
        assert json.loads(path.read_text())["plan"]["summary"] == "made just before the terminal closed"
        path.unlink()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_a_server_left_running_with_nohup_outlives_its_terminal_and_still_saves_when_it_is_killed(tmp_path):
    """`nohup` is how a server is meant to be left running: SIGHUP stays ignored (the terminal closing must not end it); a later `kill` still saves first."""
    dxf = built_sheet(tmp_path / "sheet.dxf")
    state = tmp_path / "state"
    proc = _server_child(dxf, state, "SIG_IGN")
    try:
        proc.send_signal(signal.SIGHUP)
        time.sleep(1.5)
        assert proc.poll() is None, "a server started with SIGHUP ignored ended when its terminal closed"
        _ends_within(proc, signal.SIGTERM)
    finally:
        if proc.poll() is None:
            proc.kill()
    path = keep.project_path(str(dxf), state)
    assert path.exists() and json.loads(path.read_text())["plan"]["summary"] == "made just before the terminal closed"
