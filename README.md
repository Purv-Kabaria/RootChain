# RootChain

> **GitLab Duo Agent Platform · Showcase Track**
> Trace production errors to their SDLC origin — automatically, in under 2 minutes.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitLab Duo](https://img.shields.io/badge/GitLab-Duo%20Agent%20Platform-orange)](https://docs.gitlab.com/user/duo_agent_platform/)
[![Orbit](https://img.shields.io/badge/GitLab-Orbit-blue)](https://docs.gitlab.com/orbit/)
[![Python](https://img.shields.io/badge/Python-3.11%2B-green)](https://python.org)

---

## The Problem

A production 500 error fires at 2am. Your on-call engineer opens the Sentry alert, sees a stack trace, and starts doing archaeology: `git blame` on each frame, grepping closed issues, finding the MR that introduced the change, messaging the author on Slack. This takes 30–90 minutes before a single line of fix is written. The answer has been sitting inside GitLab the whole time — in the MR that changed the function, the issue that motivated it, the reviewer who approved it — just disconnected from the runtime error.

**RootChain closes that gap.**

When Sentry creates a GitLab issue for a production alert, RootChain's GitLab Duo Agent Platform flow automatically activates. It parses the stack trace, queries GitLab Orbit for the SDLC history of each relevant frame, and posts a structured blame-chain analysis back to the issue — identifying the most likely causal MR, the intent behind it, and who to loop in — within 2 minutes of the alert firing.

**What changes:** On-call engineers open the GitLab issue to find context already waiting for them. "This error was most likely introduced by MR !342 (4 days ago), which was implementing issue #89 (payment retry logic), approved by @alice. The function `processPayment()` was changed to add a retry branch that may not handle null gateway responses."

---

## Demo Flow

```
Sentry fires alert: "TypeError: Cannot read property 'id' of undefined"
          │
          ▼
Sentry–GitLab integration creates GitLab issue (label: sentry-alert)
          │
          ▼
work_item_created trigger activates RootChain flow
          │
          ▼
Flow parses stack trace from issue description
          │
          ▼
Orbit REST API queries: Definition → MergeRequest → WorkItem + User
          │
          ▼
Agent builds ranked blame-chain (confidence-scored per frame)
          │
          ▼
Issue updated with structured analysis comment in < 2 minutes
          │
          ▼
On-call engineer sees: primary suspect MR, intent, author, suggested fix path
```

---

## Architecture

### Mermaid Flow Diagram

```mermaid
flowchart TD
    A[Sentry fires alert] -->|native GitLab integration| B[GitLab Issue created\nlabels: sentry-alert, Sentry]
    B -->|work_item_created event| C[RootChain Flow activates]
    C --> D{Already has\nrootchain-analyzed\nlabel?}
    D -->|Yes| E[Stop — idempotency guard]
    D -->|No| F[Parse stack trace\nfrom issue description]
    F --> G{Parseable\nframes found?}
    G -->|No| H[Post 'no stack trace'\ncomment + label]
    G -->|Yes — up to 5 frames| I[Query Orbit in parallel\nfor each frame]
    I --> J[Primary: Definition→File→MR\nquery_graph]
    J -->|0 results| K[Fallback: File→MR\nquery_graph]
    K -->|0 results| L[orbit_miss = true]
    J -->|MRs found| M[Enrich: linked WorkItems\nReviewers + Caller count]
    K -->|MRs found| M
    M --> N[Score confidence\nrecency×0.5 + depth×0.35 + blast×0.15]
    N --> O[Deduplicate by MR iid\nSelect primary suspect]
    O --> P[Render Markdown\nblame chain comment]
    P --> Q[create_note on issue]
    Q --> R[add_label rootchain-analyzed]
    R --> S[Done — context delivered\nin under 2 minutes]
```

### High-Level Design (HLD)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL LAYER                                  │
│                                                                               │
│   ┌─────────────┐      native integration      ┌──────────────────────────┐ │
│   │   Sentry    │ ─────────────────────────────▶│  GitLab Issue Created   │ │
│   │  (Alerts)   │    (or webhook receiver)      │  label: sentry-alert    │ │
│   └─────────────┘                               └──────────────┬───────────┘ │
└──────────────────────────────────────────────────────────────│─────────────┘
                                                                │
                                                   work_item_created event
                                                                │
┌──────────────────────────────────────────────────────────────▼─────────────┐
│                        GITLAB DUO AGENT PLATFORM                             │
│                                                                               │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                    RootChain Flow (rootchain.yml)                      │ │
│   │                                                                         │ │
│   │  ┌──────────────┐    ┌──────────────────┐    ┌─────────────────────┐  │ │
│   │  │ Sentry Parser│───▶│  Orbit Tracer    │───▶│  Issue Updater      │  │ │
│   │  │ (AgentComp.) │    │  (AgentComp.)    │    │  (AgentComp.)       │  │ │
│   │  │              │    │                  │    │                     │  │ │
│   │  │ · Parse title│    │ · query_graph()  │    │ · Build Markdown    │  │ │
│   │  │ · Extract    │    │ · Per-frame      │    │ · create_note()     │  │ │
│   │  │   frames     │    │   symbol lookup  │    │ · add_label()       │  │ │
│   │  │ · Filter     │    │ · MR traversal   │    │ · @mention author   │  │ │
│   │  │   libraries  │    │ · Issue links    │    │                     │  │ │
│   │  └──────────────┘    └────────┬─────────┘    └─────────────────────┘  │ │
│   │                               │                                          │ │
│   │           SKILL.md loaded ────┘                                          │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────│─────────────┘
                                                                │
┌──────────────────────────────────────────────────────────────▼─────────────┐
│                          GITLAB ORBIT (Remote)                               │
│                                                                               │
│  ClickHouse-backed property graph, live-indexed from your GitLab instance   │
│                                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  ┌───────────────┐ │
│  │  Definition  │  │ MergeRequest │  │   WorkItem    │  │     User      │ │
│  │  (symbols)   │  │  (MRs/PRs)   │  │  (issues)     │  │  (authors)    │ │
│  └──────┬───────┘  └──────┬───────┘  └───────────────┘  └───────────────┘ │
│         │  DEFINED_IN      │  CLOSES / MENTIONS                              │
│         ▼                  ▼                                                 │
│  ┌──────────────┐  ┌──────────────┐                                         │
│  │     File     │  │   WorkItem   │  ◀── N-hop graph traversal queries      │
│  └──────────────┘  └──────────────┘                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Low-Level Design (LLD)

#### 1. Trigger & Entry

**Trigger:** `work_item_created`
**Filter:** Issue label contains `sentry-alert` OR issue title matches `^\[Sentry\]`
**Context injected into agent:**
- `WorkItem.Title` — the Sentry error title
- `WorkItem.Description` — full issue body (contains stack trace in Sentry's format)
- `WorkItem.Labels` — label set for validation
- `WorkItem.IID` — issue number for the update call
- `WorkItem.Project.FullPath` — namespace/project for Orbit scoping
- `WorkItem.WebURL` — for linking back

**Guard check (first thing the agent does):**
```
IF already has label "rootchain-analyzed" → exit immediately (idempotency)
IF issue body has no recognizable stack trace → add comment "RootChain: No stack trace detected" → exit
```

#### 2. Sentry Event Parsing

The agent parses the GitLab issue description to extract a `SentryEvent` structure. Sentry's GitLab integration creates issues with a predictable format:

```
## TypeError: Cannot read property 'id' of undefined

**Culprit:** payments/processor.py in processPayment at line 142
**Environment:** production
**Times seen:** 47

### Stacktrace

  File "payments/processor.py", line 142, in processPayment
    result = gateway_response['id']
  File "payments/gateway.py", line 88, in call_gateway
    return self._session.post(url, data=payload)
  File "core/session.py", line 34, in post
    return requests.post(...)
```

**Parsing rules per language:**

| Language | Frame pattern | Library detection |
|----------|--------------|-------------------|
| Python | `File "path", line N, in func` | `site-packages/`, `/usr/lib/` |
| Node.js | `at FuncName (file.js:N:C)` | `node_modules/` |
| Go | `goroutine N [...]\npackage.Func(...)` | `runtime/`, `vendor/` |
| Ruby | `path:N:in 'method'` | `gems/`, `/usr/` |
| Java | `at class.method(File.java:N)` | `java.`, `sun.`, `com.google.` |

**Frame filtering (in order):**
1. Remove frames matching library path patterns
2. Remove frames where `function_name` is empty, `<anonymous>`, `<module>`, or `main`
3. Remove frames whose `file_path` starts with `/` and doesn't match any known project prefix
4. Take the top 5 remaining frames (closest to the error source first)
5. If 0 frames survive: add a comment explaining why and mention source maps for JS

#### 3. Orbit Graph Traversal

For each surviving frame, the agent executes a multi-hop Orbit query via the `query_graph` MCP tool (or the REST API at `POST /api/v4/orbit/query`).

**Primary query — Find MRs that modified this symbol:**
```cypher
MATCH (d:Definition {name: $function_name})
      -[:DEFINED_IN]->(f:File {path: $file_path})
      <-[:MODIFIES_FILE]-(mr:MergeRequest)
WHERE mr.merged_at IS NOT NULL
  AND mr.project_full_path STARTS WITH $group_path
RETURN
  mr.iid          AS iid,
  mr.title        AS title,
  mr.description  AS description,
  mr.web_url      AS url,
  mr.merged_at    AS merged_at,
  mr.author_username AS author
ORDER BY mr.merged_at DESC
LIMIT 3
```

**Secondary query — Get work items linked to each MR:**
```cypher
MATCH (mr:MergeRequest {iid: $mr_iid, project_full_path: $project_path})
      -[:CLOSES|MENTIONED_IN]->(wi:WorkItem)
RETURN
  wi.iid    AS iid,
  wi.title  AS title,
  wi.state  AS state,
  wi.web_url AS url
```

**Tertiary query — Get reviewers (for @mention):**
```cypher
MATCH (u:User)-[:REVIEWED]->(mr:MergeRequest {iid: $mr_iid, project_full_path: $project_path})
RETURN u.username AS username, u.name AS name
```

**Hot-path check (for confidence scoring):**
```cypher
MATCH (caller:Definition)-[:CALLS]->(d:Definition {name: $function_name})
RETURN count(caller) AS caller_count
```

**Query execution strategy:**
- Run primary query for all 5 frames in parallel (not sequential)
- Cache results keyed by `(function_name, file_path)` within a single flow run
- If primary query returns 0 results: fall back to file-level MR lookup (remove `Definition` node, query only on `File`)
- If file-level also returns 0: mark frame as `orbit_miss` (function too new, file not indexed, or external)
- Timeout per query: 30 seconds. Retry: 3× with 2s, 4s, 8s backoff.

#### 4. Blame Chain Construction

After Orbit returns results for all frames, the agent builds a ranked blame chain.

**Confidence score formula per frame:**

```
recency_score    = 1.0 / (1 + days_since_merge / 30)   # 0–1, decays over time
depth_score      = 1.0 / frame_depth                    # frame 1 = 1.0, frame 5 = 0.2
blast_score      = min(caller_count / 10, 1.0)          # more callers = more likely to matter
orbit_coverage   = 0.0 if orbit_miss else 1.0

confidence = (recency_score * 0.5 + depth_score * 0.35 + blast_score * 0.15) * orbit_coverage
```

**Primary suspect:** the frame/MR with the highest confidence score.

**Confidence thresholds:**
- `≥ 0.7`: HIGH — "Very likely introduced by..."
- `0.4–0.69`: MEDIUM — "May have been affected by..."
- `< 0.4`: LOW — "Historically modified by..."

#### 5. Issue Update

The agent posts a new **comment** (note) on the issue — it does NOT modify the original description (Sentry keeps updating it). It also applies the `rootchain-analyzed` label.

**Comment format:**
```markdown
## 🔗 RootChain SDLC Blame Analysis

**Analyzed:** {timestamp} UTC  
**Error:** `{error_type}: {error_message}`  
**Frames analyzed:** {n} (filtered from {total} total)  
**Primary suspect:** [MR !{iid}]({url}) by @{author} · {N} days ago

---

### Stack Trace → SDLC Chain

| # | Function | File | Last MR | Intent | Author | Confidence |
|---|----------|------|---------|--------|--------|------------|
| 1 | `processPayment` | payments/processor.py:142 | [!342]({url}) · 4d ago | [#89: Add retry logic]({url}) | @alice | 🔴 HIGH |
| 2 | `call_gateway` | payments/gateway.py:88 | [!318]({url}) · 3w ago | [#74: Refactor gateway]({url}) | @bob | 🟡 MEDIUM |
| 3 | `post` | core/session.py:34 | [!201]({url}) · 2mo ago | [#41: Session pooling]({url}) | @carol | 🟢 LOW |

---

### Analysis

MR !342 introduced retry logic in `processPayment()` to close issue #89. The 
change adds a retry branch for failed gateway calls. Based on the TypeError 
(`'id' of undefined`), the retry response path may return a different structure 
than the success path, and `gateway_response['id']` is accessed without a null 
check on the retry code path.

**Suggested investigation:** Review `payments/processor.py` around line 142, 
specifically the retry branch added in [MR !342]({url}). Check whether 
`gateway_response` can be `null` or `undefined` on retry exhaustion.

**Loop in:** @alice (MR author) · @dave (MR reviewer)

---

<sub>Generated by [RootChain](https://gitlab.com/{your-group}/rootchain) · 
[Disable for this project](link) · [Report false positive](link)</sub>
```

#### 6. Data Models

```python
# All models use Pydantic v2

class Language(str, Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    GO = "go"
    RUBY = "ruby"
    JAVA = "java"
    UNKNOWN = "unknown"

class StackFrame(BaseModel):
    file_path: str
    function_name: str
    line_number: int
    language: Language
    is_library: bool
    frame_depth: int          # 1 = closest to error
    raw_line: str

class SentryEvent(BaseModel):
    error_type: str
    error_message: str
    culprit: str | None
    environment: str | None
    frames: list[StackFrame]
    sentry_issue_url: str | None
    
class MRContext(BaseModel):
    iid: int
    title: str
    description: str
    author_username: str
    merged_at: datetime | None
    web_url: str
    linked_issues: list[LinkedIssue]
    reviewers: list[str]
    days_since_merge: int

class LinkedIssue(BaseModel):
    iid: int
    title: str
    web_url: str
    state: str  # opened | closed

class SymbolHistory(BaseModel):
    function_name: str
    file_path: str
    recent_mrs: list[MRContext]
    caller_count: int
    orbit_miss: bool          # True if Orbit returned no results
    fallback_used: bool       # True if file-level fallback was used

class BlameEntry(BaseModel):
    frame: StackFrame
    history: SymbolHistory
    primary_mr: MRContext | None  # most recent MR
    confidence: float
    confidence_label: Literal["HIGH", "MEDIUM", "LOW"]
    confidence_reason: str

class BlameChain(BaseModel):
    entries: list[BlameEntry]
    primary_suspect: BlameEntry | None
    frames_analyzed: int
    frames_total: int
    orbit_misses: int
    generated_at: datetime
```

#### 7. Orbit API Response Handling

The Orbit REST API returns a graph result object. Normalize it before use:

```python
# Raw Orbit response shape
{
  "data": {
    "nodes": [
      {"id": "mr:1234", "type": "MergeRequest", "properties": {...}},
      ...
    ],
    "edges": [
      {"source": "mr:1234", "target": "wi:89", "type": "CLOSES"},
      ...
    ]
  },
  "meta": {
    "query_time_ms": 142,
    "node_count": 7,
    "edge_count": 4
  }
}
```

Always validate:
- `data` key exists (Orbit returns `{"error": ...}` on malformed queries)
- Node `type` matches expected before accessing `properties`
- `merged_at` is parseable as ISO 8601 before constructing `datetime`
- `iid` is numeric (can come as string from ClickHouse)

#### 8. GitLab Issue Update

Use the GitLab REST API to add a comment:

```
POST /api/v4/projects/{project_id}/issues/{issue_iid}/notes
{
  "body": "{rendered_markdown}"
}
```

Then add the `rootchain-analyzed` label:

```
PUT /api/v4/projects/{project_id}/issues/{issue_iid}
{
  "add_labels": "rootchain-analyzed"
}
```

Both calls use `ROOTCHAIN_GITLAB_TOKEN` (needs `api` scope).

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Agent Platform | GitLab Duo Agent Platform | Required by hackathon; native Orbit integration |
| Knowledge Graph | GitLab Orbit (Remote) | SDLC graph traversal across MRs, issues, users, symbols |
| Error Tracking | Sentry | Ubiquitous; native GitLab integration creates issues automatically |
| Language | Python 3.11+ | Async-native, excellent httpx + Pydantic ecosystem |
| HTTP Client | httpx | Async-first, built-in retry, proper connection pooling |
| Data Validation | Pydantic v2 | Model validation, JSON parsing, serialization |
| Retries | tenacity | Declarative retry/backoff without boilerplate |
| Logging | structlog | Structured JSON logs, easy to forward to any sink |
| Testing | pytest + pytest-asyncio | Async test support |
| CI | GitLab CI/CD | Self-hosted validation pipeline |
| Optional receiver | FastAPI | Fallback webhook receiver if native Sentry integration unavailable |

---

## Project Structure

```
rootchain/
│
├── README.md                              ← You are here
├── CLAUDE.md                              ← Instructions for Claude Code
├── AGENTS.md                              ← Instructions for any AI agent
├── LICENSE                                ← MIT
│
├── .gitlab/
│   ├── duo-flows/
│   │   └── rootchain.yml                 ← Duo Agent Platform flow definition (PRIMARY ARTIFACT)
│   └── skills/
│       └── rootchain/
│           └── SKILL.md                  ← Agent skill: parsing + Orbit interpretation rules
│
├── .gitlab-ci.yml                         ← CI: lint, test, validate flow YAML, integration smoke test
│
├── src/
│   └── rootchain/
│       ├── __init__.py
│       ├── config.py                      ← Config loading (env vars → Config dataclass)
│       ├── models.py                      ← All Pydantic models (single source of truth)
│       ├── sentry_parser.py               ← Parse stack traces from issue descriptions
│       ├── orbit_client.py                ← Orbit REST API client (queries, retries, caching)
│       ├── blame_chain.py                 ← Confidence scoring + blame chain construction
│       ├── issue_formatter.py             ← Render BlameChain → Markdown comment
│       ├── gitlab_client.py               ← GitLab API client (notes, labels)
│       └── orchestrator.py               ← Entry point: wire everything together
│
├── receiver/                              ← OPTIONAL: fallback webhook receiver
│   ├── main.py                            ← FastAPI app
│   ├── requirements.txt
│   ├── Dockerfile
│   └── fly.toml                           ← Deploy to Fly.io (free tier)
│
├── scripts/
│   ├── validate_flow.py                   ← Validate rootchain.yml against Duo Platform schema
│   ├── test_orbit_connection.py           ← Smoke test: verify Orbit is reachable + enabled
│   └── generate_test_issue.py            ← Create a test Sentry-format issue in GitLab (for demo)
│
├── tests/
│   ├── conftest.py                        ← Fixtures: mock Orbit responses, sample Sentry events
│   ├── fixtures/
│   │   ├── sentry_python.json            ← Python Sentry event payload
│   │   ├── sentry_node.json              ← Node.js Sentry event payload
│   │   ├── sentry_go.json                ← Go Sentry event payload
│   │   ├── sentry_minified_js.json       ← Minified JS (edge case: no readable frames)
│   │   ├── orbit_response_full.json      ← Full Orbit API response with MR + issues + users
│   │   ├── orbit_response_empty.json     ← Orbit returns no results (orbit_miss case)
│   │   └── gitlab_issue_sentry.json      ← Sample GitLab issue created by Sentry integration
│   ├── unit/
│   │   ├── test_sentry_parser.py
│   │   ├── test_orbit_client.py
│   │   ├── test_blame_chain.py
│   │   └── test_issue_formatter.py
│   └── integration/
│       └── test_orchestrator.py          ← Requires ROOTCHAIN_ORBIT_TOKEN + test project
│
├── docs/
│   ├── configuration.md                  ← All env vars explained
│   ├── orbit_queries.md                  ← All Cypher queries with examples
│   ├── sentry_setup.md                   ← Step-by-step Sentry integration guide
│   ├── ai_catalog_publish.md             ← How to publish to GitLab AI Catalog
│   └── troubleshooting.md               ← Common errors + fixes
│
└── pyproject.toml                         ← Project metadata, deps, ruff config, pytest config
```

---

## Prerequisites

Before you start, ensure you have:

| Requirement | Minimum Version | Purpose |
|-------------|----------------|---------|
| Python | 3.11+ | Runtime |
| `glab` CLI | Latest | GitLab CLI for local Orbit testing |
| GitLab tier | **GitLab.com Premium** or self-managed Ultimate | Orbit Remote requires ClickHouse backend |
| GitLab Orbit | Enabled on group | Core data source |
| GitLab Duo | Enabled for the project | Agent Platform prerequisite |
| Sentry | Any plan | Error source (self-hosted works too) |
| Access token | `api` scope | Both Orbit queries and issue updates |

**Check Orbit is available:**
```bash
curl -s \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.com/api/v4/orbit/status" \
| jq '.status'
# Should return "healthy"
```

**Check Orbit is enabled on your group:**
```bash
curl -s \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.com/api/v4/groups/{group_id}/orbit/status" \
| jq '.indexing_status'
# Should return "indexed" or "indexing"
```

---

## Installation & Setup

### Step 1: Fork and clone this repository

```bash
git clone https://gitlab.com/YOUR_USERNAME/rootchain.git
cd rootchain
```

### Step 2: Install Python dependencies

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### Step 3: Enable GitLab Orbit on your group

1. Go to **your-group → Settings → AI & Analytics → Orbit**
2. Enable Orbit indexing
3. Wait for initial indexing to complete (can take 10–30 minutes for large groups)
4. Verify: `python scripts/test_orbit_connection.py`

### Step 4: Configure GitLab CI/CD variables

In your forked project, go to **Settings → CI/CD → Variables** and add:

| Variable | Value | Masked | Protected |
|----------|-------|--------|-----------|
| `ROOTCHAIN_GITLAB_TOKEN` | A PAT with `api` scope | ✅ | ✅ |
| `ROOTCHAIN_GITLAB_URL` | `https://gitlab.com` (or your self-managed URL) | ❌ | ❌ |
| `ROOTCHAIN_GROUP_PATH` | `your-group` (top-level group with Orbit enabled) | ❌ | ❌ |
| `ROOTCHAIN_PROJECT_PATH` | `your-group/your-project` (where Sentry issues land) | ❌ | ❌ |
| `ROOTCHAIN_ORBIT_TIMEOUT_SECONDS` | `30` | ❌ | ❌ |
| `ROOTCHAIN_MAX_FRAMES` | `5` | ❌ | ❌ |
| `ROOTCHAIN_CONFIDENCE_THRESHOLD` | `0.4` | ❌ | ❌ |

### Step 5: Configure the Duo Agent Platform flow

The flow is defined in `.gitlab/duo-flows/rootchain.yml`. It is automatically picked up by the Duo Agent Platform when present in the project. No additional registration step is required.

Verify the flow is recognized:
1. Go to **your-project → Duo Agent Platform → Flows**
2. You should see `rootchain` in the list
3. Status should be `active`

### Step 6: Connect Sentry

**Option A — Native Sentry–GitLab integration (recommended):**

1. In Sentry: **Settings → Integrations → GitLab**
2. Connect your GitLab account (OAuth)
3. Choose the GitLab project where issues should be created
4. In Sentry alert rules: add action **"Create a GitLab issue"** for the desired alert rule
5. Set the label to `sentry-alert` in the issue creation settings

Sentry creates issues with the title format: `[Sentry] ErrorType: message`  
The label `Sentry` is added automatically; we also need `sentry-alert`. Configure Sentry to add this label, or add a GitLab label event trigger that auto-adds `sentry-alert` whenever a `Sentry` label is added.

**Option B — Webhook receiver (if native integration unavailable):**

Deploy the receiver:
```bash
cd receiver/
# Edit fly.toml: set app name, add env vars
flyctl deploy
```

In Sentry: **Settings → Developer Settings → Internal Integrations → New**
- Add webhook URL: `https://your-receiver.fly.dev/webhook/sentry`
- Event: `issue` (created + triggered)
- Add header: `X-Rootchain-Secret: {your_secret}`

Add to CI variables: `ROOTCHAIN_WEBHOOK_SECRET`

### Step 7: Verify end-to-end

Run the test issue generator to simulate a Sentry alert:
```bash
python scripts/generate_test_issue.py \
  --project-path "your-group/your-project" \
  --token "$ROOTCHAIN_GITLAB_TOKEN"
```

This creates a GitLab issue with a realistic Sentry format. Within ~2 minutes, the flow should activate and post a RootChain analysis comment.

---

## Configuration Reference

All configuration is driven by environment variables. A local `.env` file is supported for development (never commit this file).

```bash
# .env.example — copy to .env and fill in

# ── Required ────────────────────────────────────────────────────────
ROOTCHAIN_GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx   # PAT: api scope
ROOTCHAIN_GITLAB_URL=https://gitlab.com             # Base URL
ROOTCHAIN_GROUP_PATH=my-org                         # Top-level group with Orbit
ROOTCHAIN_PROJECT_PATH=my-org/my-app                # Target project for issue updates

# ── Orbit ───────────────────────────────────────────────────────────
ROOTCHAIN_ORBIT_TIMEOUT_SECONDS=30    # Per-query timeout (int, 5–120)
ROOTCHAIN_ORBIT_MAX_RETRIES=3         # Retry attempts on timeout/5xx
ROOTCHAIN_ORBIT_RETRY_BASE_SECONDS=2  # Exponential backoff base

# ── Parsing ─────────────────────────────────────────────────────────
ROOTCHAIN_MAX_FRAMES=5                # Max frames to analyze (int, 1–10)
ROOTCHAIN_INCLUDE_LIBRARY_FRAMES=false  # Include library frames (bool)

# ── Scoring ─────────────────────────────────────────────────────────
ROOTCHAIN_CONFIDENCE_THRESHOLD=0.4   # Min confidence to show in output (float, 0–1)
ROOTCHAIN_RECENCY_WEIGHT=0.5         # Weight of recency in confidence (float)
ROOTCHAIN_DEPTH_WEIGHT=0.35          # Weight of frame depth in confidence (float)
ROOTCHAIN_BLAST_WEIGHT=0.15          # Weight of caller count in confidence (float)
ROOTCHAIN_RECENCY_HALF_LIFE_DAYS=30  # Days until recency score halves (int)

# ── Output ──────────────────────────────────────────────────────────
ROOTCHAIN_ADD_LABEL=rootchain-analyzed          # Label to add after analysis
ROOTCHAIN_MENTION_AUTHORS=true                  # @mention MR authors in comment
ROOTCHAIN_MENTION_REVIEWERS=false               # @mention reviewers (can be noisy)
ROOTCHAIN_MAX_MENTION_USERS=3                   # Max users to @mention

# ── Webhook Receiver (Option B only) ────────────────────────────────
ROOTCHAIN_WEBHOOK_SECRET=your-secret-here       # HMAC secret for Sentry webhook
ROOTCHAIN_WEBHOOK_PORT=8080

# ── Logging ─────────────────────────────────────────────────────────
ROOTCHAIN_LOG_LEVEL=INFO           # DEBUG | INFO | WARNING | ERROR
ROOTCHAIN_LOG_FORMAT=json          # json | console (use console for local dev)
```

---

## GitLab Duo Agent Platform Flow

### Flow Definition (`.gitlab/duo-flows/rootchain.yml`)

```yaml
name: rootchain
description: >
  RootChain traces production Sentry errors to their SDLC origin.
  When Sentry creates a GitLab issue for a production alert, this flow
  queries GitLab Orbit to find which MRs last modified each stack frame,
  what work items motivated those changes, and who the relevant authors
  and reviewers are.
version: 1

trigger:
  event: work_item_created

filter:
  # Only activate for issues with the sentry-alert label
  # (set by Sentry's native GitLab integration or the webhook receiver)
  labels:
    any_of:
      - sentry-alert
      - Sentry
  # Additional guard: title must look like a Sentry error
  # This prevents accidental triggers on manually created issues
  title_matches: '^\[Sentry\]|\[Error\]|TypeError|ValueError|NullPointerException'

context:
  goal: |
    A Sentry production error has been automatically filed as a GitLab issue.

    Issue details:
    - IID: {{ .WorkItem.IID }}
    - Title: {{ .WorkItem.Title }}
    - Project: {{ .WorkItem.Project.FullPath }}
    - Web URL: {{ .WorkItem.WebURL }}
    - Labels: {{ .WorkItem.Labels | join ", " }}

    Full issue description (contains the Sentry stack trace):
    ---
    {{ .WorkItem.Description }}
    ---

    Your task:
    1. Check if this issue already has the label "rootchain-analyzed". If yes, stop immediately.
    2. Parse the Sentry error information from the issue description above.
    3. Extract up to {{ env "ROOTCHAIN_MAX_FRAMES" | default "5" }} non-library stack frames.
    4. For each frame, use the Orbit knowledge graph to find recent MRs that modified
       the function, the work items those MRs were linked to, and the authors/reviewers.
    5. Build a confidence-ranked blame chain.
    6. Post a structured analysis comment on the issue.
    7. Add the label "rootchain-analyzed" to the issue.

steps:
  - name: parse_and_trace
    type: agent
    description: >
      Parse the Sentry event and query Orbit for each stack frame.
      Construct a blame chain ranked by confidence.
    skills:
      - rootchain
    tools:
      - query_graph          # Orbit MCP tool — native to Duo Agent Platform
      - create_note          # Add comment to a GitLab issue
      - add_label            # Add label to a GitLab issue
      - get_issue            # Read the current issue state
    max_iterations: 20       # Prevent infinite loops
    timeout_seconds: 120     # 2 minute hard limit
```

### Key Flow Design Decisions

**Why `work_item_created` and not a pipeline trigger?**  
Sentry's native GitLab integration already creates issues. Using `work_item_created` requires zero additional infrastructure. A pipeline trigger would require a receiver service and adds a network hop.

**Why label filtering instead of title-only filtering?**  
Labels are set programmatically by Sentry and are reliable. Title patterns are a fallback for orgs that configure Sentry without standard labels. Using `any_of` catches both.

**Why the idempotency guard?**  
Sentry sometimes re-fires the same alert if an issue is reopened. The label check ensures the flow runs exactly once per issue, regardless of Sentry's behavior.

**Why `max_iterations: 20`?**  
Each Orbit query is one iteration. 5 frames × 3 queries each (primary, linked issues, reviewers) = 15 queries plus parsing and formatting = ~18 total. 20 gives a small buffer.

---

## Orbit Integration

### Enabling Orbit on your group

```bash
# Via GitLab API
curl --request POST \
  --header "PRIVATE-TOKEN: $ROOTCHAIN_GITLAB_TOKEN" \
  --header "Content-Type: application/json" \
  --data '{"enabled": true}' \
  "https://gitlab.com/api/v4/groups/YOUR_GROUP_ID/orbit/settings"
```

### Orbit API Endpoint

All Orbit queries go to:
```
POST https://gitlab.com/api/v4/orbit/query
Content-Type: application/json
PRIVATE-TOKEN: {token}

{
  "query": "MATCH (d:Definition ...) RETURN ...",
  "parameters": { ... },
  "timeout": 30000
}
```

The query language is Cypher-like (based on GitLab's internal graph DSL). Always use parameterized queries — never string-concatenate user input into queries.

### Orbit Schema Reference

Verify the live schema for your instance:
```bash
curl -s \
  --header "PRIVATE-TOKEN: $ROOTCHAIN_GITLAB_TOKEN" \
  "https://gitlab.com/api/v4/orbit/schema" \
  | jq '.domains'
```

**Key node types:**

| Domain | Node | Key properties |
|--------|------|----------------|
| `source_code` | `Definition` | `name`, `kind` (function/class/method), `file_path`, `line_start` |
| `source_code` | `File` | `path`, `language`, `project_full_path` |
| `source_code` | `ImportedSymbol` | `name`, `source_path` |
| `code_review` | `MergeRequest` | `iid`, `title`, `description`, `author_username`, `merged_at`, `web_url`, `project_full_path` |
| `code_review` | `MergeRequestDiffFile` | `old_path`, `new_path`, `change_type` |
| `plan` | `WorkItem` | `iid`, `title`, `description`, `state`, `web_url` |
| `core` | `User` | `username`, `name`, `web_url` |
| `ci` | `Pipeline` | `id`, `status`, `ref`, `created_at` |
| `ci` | `Job` | `name`, `status`, `stage`, `duration` |
| `security` | `Vulnerability` | `name`, `severity`, `state`, `report_type` |

**Key edge types:**

| Edge | From → To | Meaning |
|------|-----------|---------|
| `DEFINED_IN` | Definition → File | Symbol defined in file |
| `CALLS` | Definition → Definition | Function calls function |
| `MODIFIES_FILE` | MergeRequest → File | MR changed this file |
| `AUTHORED_BY` | MergeRequest → User | MR author |
| `REVIEWED_BY` | User → MergeRequest | User reviewed MR |
| `CLOSES` | MergeRequest → WorkItem | MR closes issue |
| `MENTIONS` | MergeRequest → WorkItem | MR mentions issue |
| `IMPORTS` | File → ImportedSymbol | File imports symbol |

### All Orbit Queries Used by RootChain

See `docs/orbit_queries.md` for the complete annotated query library. The four core queries are summarized in the LLD section above.

---

## Sentry Integration

### What Sentry's native GitLab integration creates

When you configure Sentry → GitLab issue creation, a new GitLab issue is created with:

```
Title:       [Sentry] TypeError: Cannot read property 'id' of undefined
Labels:      Sentry (added by Sentry integration)
Description: (see below)
```

```markdown
## TypeError: Cannot read property 'id' of undefined

**Sentry Issue:** https://sentry.io/organizations/your-org/issues/1234567/

**Culprit:** `payments/processor.py in processPayment`

**Times seen:** 47  
**Users affected:** 12  
**Environment:** production  
**First seen:** 2024-01-15T02:14:37Z  
**Last seen:** 2024-01-15T02:47:12Z  

### Stacktrace

```
Traceback (most recent call last):
  File "/app/payments/processor.py", line 142, in processPayment
    result_id = gateway_response['id']
  File "/app/payments/gateway.py", line 88, in call_gateway
    return self._session.post(url, data=payload)
  File "/app/core/session.py", line 34, in post
    return requests.post(self.base_url + path, **kwargs)
  File "/usr/local/lib/python3.11/site-packages/requests/api.py", line 73, in post
    return request('post', url, data=data, json=json, **kwargs)
```
```

**This format is stable** — parse with `SentryParser.parse_from_issue_description()`.

### Adding the `sentry-alert` label automatically

In your GitLab project: **Settings → Labels** → Create label `sentry-alert` (color: red).

Then: **Settings → Integrations → Pipeline status emails** (or use label events) to auto-add `sentry-alert` whenever label `Sentry` is added. Alternatively, configure Sentry to add `sentry-alert` directly in its GitLab integration settings under "Additional labels".

### Webhook Receiver (Option B)

If you can't use native integration, deploy `receiver/main.py`:

```python
# receiver/main.py structure
POST /webhook/sentry
  → validate HMAC signature (X-Sentry-Hook-Signature header)
  → parse SentryWebhookPayload
  → extract: event.type, event.culprit, event.title, stacktrace
  → create GitLab issue via API with Sentry data in description
  → add labels: sentry-alert, Sentry
  → return 200 OK

GET /health
  → return {"status": "ok", "version": "..."}
```

---

## Blame Chain Algorithm

### Confidence Score

Each blame entry is scored 0.0–1.0:

```
recency  = 1 / (1 + days_since_merge / HALF_LIFE_DAYS)
           # 0 days → 1.0, 30 days → 0.5, 90 days → 0.25

depth    = 1 / frame_depth
           # frame 1 (closest to error) → 1.0, frame 5 → 0.2

blast    = min(caller_count / 10.0, 1.0)
           # 0 callers → 0.0, 5 callers → 0.5, 10+ callers → 1.0

confidence = (recency × W_RECENCY) + (depth × W_DEPTH) + (blast × W_BLAST)
           # Weights configurable via env vars, default: 0.5 / 0.35 / 0.15

# If orbit_miss is True: confidence = 0.0 (we have no data, don't guess)
# If fallback_used is True: multiply by 0.7 (file-level match is less precise)
```

### Why these weights?

- **Recency (50%):** A change from 4 days ago is far more likely to cause a new error than one from 6 months ago. Weighted highest.
- **Frame depth (35%):** The error throws in frame 1. Frame 1's last modifier is more likely culpable than frame 5's.
- **Caller count (15%):** High caller count means the function is critical, but it also means many MRs have touched it. Lower weight because it's a signal of importance, not causation.

### Primary Suspect Selection

The `primary_suspect` is the `BlameEntry` with the highest `confidence` score AND `confidence >= ROOTCHAIN_CONFIDENCE_THRESHOLD`. If no entry meets the threshold, `primary_suspect` is `None` and the comment note reads "RootChain could not identify a primary suspect with sufficient confidence."

### Comment on Idempotency in Scoring

If two frames point to the same MR (the MR touched multiple files in the stack), their entries are **merged** — the MR appears once with the maximum confidence across its frames. This prevents the same MR from appearing twice in the blame table.

---

## Edge Cases & Handling

| Edge Case | Detection | Handling |
|-----------|-----------|----------|
| **Issue already analyzed** | Label `rootchain-analyzed` present | Exit immediately, no comment added |
| **No stack trace in issue** | `SentryParser` returns `None` | Comment: "No parseable stack trace found." + label applied |
| **All frames are library code** | 0 frames after filtering | Comment: "All frames are library code. Enable source maps or check filter config." |
| **Minified JS (no function names)** | `function_name` is `<anonymous>` or empty | Skip frame, note in comment: "X frames skipped (minified). Enable Sentry source maps." |
| **Orbit not enabled on group** | `GET /api/v4/orbit/status` returns non-healthy | Comment: "Orbit is not enabled on this group. See setup guide." + fail gracefully |
| **Orbit returns 0 results for symbol** | Empty `nodes` in response | `orbit_miss=True`, try file-level fallback; if still 0, mark as "Not in Orbit index" |
| **Orbit API timeout** | httpx `ReadTimeout` after 30s | Retry 3× with exponential backoff; on final failure, mark frame as `orbit_unavailable` |
| **Orbit API rate limit (429)** | HTTP 429 response | Respect `Retry-After` header; wait and retry |
| **Orbit API 5xx** | HTTP 500–599 | Retry 3× same as timeout |
| **MR has no linked issues** | Empty `WorkItem` list from secondary query | Show MR without issue link; don't fabricate intent |
| **Same MR across multiple frames** | Duplicate `mr.iid` in results | Merge entries, use max confidence, show once |
| **Stack trace is 50+ frames deep** | `len(raw_frames) > MAX_FRAMES` | Take top `MAX_FRAMES` non-library frames, note how many were omitted |
| **Function appears in multiple files** | Multiple `Definition` nodes for same name | Return all, prefer the one in the same directory as the error's culprit file |
| **Unicode in function/file names** | Non-ASCII in `function_name` or `file_path` | Handle natively (Python str handles Unicode); ensure Orbit query is URL-encoded |
| **Sentry issue fired twice for same error** | Second `work_item_created` on updated issue | Idempotency guard (label check) prevents double-analysis |
| **GitLab API rate limit** | HTTP 429 on issue note creation | Retry with `Retry-After`; log warning |
| **Missing `api` scope on token** | HTTP 403 on note creation | Fail with clear error: "Token missing `api` scope. Check ROOTCHAIN_GITLAB_TOKEN." |
| **Project not under Orbit-enabled group** | Orbit returns empty for all queries | Comment: "Project may not be under the Orbit-indexed group. Check ROOTCHAIN_GROUP_PATH." |
| **Error in Go with goroutine prefix** | `goroutine N [...]` header before frames | Strip goroutine header before parsing frames |
| **Java exception chaining (`Caused by:`)** | Multiple exception blocks | Parse each `Caused by` block; use the root cause block as primary |
| **Orbit symbol indexed from different branch** | Definition found but line numbers differ | Note: "Symbol found, but indexing may be from a different branch. Orbit indexes default branch only." |
| **Very new code not yet indexed by Orbit** | `merged_at` of MR is < 24h ago | `orbit_miss=True` with reason: "Code may not be indexed yet. Orbit indexes on a cycle." |

---

## Coding Practices

### General

- **Python 3.11+**: Use `match` statements, `ExceptionGroup`, `Self` type, `tomllib`, variadic generics where appropriate.
- **Type hints everywhere**: All functions, all parameters, all return values. No bare `Any` except at JSON parsing boundaries (where Pydantic takes over immediately).
- **Pydantic v2 models**: Use `model_validator`, `field_validator`, `model_config`. Never use `dict` for structured data — always a model.
- **No mutable default arguments**: Use `None` defaults and initialize inside function.
- **Early returns**: Validate and return (or raise) at the top of functions. No deeply nested if-else pyramids.
- **Single responsibility**: Each file does one thing. `sentry_parser.py` only parses. `orbit_client.py` only queries Orbit.

### Error Handling

- Use a `Result` pattern for operations that can fail gracefully:

```python
from dataclasses import dataclass
from typing import TypeVar, Generic

T = TypeVar("T")

@dataclass
class Ok(Generic[T]):
    value: T

@dataclass
class Err:
    message: str
    code: str                  # e.g. "orbit_timeout", "no_stack_trace"
    retryable: bool = False

type Result[T] = Ok[T] | Err
```

- Never swallow exceptions silently. Always log at minimum with `structlog`.
- Distinguish retryable errors (network, 5xx) from permanent errors (4xx, bad input).
- Every external API call is wrapped in `try/except` with specific exception types.

### Async

- All I/O is async. Use `httpx.AsyncClient` everywhere.
- Never use `asyncio.run()` inside library code — only in entry points.
- Use `asyncio.gather()` for parallel Orbit queries (one per frame).
- Set `limits=httpx.Limits(max_connections=10, max_keepalive_connections=5)` on the shared client.

### Logging

```python
import structlog

log = structlog.get_logger()

# Always log with context, never with string formatting:
log.info("orbit_query_complete",
    function_name=frame.function_name,
    file_path=frame.file_path,
    mr_count=len(result.recent_mrs),
    query_time_ms=elapsed_ms,
)

# Never:
log.info(f"Orbit query for {frame.function_name} returned {len(result)} MRs")
```

### Configuration

All config is loaded exactly once at startup via `Config.from_env()`. Never call `os.getenv()` outside of `config.py`. The `Config` object is passed explicitly to components — no global state.

```python
@dataclass(frozen=True)
class Config:
    gitlab_token: str
    gitlab_url: str
    group_path: str
    project_path: str
    orbit_timeout: int = 30
    orbit_max_retries: int = 3
    max_frames: int = 5
    # ... etc
    
    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            gitlab_token=_require_env("ROOTCHAIN_GITLAB_TOKEN"),
            gitlab_url=os.getenv("ROOTCHAIN_GITLAB_URL", "https://gitlab.com"),
            group_path=_require_env("ROOTCHAIN_GROUP_PATH"),
            project_path=_require_env("ROOTCHAIN_PROJECT_PATH"),
            # ... parse and validate each field
        )
```

### Testing

- Aim for **80%+ unit test coverage** across `src/rootchain/`.
- Use `pytest-asyncio` for all async tests.
- Mock all external calls (Orbit, GitLab) in unit tests using `httpx.MockTransport` or `respx`.
- Keep fixtures in `tests/fixtures/*.json` — never hardcode sample data in test files.
- Integration tests (in `tests/integration/`) are skipped unless `ROOTCHAIN_INTEGRATION_TESTS=1` is set.
- Every edge case in the "Edge Cases" section above must have at least one unit test.

### Reusability

- `OrbitClient` is framework-agnostic — it only depends on `httpx` and `Config`. It can be imported into other projects.
- `SentryParser` has no external dependencies beyond `re` and Pydantic. It is independently useful.
- `BlameChainBuilder` takes `SentryEvent` and `list[SymbolHistory]` — pure functions with no I/O.
- `IssueFormatter` takes `BlameChain` and returns `str` — pure, no I/O.

All I/O happens only in `OrbitClient`, `GitLabClient`, and `orchestrator.py`.

---

## Testing

### Unit tests

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run with coverage
pytest tests/unit/ --cov=src/rootchain --cov-report=term-missing

# Run a specific test
pytest tests/unit/test_sentry_parser.py::test_parse_python_stacktrace -v
```

### Integration tests

Requires a real GitLab project with Orbit enabled:
```bash
export ROOTCHAIN_INTEGRATION_TESTS=1
export ROOTCHAIN_GITLAB_TOKEN=glpat-xxx
export ROOTCHAIN_GROUP_PATH=your-group
export ROOTCHAIN_PROJECT_PATH=your-group/your-project
pytest tests/integration/ -v
```

### Manual end-to-end test

```bash
# Create a test issue that looks like a Sentry alert
python scripts/generate_test_issue.py \
  --project-path "your-group/your-project" \
  --token "$ROOTCHAIN_GITLAB_TOKEN" \
  --language python

# Watch the flow activate (takes up to 2 minutes)
# Then check the issue for the RootChain comment
```

### Test fixtures

All fixtures in `tests/fixtures/` represent real-world samples:
- `sentry_python.json`: Python Flask app TypeError
- `sentry_node.json`: Node.js Express app ReferenceError
- `sentry_go.json`: Go service panic with goroutine prefix
- `sentry_minified_js.json`: React app with no readable frame names (source maps missing)
- `orbit_response_full.json`: Full response with MR, linked issue, and reviewer
- `orbit_response_empty.json`: Orbit returns no results (orbit_miss case)
- `gitlab_issue_sentry.json`: Raw GitLab issue payload as created by Sentry integration

---

## Deployment

### GitLab CI/CD pipeline (`.gitlab-ci.yml`)

```yaml
stages:
  - lint
  - test
  - validate
  - smoke

lint:
  stage: lint
  image: python:3.11-slim
  script:
    - pip install ruff mypy
    - ruff check src/ tests/
    - mypy src/rootchain/

test:unit:
  stage: test
  image: python:3.11-slim
  script:
    - pip install -e ".[dev]"
    - pytest tests/unit/ --cov=src/rootchain --cov-fail-under=80

validate:flow:
  stage: validate
  image: python:3.11-slim
  script:
    - pip install -e ".[dev]"
    - python scripts/validate_flow.py .gitlab/duo-flows/rootchain.yml

smoke:orbit:
  stage: smoke
  image: python:3.11-slim
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
  script:
    - pip install -e ".[dev]"
    - python scripts/test_orbit_connection.py
  variables:
    ROOTCHAIN_GITLAB_TOKEN: $ROOTCHAIN_GITLAB_TOKEN
    ROOTCHAIN_GROUP_PATH: $ROOTCHAIN_GROUP_PATH
```

### Webhook receiver (Option B) — Fly.io

```bash
cd receiver/
fly launch --name rootchain-receiver --region sin  # Singapore
fly secrets set ROOTCHAIN_GITLAB_TOKEN="glpat-xxx"
fly secrets set ROOTCHAIN_WEBHOOK_SECRET="your-secret"
fly secrets set ROOTCHAIN_GITLAB_URL="https://gitlab.com"
fly secrets set ROOTCHAIN_PROJECT_PATH="your-group/your-project"
fly deploy
```

The free Fly.io plan is sufficient — this receiver is stateless and low-traffic.

---

## Publishing to the GitLab AI Catalog

The hackathon requires at least one agent or flow to be published to the AI Catalog.

1. Ensure the project is **public** with MIT license
2. In your GitLab project: **Duo Agent Platform → Flows → rootchain → Publish to AI Catalog**
3. Fill in:
   - **Display name:** RootChain
   - **Tagline:** Trace Sentry production errors to their SDLC origin via GitLab Orbit
   - **Category:** DevSecOps / Incident Response
   - **Tags:** `orbit`, `sentry`, `incident-response`, `blame-chain`, `sdlc`
4. Submit for review

Alternatively, via API:
```bash
curl --request POST \
  --header "PRIVATE-TOKEN: $ROOTCHAIN_GITLAB_TOKEN" \
  --header "Content-Type: application/json" \
  --data '{
    "flow_name": "rootchain",
    "display_name": "RootChain",
    "description": "Trace production Sentry errors to SDLC blame chains via GitLab Orbit",
    "tags": ["orbit", "sentry", "incident-response"]
  }' \
  "https://gitlab.com/api/v4/ai_catalog/flows"
```

---

## Troubleshooting

### "Orbit status is not healthy"
- Check that Orbit is enabled on the group (not just the project)
- Orbit requires GitLab.com Premium or self-managed Ultimate
- Initial indexing can take up to 30 minutes for large groups

### "Flow did not activate after issue creation"
- Verify the issue has at least one of the trigger labels (`sentry-alert` or `Sentry`)
- Check **Project → Duo Agent Platform → Flows → rootchain → Logs**
- Ensure GitLab Duo is enabled for the project

### "Orbit queries return 0 results"
- Check that the file path in the stack trace matches what Orbit has indexed
- Orbit indexes the **default branch only** — ensure code is on `main`/`master`
- New code merged less than ~1 hour ago may not be indexed yet

### "TypeError on frame parsing"
- Run the Sentry issue description through `SentryParser.debug_parse(description)` locally
- Check `tests/fixtures/` for the closest matching sample and compare formats
- Add a new fixture if you've found a new Sentry format variant

### "GitLab API 403 on issue update"
- The token needs `api` scope (not just `read_api`)
- Ensure the token has access to the target project
- For group-level tokens: ensure group-level API access is enabled

### "Confidence scores are all 0.0"
- This typically means `orbit_miss=True` for all frames
- Check if the project's code is under the `ROOTCHAIN_GROUP_PATH` group
- Enable `ROOTCHAIN_LOG_LEVEL=DEBUG` and inspect Orbit query responses

---

## FAQ

**Q: Does RootChain work without Sentry?**  
A: Yes. Any GitLab issue with a stack trace in the description and the `sentry-alert` label will trigger the flow. You can create these manually or use a different error tracking tool's GitLab integration.

**Q: Does RootChain work with GitLab self-managed?**  
A: Yes, if your instance has Orbit Remote enabled (requires Ultimate tier with ClickHouse). Set `ROOTCHAIN_GITLAB_URL` to your instance URL.

**Q: What languages are supported?**  
A: Python, Node.js/JavaScript/TypeScript, Go, Ruby, Java. Go adds goroutine header parsing; Java adds `Caused by:` chain handling. Unknown languages attempt generic frame detection.

**Q: What happens if the MR has no linked issues?**  
A: RootChain shows the MR title and author without issue context. It will not fabricate intent.

**Q: Can I disable @mentions?**  
A: Set `ROOTCHAIN_MENTION_AUTHORS=false`. Useful in high-alert-volume projects.

**Q: How do I tune for a monorepo?**  
A: Set `ROOTCHAIN_GROUP_PATH` to the top-level group. Orbit Remote indexes the entire group, so monorepo projects are handled automatically.

---

## License

MIT — see [LICENSE](LICENSE).

---

## What's Next

RootChain demonstrates a pattern — **inverse debugging via SDLC graph traversal** — that extends well beyond Sentry alerts. Planned extensions:

### Immediate (next sprint)
- **PagerDuty / OpsGenie webhook receiver** — same flow, different alert source
- **Slack integration** — post the blame chain to `#incidents` alongside the GitLab issue link
- **Auto-assign** — set the issue assignee to the primary suspect's MR author (configurable)
- **GitLab runbooks** — if the blamed MR has a linked runbook, surface it in the comment
- **Java `Caused by:` chain multi-root** — trace all exception layers, not just the outermost

### Medium-term
- **Security triage** — the same Orbit traversal from CVE advisory → file → MR → author tells you exactly who introduced a vulnerability and what business change motivated it
- **CI failure attribution** — when a pipeline fails on `main`, trace failing test files through the same graph to find the MR that broke the build
- **Coverage delta** — query Orbit's CI domain to show whether the blamed MR's code had test coverage and whether coverage dropped
- **Confidence history** — store RootChain comment scores in a GitLab custom property; over time, identify which functions are "serial suspects" that need refactoring

### Architecture extensions
- **Multi-language Orbit domains** — Orbit's `security` domain (Vulnerabilities), `ci` domain (Pipelines/Jobs), and `plan` domain (iterations/epics) open new traversal paths not yet used by RootChain
- **AI Catalog distribution** — publish RootChain as a reusable flow that any GitLab group can install with one click and immediately use with their own Sentry + Orbit setup

---

## Why This Is Non-Obvious

Most Orbit use cases are forward queries: "what changed recently?" or "who owns this file?" RootChain inverts the direction: it starts from a **runtime signal** (a production error) and walks backward through the SDLC graph to find the **causal human decision**.

The key insight is the multi-hop path:

```
TypeError at runtime
  → stack frame: processPayment() in payments/processor.py
  → Orbit: Definition[processPayment] -[:DEFINED_IN]→ File[processor.py]
  → Orbit: File[processor.py] ←[:MODIFIES_FILE]- MergeRequest[!342]
  → Orbit: MergeRequest[!342] -[:CLOSES]→ WorkItem[#89: "Add retry logic"]
  → Orbit: MergeRequest[!342] ←[:REVIEWED_BY]- User[@dave]
  → Orbit: Definition[processPayment] ←[:CALLS]- 7 other functions (blast radius)
```

No individual hop in this chain is novel. What's novel is executing all hops in a single automated flow triggered by a runtime error, and **ranking** the results by a confidence formula that weighs recency, frame depth, and blast radius simultaneously.

The blast radius dimension (counting callers via the `CALLS` graph edge) is particularly underutilized in current tooling. A function called by 15 other functions that was changed 3 days ago is a much higher-priority suspect than a function called by 1 other function that was changed yesterday. RootChain's formula makes this explicit and tunable.

---

## Hackathon Context

Built for the [GitLab Transcend Hackathon](https://gitlab-transcend.devpost.com/) — Showcase Track.

**The story:** Every on-call engineer has spent the dead hours of night reconstructing context that already existed inside GitLab. RootChain collapses that reconstruction into a 2-minute automatic analysis. The insight is not that AI can help you debug — it's that GitLab's own SDLC graph, queried via Orbit, already contains the answer. RootChain is just the bridge between the runtime signal and the historical context.