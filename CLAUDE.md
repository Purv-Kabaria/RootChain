# CLAUDE.md — RootChain

This file tells Claude Code exactly how to build, extend, and reason about this project.
Read this entire file before touching any code.

---

## What This Project Is

**RootChain** is a GitLab Duo Agent Platform flow that:
1. Receives a trigger when a Sentry error creates a GitLab issue
2. Parses the stack trace from the issue description
3. Queries GitLab Orbit (REST API) for each stack frame to find the SDLC history
4. Builds a confidence-scored blame chain
5. Posts a structured Markdown comment back to the issue

The **primary artifact** is `.gitlab/duo-flows/rootchain.yml`. Everything else (Python scripts, tests, receiver) supports or validates that artifact.

---

## Architecture in One Paragraph

`work_item_created` GitLab event → Duo Agent Platform loads `rootchain.yml` flow → Agent reads the issue context (title + description injected as `{{ .WorkItem.* }}`) → `SKILL.md` is loaded into agent context → Agent calls `query_graph` Orbit MCP tool for each stack frame (Cypher-like DSL) → Agent builds confidence-ranked blame chain → Agent calls `create_note` to post Markdown comment → Agent calls `add_label` to apply `rootchain-analyzed` label → Flow completes.

The Python code in `src/rootchain/` exists as a **fallback orchestrator** — for testing, for the optional webhook receiver, and for orgs that want to run this outside the Duo Agent Platform context. The Python code does NOT run inside the Duo flow itself; the Duo agent calls Orbit's native MCP tools.

---

## File Creation Order

Build in this exact order to avoid circular dependency confusion:

1. `src/rootchain/models.py` — All Pydantic models. No imports from other src files.
2. `src/rootchain/config.py` — Config dataclass. Only imports from stdlib and models.
3. `src/rootchain/sentry_parser.py` — Pure parsing logic. Only imports models, config, re, structlog.
4. `src/rootchain/orbit_client.py` — Orbit REST API client. Imports models, config, httpx, tenacity.
5. `src/rootchain/blame_chain.py` — Pure function: takes models, returns models. No I/O.
6. `src/rootchain/issue_formatter.py` — Pure function: takes BlameChain, returns str. No I/O.
7. `src/rootchain/gitlab_client.py` — GitLab REST API client. Imports models, config, httpx.
8. `src/rootchain/orchestrator.py` — Wires all above. The only file that imports everything.
9. `receiver/main.py` — FastAPI app. Imports orchestrator.
10. `.gitlab/duo-flows/rootchain.yml` — The actual flow. References SKILL.md.
11. `.gitlab/skills/rootchain/SKILL.md` — Agent skill content. Plain markdown, no code.
12. `tests/` — After all source is done.
13. `.gitlab-ci.yml` — After tests are done.

---

## Key Decisions Already Made (Do Not Reverse)

- **Python 3.11+** — Use `match` statements, `X | Y` union types, `tomllib`. No `Optional[X]`, always `X | None`.
- **Pydantic v2** — `model_config = ConfigDict(...)`, not the v1 `class Config` pattern.
- **httpx, not requests** — All HTTP is async. `httpx.AsyncClient` with connection limits.
- **tenacity for retries** — Not manual retry loops. Use `@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))`.
- **structlog, not logging** — Always bind context: `log = log.bind(function_name=..., file_path=...)`.
- **Result type** — `Ok[T] | Err` pattern for fallible operations. Defined in `models.py`. Do not raise exceptions for expected failures (orbit miss, parse failure). Raise only for programmer errors.
- **Frozen dataclass for Config** — `@dataclass(frozen=True)`. Pass Config explicitly; no global state.
- **Comment, not description edit** — When updating the GitLab issue, always `POST /notes` (add comment), never `PUT /issues` on the body. Sentry updates the body; we don't fight it.
- **Idempotency via label** — First thing the agent checks: does the issue already have `rootchain-analyzed`? If yes, stop.

---

## Critical Implementation Details

### `sentry_parser.py`

The issue description comes as raw Markdown. Sentry's format is consistent but varies by language.

