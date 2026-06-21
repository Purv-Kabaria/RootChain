# Devpost Submission Text

Copy-paste this into the Devpost submission form. Adjust GitLab project URL before submitting.

---

## Project Name

RootChain

## Tagline

Trace production errors to their SDLC origin — automatically, in under 2 minutes.

## About the Project

### The Problem

A production 500 error fires at 2am. Your on-call engineer opens the Sentry alert, sees a stack trace, and starts doing archaeology: `git blame` on each frame, grepping closed issues, finding the MR that introduced the change, messaging the author on Slack. This takes 30–90 minutes before a single line of fix is written.

The answer was sitting inside GitLab the whole time — in the MR that changed the function, the issue that motivated it, the reviewer who approved it — just disconnected from the runtime error.

### What RootChain Does

RootChain is a GitLab Duo Agent Platform flow that closes that gap. When Sentry creates a GitLab issue for a production alert, RootChain:

1. Parses the stack trace (Python, Node.js, Go, Ruby, Java supported)
2. Queries GitLab Orbit to find which MRs last modified each frame's function symbol
3. Traces those MRs back to their motivating work items (issues)
4. Counts how many other functions call each frame's function (blast radius)
5. Scores each frame with a confidence formula: recency × 0.5 + depth × 0.35 + blast × 0.15
6. Posts a ranked, hyperlinked analysis comment on the issue in under 2 minutes

### How We Built It

The primary artifact is `.gitlab/duo-flows/rootchain.yml` — a Duo Agent Platform flow definition. The agent uses the `query_graph` MCP tool to execute multi-hop Cypher-like queries against GitLab Orbit's knowledge graph, traversing the `Definition → File → MergeRequest → WorkItem → User` path for each stack frame.

The agent's behavior is specified in `.gitlab/skills/rootchain/SKILL.md`, which is loaded as context at runtime and contains the frame parsing rules, Orbit query templates, confidence formula, and exact output format.

A Python fallback orchestrator (`src/rootchain/`) implements the same logic for testing, CI validation, and orgs that want to run outside the Duo Agent Platform. It uses httpx for async HTTP, Pydantic v2 for data modeling, tenacity for retry logic, and structlog for structured logging. Test coverage is 91% (115 unit tests).

### Orbit Integration

RootChain performs 4 types of Orbit queries per frame:
- **Primary (Definition-level):** `Definition → File ← MergeRequest` — finds MRs that modified the specific function symbol
- **Fallback (File-level):** `File ← MergeRequest` — used when the symbol isn't indexed
- **Work item enrichment:** `MergeRequest → WorkItem` via `CLOSES/MENTIONED_IN` edges — gets the business intent behind each MR
- **Blast radius:** `Definition ← Definition` via `CALLS` edge — counts how many functions call the target, measuring its criticality

This multi-hop traversal is the core innovation: it walks backward from a runtime signal through the full SDLC graph to find the causal human decision.

### What's Next

The same pattern extends to:
- Security triage: CVE advisory → file → MR → author → intent
- CI failure attribution: failing test file → last MR that touched it → author
- Auto-assignment: set issue assignee to the blamed MR's author
- Slack/PagerDuty integration for incident channels

### Built With

- GitLab Duo Agent Platform (flows + skills)
- GitLab Orbit (knowledge graph queries via `query_graph` MCP tool)
- Python 3.11+, httpx, Pydantic v2, tenacity, structlog
- FastAPI (optional webhook receiver)
- pytest, respx (91% test coverage)

---

## Track

Showcase Track

## GitLab Project URL

https://gitlab.com/YOUR_USERNAME/rootchain

## AI Catalog Link

https://gitlab.com/explore/ai-catalog/agents/rootchain

## Demo Video URL

[YouTube link — 3 minute walkthrough]

## What problem does your project solve?

On-call engineers spend 30–90 minutes reconstructing context that already exists inside GitLab every time a production error fires. RootChain eliminates that manual archaeology by using GitLab Orbit to automatically trace the runtime error back to its SDLC origin — delivering the causal MR, the business intent behind it, and who to loop in, all within 2 minutes of the alert firing.

## How does your project use GitLab Orbit?

RootChain performs 4 distinct multi-hop Orbit graph queries per stack frame:
1. `Definition[func] -[:DEFINED_IN]→ File -[:MODIFIES_FILE]← MergeRequest` — finds which MRs last touched the exact function symbol
2. `File -[:MODIFIES_FILE]← MergeRequest` — file-level fallback when symbol isn't indexed
3. `MergeRequest -[:CLOSES|MENTIONED_IN]→ WorkItem` — retrieves the business intent behind each MR
4. `Definition ←[:CALLS]- Definition` — counts callers for blast radius scoring

The project would not be possible without Orbit — there is no other way to resolve a function name in a stack trace to its specific MR history and linked work items in real time.
