# AGENTS.md — RootChain

Universal agent instructions for building, modifying, or reviewing this project.
This file applies to any AI agent: Claude, Copilot, Codex, Gemini, etc.

---

## Project Summary

**RootChain** maps production Sentry errors to their GitLab SDLC origin.
When Sentry creates a GitLab issue, a Duo Agent Platform flow queries GitLab Orbit
(the SDLC knowledge graph) to find which MRs last modified each stack frame,
what issues motivated those MRs, and who is responsible. The result is a
confidence-ranked blame chain posted as a comment on the issue.

**Primary artifact:** `.gitlab/duo-flows/rootchain.yml`
**Primary data source:** GitLab Orbit REST API (`/api/v4/orbit/query`)
**Primary trigger:** `work_item_created` GitLab event

---

## Tech Stack

| What | Technology |
|------|-----------|
| Agent Platform | GitLab Duo Agent Platform |
| Knowledge Graph | GitLab Orbit (Remote, ClickHouse-backed) |
| Error Source | Sentry (native GitLab integration) |
| Language | Python 3.11+ |
| HTTP | httpx (async) |
| Data Models | Pydantic v2 |
| Retries | tenacity |
| Logging | structlog (structured JSON) |
| Tests | pytest + pytest-asyncio |
| Optional receiver | FastAPI |

---

## Repository Layout

```
.gitlab/duo-flows/rootchain.yml   ← THE main artifact (Duo flow definition)
.gitlab/skills/rootchain/SKILL.md ← Agent skill: parsing + Orbit interpretation
src/rootchain/
  models.py           ← Pydantic v2 data models (all of them)
  config.py           ← Env-var driven Config frozen dataclass
  sentry_parser.py    ← Parse stack traces from GitLab issue descriptions
  orbit_client.py     ← Orbit REST API client (async, retries, caching)
  blame_chain.py      ← Confidence scoring, chain construction (pure functions)
  issue_formatter.py  ← BlameChain → Markdown string (pure function)
  gitlab_client.py    ← GitLab REST API client (add notes, add labels)
  orchestrator.py     ← Entry point: wire everything, no business logic here
receiver/main.py      ← Optional FastAPI webhook receiver (alternative to native integration)
tests/
  fixtures/           ← JSON fixtures for all test cases
  unit/               ← Unit tests (no external calls)
  integration/        ← Integration tests (require real Orbit + GitLab)
scripts/              ← Dev utilities (smoke tests, test issue generator)
```

---

## Core Flow (Step by Step)

```
1. Sentry alert → GitLab issue created (via Sentry's native GitLab integration)
   Issue has label: sentry-alert
   Issue title: [Sentry] ErrorType: message
   Issue body: contains stack trace in Sentry's format

2. work_item_created event fires
   → rootchain.yml filter checks: label includes sentry-alert?
   → YES: flow activates

3. Agent reads context:
   - WorkItem.Title, WorkItem.Description, WorkItem.IID, WorkItem.Project.FullPath

4. Agent calls get_issue to check for "rootchain-analyzed" label
   → If present: STOP (idempotency guard)

5. Agent parses issue description:
   - Detect language (Python/Node/Go/Ruby/Java) from stack trace format
   - Extract up to 5 non-library frames
   - If 0 frames survive: post "no parseable stack trace" comment → STOP

6. For each frame (in parallel via asyncio.gather):
   Agent calls query_graph (Orbit MCP tool):
   MATCH (d:Definition {name: $fn})-[:DEFINED_IN]->(f:File {path: $fp})
         <-[:MODIFIES_FILE]-(mr:MergeRequest)
   WHERE mr.merged_at IS NOT NULL
   RETURN mr.iid, mr.title, mr.web_url, mr.merged_at, mr.author_username
   ORDER BY mr.merged_at DESC LIMIT 3

   If 0 results: fall back to file-level query (same but no Definition hop)
   If still 0: mark orbit_miss=True for this frame

7. For each MR found: run secondary queries for linked issues and reviewers

8. Calculate confidence per frame (recency × depth × blast, see formula in README)
   Deduplicate entries where two frames point to same MR (keep higher confidence)
   Identify primary_suspect (highest confidence entry above threshold)

9. Render Markdown comment (see template in README LLD section)

10. Call create_note with the rendered Markdown
    Call add_label with "rootchain-analyzed"

11. Flow completes
```

