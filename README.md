# RootChain

> One YAML file. Drop it in any GitLab project. When a production error lands as a GitLab issue, RootChain automatically traces the stack trace to the MR that introduced it — finding the causal change, its intent, and who to loop in — in under two minutes.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitLab Duo](https://img.shields.io/badge/GitLab-Duo%20Agent%20Platform-orange)](https://docs.gitlab.com/user/duo_agent_platform/)
[![Orbit](https://img.shields.io/badge/GitLab-Orbit-blue)](https://docs.gitlab.com/orbit/)
[![Python](https://img.shields.io/badge/Python-3.11%2B-green)](https://python.org)

---

## The Problem

A production error fires at 2am. Your on-call engineer opens the alert, sees a stack trace, and spends the next 30–90 minutes doing archaeology: `git blame`, grepping closed issues, finding the MR that introduced the change, messaging the author. The answer has been sitting inside GitLab the whole time — in the MR that changed the function, in the issue that motivated it, in the reviewer who approved it — just disconnected from the runtime signal.

**RootChain closes that gap.**

When an error lands as a GitLab issue — from Sentry, GitLab error tracking, a CI failure, a crash report, or a manually filed bug — RootChain's Duo Agent Platform flow activates automatically. It parses the stack trace, queries GitLab Orbit for the SDLC history of each frame, and posts a structured blame-chain analysis directly to the issue.

**What engineers see when they open the issue:**

```markdown
## 🔗 RootChain SDLC Blame Analysis

**Error:** `AttributeError: 'NoneType' object has no attribute 'get'`
**Primary suspect:** MR !342 by @alice · 4 days ago

| # | Function | File | Last MR | Intent | Author | Confidence |
|---|----------|------|---------|--------|--------|------------|
| 1 | _run_with_retry | orbit_client.py:473 | !342 · 4d ago · ✅ CI passed | #89: JSON DSL rewrite | @alice | 🔴 HIGH |
| 2 | _find_mrs_for_file | orbit_client.py:243 | !342 · 4d ago | #89: JSON DSL rewrite | @alice | 🟡 MEDIUM |

MR !342 rewrote the Orbit query layer from Cypher to JSON DSL. The change at line 473
uses `body.get("result", {})` which silently fails when Orbit returns `{"result": null}` —
the null case was handled in the original implementation but lost during the rewrite.

**Suggested investigation:** Review `orbit_client.py` around line 473, specifically
the `_run_with_retry` changes in MR !342.

**Loop in:** @alice · @bob
```

---

## How It Works

```
Production error fires (Sentry / GitLab error tracking / CI failure / crash report)
        │
        ▼
Error lands as a GitLab issue with a stack trace in the description
        │
        ▼
work_item_created trigger activates the RootChain flow
        │
        ▼
Flow reads the issue, parses the stack trace (Python / Node.js / Go / Ruby / Java / Rust)
        │
        ▼
Orbit JSON DSL queries: File → MergeRequest → WorkItem + User + Pipeline
        │
        ▼
Agent builds a confidence-scored blame chain and posts it as a comment
        │
        ▼
On-call engineer sees: primary suspect MR, intent, author, and a suggested fix path
```

### Why This Is Non-Obvious

Most Orbit use cases are forward queries: "what changed recently?" or "who owns this file?" RootChain inverts the direction: it starts from a **runtime signal** and walks backward through the SDLC graph to find the causal human decision.

The key multi-hop path:
```
AttributeError at runtime
  → stack frame: _run_with_retry() in orbit_client.py
  → Orbit: File[orbit_client.py] ← MergeRequest[!342]
  → Orbit: MergeRequest[!342] → WorkItem[#89: "JSON DSL rewrite"]
  → Orbit: MergeRequest[!342] ← User[@alice (author), @bob (reviewer)]
  → Orbit: Definition[_run_with_retry] ← 7 other callers (blast radius)
```

No individual hop is novel. What's novel is executing all hops automatically from a runtime error and **ranking** the results by a confidence formula that weighs recency, frame depth, and blast radius simultaneously.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        GITLAB DUO AGENT PLATFORM                             │
│                                                                               │
│   ┌───────────────────────────────────────────────────────────────────────┐ │
│   │                   RootChain Flow  (.gitlab/duo-flows/rootchain.yml)    │ │
│   │                                                                         │ │
│   │  work_item_created                                                      │ │
│   │         │                                                               │ │
│   │         ▼                                                               │ │
│   │  get_issue ──► parse stack trace ──► query_graph × N frames           │ │
│   │                                           │                            │ │
│   │                              File → MR → WorkItem + User + Pipeline   │ │
│   │                                           │                            │ │
│   │                              score confidence per frame                │ │
│   │                                           │                            │ │
│   │                              create_issue_note + update_issue          │ │
│   └───────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────│──────────────┘
                                                               │
┌──────────────────────────────────────────────────────────────▼──────────────┐
│                          GITLAB ORBIT                                         │
│                                                                               │
│   File  ←──MODIFIES_FILE──  MergeRequest  ──CLOSES──►  WorkItem             │
│    │                              │                                           │
│   Definition  ←──CALLS──  Definition     ──AUTHORED_BY──►  User             │
│                                   │                                           │
│                              Pipeline  ──  Vulnerability                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

The Duo Agent Platform flow is the **only required file**. The Python code in `src/rootchain/` is a standalone fallback orchestrator for orgs that want to run the same analysis outside the Duo Agent Platform context.

---

## Quick Start

### Prerequisites

| Requirement | Notes |
|-------------|-------|
| GitLab.com Premium or self-managed Ultimate | Required for Orbit Remote |
| Orbit enabled on your group | Settings → AI & Analytics → Orbit → Enable |
| GitLab Duo enabled on the project | Project → Settings → GitLab Duo |
| Personal access token with `api` scope | For Orbit queries and issue updates |

### Step 1: Add the flow to your project

Copy `.gitlab/duo-flows/rootchain.yml` into your project's repository at the same path. That's the entire integration — no server, no cron job, no webhook registration.

```bash
# From your project root
mkdir -p .gitlab/duo-flows .gitlab/skills/rootchain
curl -O https://raw.githubusercontent.com/your-org/rootchain/main/.gitlab/duo-flows/rootchain.yml
curl -O https://raw.githubusercontent.com/your-org/rootchain/main/.gitlab/skills/rootchain/SKILL.md
git add .gitlab/ && git commit -m "Add RootChain Duo flow"
git push
```

### Step 2: Enable the trigger

In your GitLab project: **AI → Triggers → New flow trigger**

| Field | Value |
|-------|-------|
| Event type | Work item → Created |
| Service account | Select the auto-created service account |
| Configuration source | rootchain |
| Label filter | Leave empty (all issues) or set to `bug`, `incident`, etc. |

### Step 3: Enable Orbit on your group

```
Group → Settings → AI & Analytics → Orbit → Enable
```

Wait for initial indexing to complete (10–30 minutes for large groups).

### Step 4: Verify

Create a test issue with any stack trace in the description. Within 2 minutes, the flow should activate and post a RootChain analysis comment. Check **AI → Flows → Managed → rootchain → Sessions** for the run log.

---

## Configuration (Python Fallback Orchestrator)

If running outside the Duo Agent Platform, configure via environment variables:

```bash
# .env.example

# Required
ROOTCHAIN_GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx   # api scope
ROOTCHAIN_GITLAB_URL=https://gitlab.com
ROOTCHAIN_GROUP_PATH=my-org
ROOTCHAIN_PROJECT_PATH=my-org/my-app

# Orbit
ROOTCHAIN_ORBIT_TIMEOUT_SECONDS=30
ROOTCHAIN_ORBIT_MAX_RETRIES=3
ROOTCHAIN_DEFAULT_BRANCH=main

# Parsing
ROOTCHAIN_MAX_FRAMES=5
ROOTCHAIN_INCLUDE_LIBRARY_FRAMES=false

# Confidence scoring (weights must sum to 1.0)
ROOTCHAIN_CONFIDENCE_THRESHOLD=0.4
ROOTCHAIN_RECENCY_WEIGHT=0.50
ROOTCHAIN_DEPTH_WEIGHT=0.35
ROOTCHAIN_BLAST_WEIGHT=0.15
ROOTCHAIN_RECENCY_HALF_LIFE_DAYS=30

# Output
ROOTCHAIN_ADD_LABEL=rootchain-analyzed
ROOTCHAIN_MENTION_AUTHORS=true
ROOTCHAIN_MENTION_REVIEWERS=false
ROOTCHAIN_MAX_MENTION_USERS=3

# Logging
ROOTCHAIN_LOG_LEVEL=INFO
ROOTCHAIN_LOG_FORMAT=json          # json | console
```

Run locally:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Dry run: parse + query Orbit, print the comment to stdout
python -m src.rootchain.orchestrator \
  --project-path "my-org/my-app" \
  --issue-iid 42 \
  --dry-run
```

---

## How RootChain Finds the Causal MR

Current primary lookup: a project-scoped Orbit traversal from Project to
MergeRequest to MergeRequestDiff to MergeRequestDiffFile, filtering the diff
file by `old_path`.

```json
{
  "query": {
    "query_type": "traversal",
    "nodes": [
      {"id": "project", "entity": "Project", "filters": {"full_path": "my-org/my-app"}},
      {"id": "mr", "entity": "MergeRequest", "filters": {"state": "merged"}},
      {"id": "snapshot", "entity": "MergeRequestDiff"},
      {"id": "file", "entity": "MergeRequestDiffFile", "filters": {"old_path": "src/my/file.py"}}
    ],
    "relationships": [
      {"type": "IN_PROJECT", "from": "mr", "to": "project"},
      {"type": "HAS_DIFF", "from": "mr", "to": "snapshot"},
      {"type": "HAS_FILE", "from": "snapshot", "to": "file"}
    ],
    "limit": 25
  }
}
```

`old_path` is used first because it is the stable historical lookup column for
MR diff files. `new_path` and the older neighbor-based queries remain as
fallbacks.

For each stack frame, `OrbitClient` runs a cascade of strategies — stopping at the first one that returns MR nodes:

**Strategy 1 — File neighbors** (direct; fastest when indexed)
```json
{"query": {"query_type": "neighbors", "node": {"entity": "File", "filters": {"path": "src/my/file.py"}}, "neighbors": {"node": "n"}}}
```

**Strategy 2 — MergeRequestDiffFile** (one hop via diff record)
```json
{"query": {"query_type": "neighbors", "node": {"entity": "MergeRequestDiffFile", "filters": {"new_path": "src/my/file.py"}}, "neighbors": {"node": "n"}}}
```

**Strategy 3 — old_path fallback** (renamed files; applies a 0.7× confidence penalty)

**Strategy 4 — GitLab commits REST API** (reliable fallback when Orbit graph edges aren't indexed yet)
```
GET /api/v4/projects/{id}/repository/commits?path={file}&ref_name=main
→ per commit SHA → GET .../commits/{sha}/merge_requests
→ supplement with Orbit MR node data
```

Once MRs are found, a single `neighbors` query per MR returns WorkItems, Users, and Pipeline nodes together for enrichment.

### Confidence Scoring

```
recency  = 1 / (1 + days_since_merge / 30)   # 0 days → 1.0, 30 days → 0.5
depth    = 1 / frame_depth                    # frame 1 → 1.0, frame 5 → 0.2
blast    = min(caller_count / 10, 1.0)        # callers via Orbit CALLS edges

confidence = (recency × 0.50) + (depth × 0.35) + (blast × 0.15)

# orbit_miss → 0.0  (no data; never fabricate)
# fallback_used → × 0.7  (file-level match is less precise)
```

**≥ 0.7** → 🔴 HIGH · **0.4–0.69** → 🟡 MEDIUM · **< 0.4** → 🟢 LOW

---

## Supported Languages

| Language | Frame pattern | Library detection |
|----------|--------------|-------------------|
| Python | `File "path", line N, in func` | `site-packages/`, `/usr/lib/`, `.pyenv/` |
| Node.js / TypeScript | `at FuncName (file.js:N:C)` | `node_modules/`, `dist/` |
| Go | goroutine header + `package.Func(...)\n  /path/file.go:N` | `/usr/local/go/`, `runtime/`, `vendor/` |
| Ruby | `path:N:in 'method'` | `gems/`, `rubygems/` |
| Java | `at com.pkg.Class.method(File.java:N)` | `java.`, `javax.`, `sun.`, `org.springframework.` |
| Kotlin | Same JVM format; `.kt` extension triggers Kotlin detection | `kotlin.`, `kotlinx.` |
| Rust | `N: func::path\n  at file.rs:N` + panic format | `std::`, `core::`, `alloc::`, `tokio::` |

---

## Edge Cases

| Situation | Handling |
|-----------|----------|
| Issue already analyzed | `rootchain-analyzed` label check exits immediately (idempotency) |
| No recognizable stack trace | Posts "no stack trace found" comment, adds label, stops |
| All frames are library code | Posts "all frames filtered" comment explaining why |
| `orbit_miss` for all frames | Posts full analysis table with "Not in Orbit index" in each row |
| Orbit returns `{"result": null}` | Treated as empty result — never raises AttributeError |
| Same MR in multiple frames | Deduplicates — appears once with the highest confidence score |
| Stack trace is 50+ frames | Takes top 5 non-library frames, notes how many were omitted |
| Minified JS / no function names | Skips `<anonymous>` frames, notes source maps recommendation |
| Java `Caused by:` chain | Parses root cause block first; traces all exception layers |
| Renamed file (old_path) | Strategy 3 catches it with a 0.7× confidence penalty |
| Orbit not yet indexed (~1h after merge) | Strategy 4 (commits REST API) bridges the gap |

---

## FAQ

**Q: Does this require Sentry?**  
No. Any GitLab issue with a stack trace in the description works — GitLab error tracking, CI failures, crash reports, manual bug reports, all equally.

**Q: Does it work with GitLab self-managed?**  
Yes, if Orbit Remote is enabled (requires Ultimate tier with ClickHouse backend). Set `ROOTCHAIN_GITLAB_URL` to your instance URL.

**Q: What if the MR has no linked issues?**  
The MR title and author are shown. RootChain never fabricates intent.

**Q: Can I restrict which issues trigger it?**  
Set a label filter in the trigger configuration (AI → Triggers). Common filters: `bug`, `incident`, `sentry-alert`.

**Q: How do I tune for a monorepo?**  
Set `ROOTCHAIN_GROUP_PATH` to the top-level group. Orbit indexes the entire group, so all projects in the monorepo are covered automatically.

**Q: What's the performance impact on GitLab?**  
Each flow run makes 5–25 Orbit queries (depending on frames and fallback strategies), all async. Well within GitLab's API rate limits.

---

## Testing

```bash
# Unit tests (no external calls)
pytest tests/unit/ -v

# With coverage
pytest tests/unit/ --cov=src/rootchain --cov-report=term-missing

# Integration tests (requires live GitLab + Orbit)
export ROOTCHAIN_INTEGRATION_TESTS=1
export ROOTCHAIN_GITLAB_TOKEN=glpat-xxx
export ROOTCHAIN_GROUP_PATH=my-org
export ROOTCHAIN_PROJECT_PATH=my-org/my-app
pytest tests/integration/ -v
```

---

## Troubleshooting

**Flow did not activate**  
Check that a trigger is configured at **AI → Triggers**. The flow YAML defines the agent; the trigger is configured separately and must exist for the flow to fire automatically.

**Agent posted no comment (tools reported as unavailable)**  
Verify `.gitlab/duo-flows/rootchain.yml` has `create_issue_note` and `update_issue` in the toolset — not `create_note` / `add_label`, which are not valid tool names.

**All frames show "Not in Orbit index"**  
- Orbit must be enabled on the group, not just the project
- Code must be on the default branch (`main`/`master`)
- Recently merged code (~< 1h) may not be indexed yet — Strategy 4 (commits REST API) handles this automatically

**HTTP 403 on issue update**  
The token needs `api` scope (not `read_api`). For group tokens, ensure group-level API access is enabled under Group → Settings → General → Permissions.

**Confidence scores all 0.0**  
All frames returned `orbit_miss`. Enable `ROOTCHAIN_LOG_LEVEL=DEBUG` and inspect the structured logs for `orbit_no_mr_data` vs `orbit_commits_api_hit` to see which strategy ran.

Full troubleshooting guide: [`docs/troubleshooting.md`](docs/troubleshooting.md)

---

## Project Structure

```
.gitlab/
  duo-flows/rootchain.yml     ← The only required file for integration
  skills/rootchain/SKILL.md   ← Agent parsing + scoring rules (loaded as context)

src/rootchain/
  models.py          ← All Pydantic v2 models
  config.py          ← Env-var-driven Config dataclass
  sentry_parser.py   ← Stack trace parser (7 languages)
  orbit_client.py    ← Orbit REST client (5-strategy MR discovery, async)
  blame_chain.py     ← Confidence scoring + blame chain construction
  issue_formatter.py ← BlameChain → Markdown
  gitlab_client.py   ← GitLab API client (notes, labels)
  orchestrator.py    ← Entry point for standalone use

receiver/            ← Optional FastAPI webhook receiver
tests/unit/          ← 141 tests, no external calls
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Agent Platform | GitLab Duo Agent Platform |
| Knowledge Graph | GitLab Orbit (Remote) |
| HTTP | `httpx` (async) |
| Data models | Pydantic v2 |
| Retries | `tenacity` |
| Logging | `structlog` (structured JSON) |
| Testing | `pytest` + `pytest-asyncio` + `respx` |

---

## Hackathon Context

Built for the [GitLab Transcend Hackathon](https://gitlab-transcend.devpost.com/) — Showcase Track.

The core bet: GitLab's SDLC graph already contains the answer to "why did this break?" On-call engineers spend 30–90 minutes reconstructing context that Orbit has indexed. RootChain is a single-file integration that makes that context appear automatically when it's needed most.

---

## License

MIT — see [LICENSE](LICENSE).