```python
# Python frame pattern (regex):
r'File "(?P<path>[^"]+)", line (?P<line>\d+), in (?P<func>\S+)'

# Node.js frame pattern:
r'at (?P<func>[\w.<>]+) \((?P<path>[^:]+):(?P<line>\d+):\d+\)'

# Go frame pattern (two lines: goroutine header + frame):
r'(?P<path>[^\s]+\.go):(?P<line>\d+)'   # file line
r'\t(?P<func>[\w/.()*]+)\('              # func line (next line)

# Ruby frame pattern:
r'(?P<path>[^:]+):(?P<line>\d+):in `(?P<func>[^\']+)\''

# Java frame pattern:
r'at (?P<class>[\w.]+)\.(?P<func>\w+)\((?P<file>\w+\.java):(?P<line>\d+)\)'
```

Library detection — a frame IS a library frame if its `file_path` matches ANY of:
```python
LIBRARY_PREFIXES = [
    "site-packages/", "/usr/lib/", "/usr/local/lib/",
    "node_modules/", "vendor/", "dist/",
    "java.", "sun.", "javax.", "com.sun.",
    "runtime/", "builtin/",
]
```

After filtering library frames, if `function_name` is any of:
`["<module>", "<anonymous>", "<lambda>", "main", "__main__", ""]` — skip that frame too.

### `orbit_client.py`

**DO NOT** interpolate user-supplied strings directly into Cypher queries. Always use parameterized queries:

```python
# CORRECT
query = """
MATCH (d:Definition {name: $function_name})
      -[:DEFINED_IN]->(f:File {path: $file_path})
      <-[:MODIFIES_FILE]-(mr:MergeRequest)
WHERE mr.merged_at IS NOT NULL
RETURN mr.iid, mr.title, mr.web_url, mr.merged_at, mr.author_username
ORDER BY mr.merged_at DESC LIMIT 3
"""
params = {"function_name": frame.function_name, "file_path": frame.file_path}

# WRONG — injection risk
query = f"MATCH (d:Definition {{name: '{frame.function_name}'}})..."
```

**Parallel queries:** Use `asyncio.gather()` for all frames simultaneously, not a loop:

```python
results = await asyncio.gather(
    *[self.get_symbol_history(f.function_name, f.file_path) for f in frames],
    return_exceptions=True  # Don't let one failure kill all
)
# Handle each result: if isinstance(r, Exception): log and create orbit_miss entry
```

**Response normalization:** Orbit responses can return `iid` as int or string from ClickHouse. Always cast:
```python
mr_iid = int(node["properties"].get("iid", 0))
```

**Fallback strategy:** If the primary Definition-level query returns 0 results:
```python
# Fall back to file-level match
fallback_query = """
MATCH (f:File {path: $file_path})<-[:MODIFIES_FILE]-(mr:MergeRequest)
WHERE mr.merged_at IS NOT NULL
RETURN mr.iid, mr.title, mr.web_url, mr.merged_at, mr.author_username
ORDER BY mr.merged_at DESC LIMIT 3
"""
```
Set `fallback_used=True` on the resulting `SymbolHistory` — this reduces confidence score.

If file-level also returns 0: set `orbit_miss=True`. Do not make up data.

### `blame_chain.py`

The confidence score formula (from README, must match exactly):
```python
from datetime import datetime, timezone

def calculate_confidence(
    frame: StackFrame,
    history: SymbolHistory,
    config: Config,
) -> tuple[float, str]:
    if history.orbit_miss:
        return 0.0, "No Orbit data available"
    
    primary_mr = history.recent_mrs[0] if history.recent_mrs else None
    if primary_mr is None:
        return 0.0, "No MR history found"
    
    days_since = (datetime.now(timezone.utc) - primary_mr.merged_at).days
    half_life = config.recency_half_life_days
    recency = 1.0 / (1.0 + days_since / half_life)
    
    depth = 1.0 / frame.frame_depth
    blast = min(history.caller_count / 10.0, 1.0)
    
    score = (
        recency * config.recency_weight +
        depth * config.depth_weight +
        blast * config.blast_weight
    )
    
    if history.fallback_used:
        score *= 0.7
    
    reason = (
        f"MR merged {days_since}d ago (recency={recency:.2f}), "
        f"frame depth {frame.frame_depth} (depth={depth:.2f}), "
        f"{history.caller_count} callers (blast={blast:.2f})"
    )
    return round(score, 3), reason
```

**Deduplication:** After scoring, if two `BlameEntry` items reference the same `mr.iid`, keep the one with higher confidence and discard the duplicate.

### `issue_formatter.py`

- All MR and issue references must be hyperlinked: `[!{iid}]({web_url})`
- Use `🔴` for HIGH, `🟡` for MEDIUM, `🟢` for LOW confidence
- The closing `<sub>` tag is required — it must link to the project and include "disable" and "false positive" links
- Never include backticks inside table cells (GitHub/GitLab renders them oddly) — use `code` HTML tag instead if needed, but plain text is preferred in tables

### `.gitlab/duo-flows/rootchain.yml`

The YAML schema must validate against the Duo Agent Platform spec. Key constraints:
- `version: 1` (integer, not string)
- `trigger.event` must be exactly `work_item_created` (snake_case)
- `steps[].type` must be `agent` (the Duo Agent Platform supports `agent` and `pipeline`)
- `skills` references the folder name under `.gitlab/skills/` (not the SKILL.md path)
- `tools` must only reference tools that the Duo Agent Platform provides natively or via Orbit MCP

The four tools used:
- `query_graph` — Orbit MCP tool, available natively
- `create_note` — GitLab built-in: creates a comment on an issue
- `add_label` — GitLab built-in: adds a label to an issue
- `get_issue` — GitLab built-in: reads current issue state (for idempotency check)

### `.gitlab/skills/rootchain/SKILL.md`

This file is **loaded as agent context** when the flow runs. It must be written in plain English that an LLM can follow. Structure it as:

```markdown
# RootChain Skill

## Your Role
You are RootChain, a GitLab Orbit intelligence agent. Your job is to trace 
production errors to their SDLC origin...

## How to Parse a Sentry Issue Description
1. Look for the error type and message in the ## heading
2. Find the "Stacktrace" section
3. Parse each frame using these language-specific patterns...

## How to Interpret Orbit Results
When `query_graph` returns results:
- `nodes` contains the matched graph nodes
- Filter by `type == "MergeRequest"` for MR data
- The `properties.merged_at` field is ISO 8601 UTC
- If `nodes` is empty: this is an orbit_miss — say so, don't guess

## How to Score Confidence
[describe the formula in plain English so the agent can apply it]

## Output Format
[paste the exact Markdown template the agent must fill]

## What NOT to Do
- Do not modify the original issue description
- Do not guess MR authors or issue titles if Orbit returns no data
- Do not analyze more than 5 frames
- Do not @mention more than 3 people
- Stop immediately if the issue already has the label "rootchain-analyzed"
```

---

## What to Avoid

- **Do not** use `requests` — only `httpx`.
- **Do not** use `logging` — only `structlog`.
- **Do not** use synchronous code for I/O — everything is `async/await`.
- **Do not** put business logic in `orchestrator.py` — it should only call other modules.
- **Do not** hardcode any URL, token, or project path — everything comes from `Config`.
- **Do not** modify the GitLab issue description — only add notes (comments) and labels.
- **Do not** fabricate Orbit results — if `orbit_miss=True`, say so in the output.
- **Do not** expose the `ROOTCHAIN_GITLAB_TOKEN` in any log output (structlog masks it if you use `config.gitlab_token` bound to the logger — don't bind it).
- **Do not** string-interpolate into Cypher queries.
- **Do not** run `asyncio.run()` inside library modules — only in `orchestrator.py` entry point.
- **Do not** use `Optional[X]` — use `X | None` (Python 3.10+ style).
- **Do not** use Pydantic v1 patterns (`class Config: ...` inside model, `validator` decorator) — use v2 (`model_config = ConfigDict(...)`, `@field_validator`).

---

## Running Locally

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Unit tests only (no external calls)
pytest tests/unit/ -v

# Smoke test Orbit connection
export ROOTCHAIN_GITLAB_TOKEN=glpat-xxx
export ROOTCHAIN_GROUP_PATH=your-group
python scripts/test_orbit_connection.py

# Simulate the full flow (creates a real test issue)
export ROOTCHAIN_PROJECT_PATH=your-group/your-project
python scripts/generate_test_issue.py --language python
```

---

## When You're Stuck

- Orbit query syntax: `GET /api/v4/orbit/schema` returns the live schema for your instance.
- Duo flow YAML schema: `GET /api/v4/ai/agent_flows/schema` (check docs for exact path).
- GitLab notes API: `POST /api/v4/projects/{id}/issues/{iid}/notes` — body is `{"body": "..."}`.
- All Orbit API docs: `https://docs.gitlab.com/api/orbit/`
- All Duo Agent Platform docs: `https://docs.gitlab.com/user/duo_agent_platform/`