---

## Non-Negotiable Rules

These apply to every file you create or modify:

1. **Type hints everywhere.** Every function parameter and return value. No bare `Any`.
2. **Pydantic v2 syntax.** `model_config = ConfigDict(...)`, `@field_validator`, `X | None` not `Optional[X]`.
3. **Async all I/O.** `httpx.AsyncClient`, `await`, `async def`. Never `requests`.
4. **Parameterized Orbit queries.** Never string-interpolate into Cypher. Use `params` dict.
5. **No global state.** Config passed explicitly. No module-level variables that hold state.
6. **No silent swallowing.** Every `except` block either logs + returns `Err(...)` or re-raises.
7. **No modification of issue description.** Only add notes and labels. Never `PUT /issues` body.
8. **No fabrication.** If Orbit returns nothing, say so. Never invent MR titles or authors.
9. **Structlog, not print/logging.** `log = structlog.get_logger()`, bind context before logging.
10. **Frozen Config.** `@dataclass(frozen=True)`. All env var reads happen in `Config.from_env()` only.

---

## Data Models Reference

These are the exact models in `src/rootchain/models.py`. Use them everywhere; don't create local dicts.

```python
# Result type for fallible operations
Ok[T] | Err   where Err has: message: str, code: str, retryable: bool

# Core parsing output
StackFrame: file_path, function_name, line_number, language, is_library, frame_depth, raw_line
SentryEvent: error_type, error_message, culprit, environment, frames, sentry_issue_url

# Orbit output
LinkedIssue: iid, title, web_url, state
MRContext: iid, title, description, author_username, merged_at, web_url, linked_issues, reviewers, days_since_merge
SymbolHistory: function_name, file_path, recent_mrs, caller_count, orbit_miss, fallback_used

# Blame chain
BlameEntry: frame, history, primary_mr, confidence, confidence_label, confidence_reason
BlameChain: entries, primary_suspect, frames_analyzed, frames_total, orbit_misses, generated_at
```

---

## Environment Variables

Required:
```
ROOTCHAIN_GITLAB_TOKEN       PAT with api scope
ROOTCHAIN_GITLAB_URL         https://gitlab.com (or self-managed)
ROOTCHAIN_GROUP_PATH         top-level group with Orbit enabled
ROOTCHAIN_PROJECT_PATH       group/project where issues are created
```

Optional (with defaults):
```
ROOTCHAIN_ORBIT_TIMEOUT_SECONDS=30
ROOTCHAIN_ORBIT_MAX_RETRIES=3
ROOTCHAIN_MAX_FRAMES=5
ROOTCHAIN_CONFIDENCE_THRESHOLD=0.4
ROOTCHAIN_RECENCY_WEIGHT=0.50
ROOTCHAIN_DEPTH_WEIGHT=0.35
ROOTCHAIN_BLAST_WEIGHT=0.15
ROOTCHAIN_RECENCY_HALF_LIFE_DAYS=30
ROOTCHAIN_ADD_LABEL=rootchain-analyzed
ROOTCHAIN_MENTION_AUTHORS=true
ROOTCHAIN_MAX_MENTION_USERS=3
ROOTCHAIN_LOG_LEVEL=INFO
ROOTCHAIN_LOG_FORMAT=json
```

---

## Edge Cases You Must Handle

| Case | Where handled | What to do |
|------|---------------|-----------|
| Issue already has `rootchain-analyzed` label | Step 4 | Stop immediately, no output |
| No stack trace found in description | `sentry_parser.py` | Post "no stack trace" comment, apply label, stop |
| All frames are library code | `sentry_parser.py` | Post "all library frames" comment, apply label, stop |
| Minified JS (empty function names) | `sentry_parser.py` | Skip frame, note in comment how many were skipped |
| Orbit query timeout | `orbit_client.py` | Retry 3× with exponential backoff, then `orbit_miss=True` |
| Orbit returns 0 for definition | `orbit_client.py` | Try file-level fallback, set `fallback_used=True` |
| Same MR appears for multiple frames | `blame_chain.py` | Merge entries, keep higher confidence score |
| MR has no linked issues | `orbit_client.py` | `linked_issues=[]`, still include MR in output |
| Java `Caused by:` chain | `sentry_parser.py` | Parse root cause block as primary, include others as context |
| Go goroutine header lines | `sentry_parser.py` | Strip `goroutine N [state]:` lines before parsing |
| GitLab API 429 rate limit | `gitlab_client.py` | Read `Retry-After` header, wait, retry |
| `merged_at` is None (open MR) | `orbit_client.py` | Exclude from results (only analyze merged MRs) |
| Sentry fires twice for same issue | Flow trigger | Idempotency label check handles this |

