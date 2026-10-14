"""Allows: python3 -m agentctx <command>  (run from agent-context/, or with agent-context/ on sys.path)."""

from .cli import main

raise SystemExit(main())
