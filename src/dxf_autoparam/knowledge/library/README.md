# Engineering libraries

One folder per domain; the folder name is the domain pack's name (`knowledge/<name>.json`, switched on with `--domain`, `options.domain`
or `AUTOPARAM_DOMAIN`). A library is what the agent can RETRIEVE on demand while it works — nothing in it is loaded into a run's context
unless the model asks (`list_skills`, `load_skill`, `search_library`, `get_reference`, `check_rule`, `record_finding`; see `ai/library.py`).

```
<domain>/
  domain.json      name, title, the sources the library reads, the family procedure, the protocol file
  protocol.md      what the model is told about the library (the system prompt's paragraph)
  skills/*.md      human-authored skills and recipes (JSON front matter, then `## ` sections)
```

Three kinds of material are kept apart:

| Kind | Where | Edited by |
|---|---|---|
| Source knowledge (what the engineering material says) | `../agent_context/` (migrated, hash-verified, never edited) | nobody here: re-run `tools/migrate_agent_context.py` |
| Skills and recipes (how the agent uses it) | `<domain>/skills/*.md`, `domain.json` | a person |
| Indexes, caches, traces | in memory; `.cache/library/` if cached; run events | generated, never committed |

To add a recipe: a new `skills/<id>.md`. To add reference material: a new source folder with the same layout as `agent_context` and a
line in `domain.json`. To add another kind of structure's guidance: its skill file under the source's `skills/families/`, or an authored
`skills/<id>.md` with `"kind": "family"` and its cues in the front matter. See `docs/KNOWLEDGE_LIBRARY.md`.
