# Agent skills (agent-context)

These skills tell an agent how to use the context layer. They call the library (`agent-context/ctx.py`) and cite
only ids that resolve. They do not copy the knowledge base or the drawings.

| Skill | Use it when | Main commands |
|---|---|---|
| `find-source-evidence` | You need what the repository holds about a sheet, page or topic | `status`, `search`, `evidence`, `pack --task source_evidence` |
| `interpret-components` | You need to name the parts a sheet shows | `pack --task component_interpretation`, `search` (category C) |
| `propose-dimension-bindings` | You want to suggest which written dimension sets which parameter | `pack --task dimension_binding`, `validate` |
| `propose-geometric-relationships` | You want to describe how views, levels and parts relate | `pack --task geometric_relationships`, `evidence` |
| `handle-uncertainty` | Anything is missing, disputed, unreviewed or conflicting | `status`, `check`, `validate` |
| `families/<family>/SKILL.md` | You are working on a drawing of a given bridge family | the commands above, plus the family notes |

## Rules every skill follows

1. Start from the record: `ctx.py status <record_id>`. Read its completeness, eligibility and issues before anything else.
2. Cite evidence ids (for example `21cc08a32dd8-p1#D1`). A statement with no id is not evidence.
3. Keep three things apart: the printed text, the agent's reading of it, and the knowledge-base definition.
4. Label every knowledge item with its category and review state. An unreviewed entry is context, not a fact.
5. A binding is a candidate until a person verifies the value and its unit. The repository holds no such verification, so every binding is blocked.
6. A pack is derived. Never cite a pack as a source, and never write a pack's content back into the knowledge base.
7. If a record is ungrounded or a page is not saved, say so and stop there. Do not fill the gap.
8. Validate what you produce: `ctx.py validate <pack>` must report `valid: true` before you rely on it.

## Python

```python
import sys
sys.path.insert(0, "agent-context")
from agentctx import Context
ctx = Context()
```