---

## Test Requirements

- Every public function in `src/rootchain/` must have at least one unit test
- Every edge case in the table above must have a dedicated test
- Unit tests must not make real HTTP calls — mock with `respx` or `httpx.MockTransport`
- Use fixtures from `tests/fixtures/*.json` — do not hardcode payloads in test files
- Integration tests must be gated by `ROOTCHAIN_INTEGRATION_TESTS=1` env var
- Target: 80%+ coverage on `src/rootchain/`

---

## Confidence Score Formula

```
days_since    = (now_utc - primary_mr.merged_at).days
recency       = 1.0 / (1.0 + days_since / HALF_LIFE_DAYS)
depth         = 1.0 / frame.frame_depth
blast         = min(caller_count / 10.0, 1.0)
confidence    = recency * W_RECENCY + depth * W_DEPTH + blast * W_BLAST
if fallback:  confidence *= 0.7
if orbit_miss: confidence = 0.0

Labels:
  >= 0.7  → "HIGH"    🔴
  >= 0.4  → "MEDIUM"  🟡
  < 0.4   → "LOW"     🟢
```

Do not change these thresholds without updating README.md.

---

## Orbit Query Patterns

Always use this structure for REST API calls:

```python
POST https://gitlab.com/api/v4/orbit/query
Content-Type: application/json
PRIVATE-TOKEN: {token}

{
  "query": "MATCH (d:Definition {name: $fn}) ... RETURN ...",
  "parameters": {"fn": "functionName", "fp": "path/to/file.py"},
  "timeout": 30000
}
```

The response shape:
```json
{
  "data": {
    "nodes": [{"id": "mr:123", "type": "MergeRequest", "properties": {...}}],
    "edges": [{"source": "mr:123", "target": "wi:89", "type": "CLOSES"}]
  },
  "meta": {"query_time_ms": 142}
}
```

Always check `"data"` key exists before accessing. On error: `{"error": "..."}`.
Cast `iid` to `int` always — ClickHouse can return it as string.
Parse `merged_at` as ISO 8601 UTC: `datetime.fromisoformat(v.replace("Z", "+00:00"))`.

---

## pyproject.toml Dependencies

```toml
[project]
name = "rootchain"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27.0",
    "pydantic>=2.7.0",
    "tenacity>=8.3.0",
    "structlog>=24.2.0",
    "fastapi>=0.111.0",     # receiver only
    "uvicorn>=0.30.0",      # receiver only
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=5.0.0",
    "respx>=0.21.0",        # httpx mocking
    "ruff>=0.4.0",
    "mypy>=1.10.0",
]
```

---

## When Unsure About Orbit Schema

Run this to get the live schema for any GitLab instance:
```bash
curl -s \
  --header "PRIVATE-TOKEN: $ROOTCHAIN_GITLAB_TOKEN" \
  "https://gitlab.com/api/v4/orbit/schema" | jq '.domains'
```

The node types, edge types, and property names are authoritative from this endpoint.
Do not hardcode schema assumptions — always refer to the live schema in documentation
or verify against the test fixtures.

---

## Definition of Done

A feature or file is complete when:
- [ ] All functions have type hints and docstrings
- [ ] All edge cases for that module are handled (see edge case table)
- [ ] Unit tests cover the happy path + at least 3 edge cases
- [ ] No `logging`, `requests`, `Optional`, or Pydantic v1 patterns
- [ ] `ruff check` passes with zero warnings
- [ ] `mypy` passes with zero errors on `src/rootchain/`
- [ ] README.md is still accurate (update it if behavior changed)