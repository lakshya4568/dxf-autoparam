"""Bundling the production rule bridge: `tools/production/bridge_rules.ts` + the aagento-bridge registry → one Node module.

The bundle is a build artefact (`.cache/production/`, git-ignored): it is made from whatever revision of aagento-bridge is checked out, with
that checkout's own esbuild and node_modules, and it carries its identity — the revision, whether the bridges feature had uncommitted changes,
and the sha256 of every module the registry entries name — both in `build.json` and inside the bundle (the bridge reports it on `hello`).
A manifest records the same fingerprints, so a bundle built from other code than the knowledge describes is detected, not trusted.

    dxf-autoparam production build      # needs the aagento-bridge checkout (AAGENTO_BRIDGE_DIR or ../aagento-bridge) and node
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import source as S

ENTRY = Path("tools") / "production" / "bridge_rules.ts"
BUNDLE = "bridge_rules.mjs"
BUILD_INFO = "build.json"


class BuildError(RuntimeError):
    pass


def cache_dir() -> Path:
    """Where the bundle lives: AUTOPARAM_PRODUCTION_CACHE, else this project's .cache/production."""
    env = os.environ.get("AUTOPARAM_PRODUCTION_CACHE")
    return Path(env) if env else S.project_root() / ".cache" / "production"


def node_binary() -> str | None:
    return os.environ.get("AUTOPARAM_NODE") or shutil.which("node")


def build(src: S.Source | None = None, out_dir: Path | None = None) -> dict:
    """Bundle the bridge against the checkout; returns the build info (also written next to the bundle). Raises BuildError with the reason."""
    src = src or S.locate()
    if src is None:
        raise BuildError("no aagento-bridge checkout: set AAGENTO_BRIDGE_DIR or place it next to this project (../aagento-bridge)")
    esbuild = src.root / "node_modules" / ".bin" / "esbuild"
    if not esbuild.is_file():
        raise BuildError(f"{esbuild} not found: run `npm install` in {src.root} first (the bundle uses the checkout's own esbuild)")
    if not (src.root / "node_modules" / "@angular" / "compiler").is_dir():
        raise BuildError("@angular/compiler is not installed in the checkout: the registry's renderers need it to load")
    out_dir = out_dir or cache_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    entry = S.project_root() / ENTRY
    reg = S.registry_modules(src)
    files: dict[str, str] = {}
    for row in reg.values():
        files.update(S.fingerprint(src, row))
    info = {"format": "dxf-autoparam/production-build-1", "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "aagento_bridge": S.revision(src),
            "registry": src.rel(src.registry), "families": sorted(reg),
            "sources": dict(sorted(files.items())), "entry_sha256": S.sha256(entry)}
    info["sources_digest"] = digest(info["sources"])
    tmp = out_dir / (BUNDLE + ".tmp")
    cmd = [str(esbuild), str(entry), "--bundle", "--platform=node", "--format=esm", f"--outfile={tmp}", f"--tsconfig={src.root / 'tsconfig.json'}",
           "--log-level=error", f"--alias:aagento-bridges={src.bridges}", f"--define:__BUILD_INFO__={json.dumps(_embedded(info))}"]
    env = {**os.environ, "NODE_PATH": str(src.root / "node_modules")}
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(src.root), env=env, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BuildError(f"esbuild could not run: {exc}") from exc
    if res.returncode != 0 or not tmp.is_file():
        raise BuildError("esbuild failed:\n" + (res.stderr or res.stdout)[-2000:])
    tmp.replace(out_dir / BUNDLE)
    info["bundle_sha256"] = S.sha256(out_dir / BUNDLE)
    (out_dir / BUILD_INFO).write_text(json.dumps(info, indent=1))
    return info


def _embedded(info: dict) -> dict:
    """What the running bridge reports about itself (hello): enough to match it against a manifest without reading build.json."""
    return {"commit": info["aagento_bridge"]["commit"], "dirty": bool(info["aagento_bridge"]["dirty_files"]), "sources_digest": info["sources_digest"],
            "built_at": info["built_at"]}


def digest(sources: dict[str, str]) -> str:
    h = hashlib.sha256()
    for k in sorted(sources):
        h.update(f"{k}={sources[k]}\n".encode())
    return h.hexdigest()


def read_info(out_dir: Path | None = None) -> dict | None:
    p = (out_dir or cache_dir()) / BUILD_INFO
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None
