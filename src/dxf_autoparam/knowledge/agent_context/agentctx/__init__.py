"""agentctx: a derived access layer over the GAD repository (see agent-context/README.md).

Import it after putting agent-context/ on sys.path:

    import sys; sys.path.insert(0, "agent-context")
    from agentctx import Context
"""

from .api import (
    Context,
    build_evidence_pack,
    get_evidence,
    get_source_status,
    search_knowledge,
    validate_evidence_pack,
)
from .packs import TASKS

__all__ = [
    "Context",
    "TASKS",
    "build_evidence_pack",
    "get_evidence",
    "get_source_status",
    "search_knowledge",
    "validate_evidence_pack",
]
