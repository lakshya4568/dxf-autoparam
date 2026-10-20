"""The work is kept on disk while it is made, so a server that is closed, killed or crashes loses nothing.

The sheet's parametric project — what a person or the AI decided: parts, sizes, shared values, plans, notes (`SheetModel.to_dict`) — is written to a
state folder whenever it changes, under a name made of the drawing's name and its content hash, and `serve` opens it again when the same drawing is
served. The folder is `$DXF_AUTOPARAM_STATE`, else `$XDG_STATE_HOME/dxf-autoparam`, else `~/.local/state/dxf-autoparam`.

A write goes to a temporary file in the same folder and is renamed over the old one, so a crash cannot leave half a file; the generation before it is
kept as `<name>.prev.json` (when the file is more than a minute old, so it is a state to go back to, not the last second's). A file that does not
read is reported and kept aside (`.unreadable`), never silently dropped or written over. Opening a drawing and doing nothing writes nothing.

One server keeps one drawing's work: when it first writes, it says so in `<name>.owner.json` (its process and port). A second server on the same
drawing finds a live owner, reads the work (it may open it) and writes nothing, and says so — two servers used to save over each other and whichever
wrote last won in silence. An owner that is gone (its process ended, or its port no longer answers) is replaced. Nothing is written before the first change.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .crossview import SheetModel

if TYPE_CHECKING:
    from .workspace import SheetSession

STATE_ENV = "DXF_AUTOPARAM_STATE"
EVERY_S = 1.5  # how often the open sheet is looked at (a look costs a couple of milliseconds)
PREV_AFTER_S = 60.0  # the previous generation is kept only from a file older than this


def state_dir() -> Path:
    root = os.environ.get(STATE_ENV)
    if root:
        return Path(root).expanduser()
    base = os.environ.get("XDG_STATE_HOME")
    return (Path(base).expanduser() if base else Path.home() / ".local" / "state") / "dxf-autoparam"


def drawing_key(dxf: str) -> str:
    """The drawing's name and content hash: the same drawing, wherever it sits, is the same work; an edited drawing is another."""
    p = Path(dxf)
    return f"{re.sub(r'[^A-Za-z0-9._-]+', '_', p.stem)}-{hashlib.sha256(p.read_bytes()).hexdigest()[:16]}"


def project_path(dxf: str, root: Path | None = None) -> Path:
    return (root or state_dir()) / f"{drawing_key(dxf)}.autoparam.json"


def prev_of(path: Path) -> Path:
    return path.with_name(path.name.removesuffix(".json") + ".prev.json")


def owner_path(path: Path) -> Path:
    return path.with_name(path.name.removesuffix(".json") + ".owner.json")


def owner_alive(owner: dict) -> bool:
    """Whether the server an owner file names is still there: its process exists and, when it said its port, that port still answers (a process
    number is reused; the owner is the one still serving its port). A server that is this process is not another server."""
    try:
        pid = int(owner.get("pid") or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass  # a process of someone else: it exists
    port = owner.get("port")
    if port:
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=0.3):
                return True
        except (OSError, ValueError):
            return False
    return True


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if path.exists() and time.time() - path.stat().st_mtime > PREV_AFTER_S:
            shutil.copy2(path, prev_of(path))
        os.replace(tmp, path)
    except BaseException:  # the temporary file never outlives a failed write; the error goes on to the caller
        Path(tmp).unlink(missing_ok=True)
        raise


def restore(dxf: str, root: Path | None = None) -> tuple[SheetModel | None, dict]:
    """The work saved for this drawing, if there is any: (the model, what happened). A file that does not read is set aside and said so."""
    path = project_path(dxf, root)
    problems: list[str] = []
    for candidate, label in ((path, "the autosave"), (prev_of(path), "the previous autosave")):
        if not candidate.exists():
            continue
        try:
            sm = SheetModel.load(str(candidate), dxf=dxf)
        except Exception as exc:  # noqa: BLE001 — a saved file that does not read is reported and kept, never fatal to starting
            problems.append(f"{candidate.name}: {type(exc).__name__}: {exc}")
            continue
        return sm, {"path": str(candidate), "from": label, "revision": sm.revision, "saved_at": candidate.stat().st_mtime, "problems": problems}
    if problems and path.exists():
        path.replace(path.with_name(path.name.removesuffix(".json") + ".unreadable.json"))
    return None, {"problems": problems}


def set_aside(dxf: str, root: Path | None = None) -> Path | None:
    """Start over on purpose: the saved work for this drawing is kept under a dated name, so nothing a person did is lost by asking for a clean start."""
    path = project_path(dxf, root)
    if not path.exists():
        return None
    kept = path.with_name(path.name.removesuffix(".json") + time.strftime(".%Y%m%d-%H%M%S") + ".replaced.json")
    path.replace(kept)
    return kept


