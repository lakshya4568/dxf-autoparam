"""The execution boundary: a Node process serving the production `BRIDGE_REGISTRY` over JSON lines.

Python owns the workflow; the production code only answers questions about a production model (compute, validate, levels, views, which
inputs it reads, a headless render). One persistent process serves a whole session (starting the bundle costs ~0.3 s; a request ~1 ms).

Failures are results, never a corrupted drawing: no Node, no bundle, a crash, a timeout or a malformed answer raise `BridgeUnavailable` /
`BridgeError` with the reason, and the callers turn them into an explicit `unavailable` / `error` status. Every answer is checked against
the shape its operation promises before anyone reads it.

    br = default_bridge()
    br.status()                                   # {"available": True, "build": {...}, "families": [...]} or the reason it is not
    br.request("compute", family="railway_rcc_box", model={...})["derived"]
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from .build import BUNDLE, cache_dir, node_binary, read_info

PROTOCOL = 1


class BridgeUnavailable(RuntimeError):
    """The production rules cannot be executed here (no Node, no bundle, disabled): knowledge can still be read, nothing can be evaluated."""


class BridgeError(RuntimeError):
    """The bridge ran but did not answer as promised (a production exception, a timeout, a malformed answer)."""


# what each operation's result must hold (key → type); anything else is a malformed answer
_SHAPES: dict[str, dict[str, type | tuple[type, ...]]] = {
    "hello": {"protocol": int, "families": list},
    "defaults": {},
    "compute": {"derived": dict},
    "compute_many": {"derived": list},
    "validate": {"available": bool},
    "levels": {"available": bool},
    "views": {"available": bool},
    "trace": {"reads": list, "missing": list, "derived": dict},
    "render": {"available": bool},
}


def check_answer(op: str, rid: int, msg) -> dict:
    """The answer to request `rid` of operation `op`, checked; raises BridgeError when it is not what the protocol promises."""
    if not isinstance(msg, dict) or msg.get("id") != rid or not isinstance(msg.get("ok"), bool):
        raise BridgeError(f"malformed answer to {op} #{rid}: {str(msg)[:200]}")
    if not msg["ok"]:
        raise BridgeError(f"{op} failed in the production code: {str(msg.get('error'))[:400]}")
    res = msg.get("result")
    if not isinstance(res, dict):
        raise BridgeError(f"{op} answered without a result object")
    for k, t in _SHAPES.get(op, {}).items():
        if not isinstance(res.get(k), t):
            raise BridgeError(f"{op} answer lacks {k!r} of type {getattr(t, '__name__', t)}: {str(res)[:200]}")
    if op == "compute_many":
        for row in res["derived"]:
            if not isinstance(row, dict) or not isinstance(row.get("ok"), bool) or (row["ok"] and not isinstance(row.get("derived"), dict)):
                raise BridgeError(f"compute_many answered a malformed row: {str(row)[:200]}")
    return res


class RuleBridge:
    def __init__(self, bundle: Path | None = None, node: str | None = None, timeout_s: float = 30.0):
        self.bundle = Path(bundle) if bundle else cache_dir() / BUNDLE
        self.node = node if node is not None else node_binary()
        self.timeout_s = timeout_s
        self._proc: subprocess.Popen | None = None
        self._out: queue.Queue | None = None
        self._err: deque[str] = deque(maxlen=200)
        self._lock = threading.Lock()
        self._next = 0
        self._hello: dict | None = None
        self.calls = 0

    # ── the process ──────────────────────────────────────────────────────────────

    def _why_not(self) -> str | None:
        if os.environ.get("AUTOPARAM_PRODUCTION_BRIDGE", "1").strip() in ("0", "off", "false"):
            return "the production rule bridge is switched off (AUTOPARAM_PRODUCTION_BRIDGE=0)"
        if not self.node:
            return "node is not installed (or AUTOPARAM_NODE does not point at it): the production rules cannot be executed"
        if not self.bundle.is_file():
            return f"no bundle at {self.bundle}: run `dxf-autoparam production build` (needs the aagento-bridge checkout)"
        return None

    def _start(self) -> None:
        why = self._why_not()
        if why:
            raise BridgeUnavailable(why)
        try:
            self._proc = subprocess.Popen([self.node, str(self.bundle)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          text=True, bufsize=1)
        except OSError as exc:
            raise BridgeUnavailable(f"node could not start: {exc}") from exc
        self._out = queue.Queue()
        out, proc = self._out, self._proc

        def pump_out():
            for line in proc.stdout:
                out.put(line)
            out.put(None)

        def pump_err():
            for line in proc.stderr:
                self._err.append(line.rstrip()[:300])

        threading.Thread(target=pump_out, daemon=True).start()
        threading.Thread(target=pump_err, daemon=True).start()

    def close(self) -> None:
        with self._lock:
            self._stop()

    def _stop(self) -> None:
        p, self._proc = self._proc, None
        if p is not None:
            try:
                p.kill()
                p.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                self._err.append("the bridge process could not be stopped cleanly")

    def stderr_tail(self, n: int = 20) -> list[str]:
        return list(self._err)[-n:]

    # ── requests ─────────────────────────────────────────────────────────────────

    def request(self, op: str, timeout_s: float | None = None, **args) -> dict:
        """One operation, answered and checked. A dead or hung process is stopped and started again on the next request."""
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._stop()
                self._start()
            self._next += 1
            rid = self._next
            try:
                self._proc.stdin.write(json.dumps({"id": rid, "op": op, **args}) + "\n")
                self._proc.stdin.flush()
            except (OSError, ValueError) as exc:
                self._stop()
                raise BridgeError(f"the bridge process is gone ({exc}); stderr: {self.stderr_tail(5)}") from exc
            deadline = time.monotonic() + (timeout_s or self.timeout_s)
            while True:
                left = deadline - time.monotonic()
                try:
                    line = self._out.get(timeout=max(0.01, left)) if left > 0 else None
                except queue.Empty:
                    line = None
                if line is None:
                    alive = self._proc is not None and self._proc.poll() is None
                    self._stop()
                    raise BridgeError(f"{op} timed out after {timeout_s or self.timeout_s:g} s" if alive
                                      else f"the bridge process exited during {op}; stderr: {self.stderr_tail(5)}")
                try:
                    msg = json.loads(line)
                except ValueError:
                    self._err.append("non-protocol stdout: " + line[:200])
                    continue
                if isinstance(msg, dict) and msg.get("id") not in (rid, None):
                    continue  # an answer to a request that already timed out
                self.calls += 1
                return check_answer(op, rid, msg)

    def hello(self) -> dict:
        if self._hello is None:
            h = self.request("hello")
            if h["protocol"] != PROTOCOL:
                raise BridgeError(f"the bundle speaks protocol {h['protocol']}, this code {PROTOCOL}: rebuild it (dxf-autoparam production build)")
            self._hello = h
        return self._hello

    def status(self) -> dict:
        """Whether the production rules can be executed here, and from what build — never raises."""
        why = self._why_not()
        if why:
            return {"available": False, "reason": why}
        try:
            h = self.hello()
        except (BridgeUnavailable, BridgeError) as exc:
            return {"available": False, "reason": str(exc)}
        return {"available": True, "build": h.get("build"), "build_info": _brief(read_info(self.bundle.parent)), "node": h.get("node"),
                "families": h["families"]}


def _brief(info: dict | None) -> dict | None:
    if not info:
        return None
    return {"commit": info["aagento_bridge"]["commit"], "dirty_files": info["aagento_bridge"]["dirty_files"][:10], "built_at": info["built_at"],
            "sources_digest": info["sources_digest"]}


_DEFAULT: RuleBridge | None = None
_DEFAULT_LOCK = threading.Lock()


def default_bridge() -> RuleBridge:
    """One bridge per process (the bundle in this project's cache)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = RuleBridge()
        return _DEFAULT


def set_default_bridge(br: RuleBridge | None) -> None:
    """Replace the process's bridge (tests; a bundle elsewhere). The previous one is stopped."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is not None and _DEFAULT is not br:
            _DEFAULT.close()
        _DEFAULT = br
