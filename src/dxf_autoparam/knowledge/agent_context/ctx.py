#!/usr/bin/env python3
"""Command-line wrapper for agentctx. The library is the real interface; this file only starts the CLI.

Run from the repository root, with the project environment (see agent-context/README.md):
    .venv/bin/python agent-context/ctx.py build
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agentctx.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