class Autosave:
    """Writes the open sheet's project to the state folder whenever it changes (a thread looks every `every` seconds; `flush` writes at once)."""

    def __init__(self, sheet: SheetSession, root: Path | None = None, every: float = EVERY_S):
        self.sheet, self.root, self.every = sheet, root, every
        self.path: Path | None = None
        self.saved_at: float | None = None
        self.saved_revision: int | None = None
        self.error: str | None = None
        self.restored: dict | None = None  # what was opened from the state folder (None: a drawing that had no saved work, or a clean start)
        self.port: int | None = None  # where this server answers (said by announce, once it is bound)
        self.foreign: dict | None = None  # another live server that keeps this drawing's work: nothing is written from here while it does
        self._owned: Path | None = None  # the owner file this server wrote
        self._seen: dict[str, str] = {}  # per file: the project text last written, or the baseline it was opened as (no change, nothing to write)
        self._io = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> Autosave:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="autosave")
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.flush()
        self._release()

    def touch(self) -> None:
        """The sheet differs from what is on disk although nobody changed it (the engine worked something out for saved work when it was opened): it is
        written at the next look, so the next opening has it and does not work it out again."""
        with self._io:
            if self.path is not None:
                self._seen.pop(str(self.path), None)

    def announce(self, port: int) -> None:
        """The port this server answers on, once it is bound: it goes into the owner file, so another server can tell this one is alive."""
        self.port = port
        if self._owned is not None:
            self._write_owner(self._owned)

    def _write_owner(self, file: Path) -> None:
        file.write_text(json.dumps({"pid": os.getpid(), "port": self.port, "started": time.time()}))
        self._owned = file

    @staticmethod
    def _owner_of(path: Path) -> dict | None:
        try:
            owner = json.loads(owner_path(path).read_text())
        except (OSError, ValueError):
            return None  # no owner file, or one that does not read: nobody keeps it
        return owner if isinstance(owner, dict) and owner_alive(owner) else None

    def _look(self, path: Path) -> None:
        """A drawing was opened: is its work kept by another live server? Nothing is written."""
        self._release()  # a drawing opened before was this server's
        self.foreign = self._owner_of(path)

    def _keep(self, path: Path) -> bool:
        """About to write: this server keeps the drawing's work (True), or another live server does (False)."""
        if self._owned == owner_path(path) and self.foreign is None:
            return True
        self._release()
        self.foreign = self._owner_of(path)
        if self.foreign is not None:
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._write_owner(owner_path(path))
        except OSError as exc:  # a folder that cannot be written is the save's own failure to report, not this one's
            self.error = f"{type(exc).__name__}: {exc}"
        return True

    def _release(self) -> None:
        """Let go of the drawing's work (the owner file goes only if it is still this server's)."""
        file, self._owned = self._owned, None
        if file is None:
            return
        try:
            if json.loads(file.read_text()).get("pid") == os.getpid():
                file.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass  # gone or not ours: nothing of this server's to remove

    def _foreign_text(self) -> str | None:
        f = self.foreign
        if f is None:
            return None
        where = f"pid {f.get('pid')}" + (f", port {f['port']}" if f.get("port") else "")
        return f"another server ({where}) keeps this drawing's saved work: this one does not write it, so it cannot overwrite it"

    def _loop(self) -> None:
        while not self._stop.wait(self.every):
            self.flush()

    def rebase(self) -> None:
        """The sheet as it was just opened (or opened from saved work) is the baseline: opening a drawing and doing nothing writes nothing. Taken
        when the sheet is opened, not at the first look, so a change made in the first second is a change."""
        with self.sheet.lock, self._io:  # the sheet first, then the file: see flush
            sm = self.sheet.sm
            if sm is None:
                return
            self.path = project_path(sm.path, self.root)
            self._seen[str(self.path)] = json.dumps(sm.to_dict(), indent=1, default=list)
            self._look(self.path)

    def flush(self) -> bool:
        """Write the project now if it differs from what was last written (or the baseline). True when a file was written.

        The two locks are always taken in this order, the sheet's and then the file's. The page's request that opens a drawing holds the sheet for
        the whole read and calls rebase(); a flush that held the file's lock while it waited for the sheet made the two wait for each other for ever."""
        with self.sheet.lock, self._io:
            try:
                sm = self.sheet.sm
                if sm is None:
                    return False
                path = project_path(sm.path, self.root)
                revision = sm.revision
                text = json.dumps(sm.to_dict(), indent=1, default=list)
                key = str(path)
                if text == self._seen.get(key):
                    return False
                if not self._keep(path):
                    return False  # another live server keeps this drawing's work: it is not written over
                write_atomic(path, text)
            except Exception as exc:  # noqa: BLE001 — a failed save is shown in the page and tried again; it must never stop the server
                self.error = f"{type(exc).__name__}: {exc}"
                return False
            self._seen[key] = text
            self.path, self.saved_at, self.saved_revision, self.error = path, time.time(), revision, None
            return True

    def status(self) -> dict:
        sm = self.sheet.sm
        return {"path": str(self.path) if self.path else None, "saved_at": self.saved_at, "saved_revision": self.saved_revision,
                "revision": sm.revision if sm is not None else None, "restored": self.restored, "error": self.error or self._foreign_text(),
                "owner": self.foreign}
