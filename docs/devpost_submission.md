# Devpost Submission — RootChain

Exact copy-paste content for every field on the GitLab Transcend Hackathon Devpost form.
**Deadline: June 24, 2026 @ 2:00 PM EDT**

---

## STEP 1: Go to https://gitlab-transcend.devpost.com/ → Submit Project

---

## Field: Project Name

```
RootChain
```

---

## Field: Tagline (one line, shown under the name)

```
Trace Sentry production errors to their SDLC origin automatically — no git blame, no Slack DMs, just Orbit.
```

---

## Field: Track

Select: **Showcase Track**

---

## Field: GitHub / GitLab Project URL

```
https://github.com/Purv-Kabaria/RootChain
```

> ⚠️ You also need a **GitLab project** where the flow is deployed so you can publish to the AI Catalog.
> If you haven't already: push this repo to GitLab and paste that URL here too if the form allows both.
> See the Pre-Submission Checklist at the end of this file.

---

## Field: AI Catalog Link

After publishing to the AI Catalog (see checklist), paste the URL here:

```
https://gitlab.com/explore/ai-catalog/agents/rootchain
```

(URL will be assigned when you publish — replace with your actual URL.)

---

## Field: Demo Video URL

Paste your YouTube or Vimeo URL here after recording.
See `docs/demo_script.md` for the exact shot-by-shot script.
Video must be **public** (not unlisted) and **max 3 minutes**.

---

## Field: Inspiration

Paste exactly:

```
Every on-call engineer has a muscle-memory sequence: Sentry alert fires, open
stack trace, git blame each frame, search closed issues, find the MR, message
the author on Slack, wait. That's 30–90 minutes before a single line of fix is
written — at 2am.

The answer was sitting in GitLab the whole time. The MR that changed the
function, the issue that motivated it, the reviewer who approved it, the CI
pipeline that passed it — all of it is already in the Orbit graph, just
disconnected from the runtime error.

RootChain is the bridge. We built it because we believe inverse debugging —
starting from a production signal and walking backward through the SDLC graph
to find the causal human decision — is a primitive that belongs in every
team's incident response playbook.
```

---

## Field: What it does

Paste exactly:

```
When Sentry creates a GitLab issue for a production error, RootChain activates
automatically via the work_item_created event. Within 2 minutes, it posts a
structured SDLC blame analysis directly on the issue — naming the most likely
causal MR, its business intent, the CI status at time of merge, any co-located
security findings, and who to loop in.

Here's what happens step by step:

1. The Duo Agent Platform flow triggers on work_item_created (filtered by the
   sentry-alert label Sentry's native integration adds).

2. The agent parses the stack trace from the issue description. Supported
   languages: Python, Node.js/TypeScript, Go, Ruby, Java, Kotlin, and Rust.
   Library frames (site-packages, node_modules, vendor, runtime) are filtered
   out. Up to 5 application frames are kept.

3. For each frame, the agent queries GitLab Orbit across four domains:
   - source_code: Definition → File ← MergeRequest (which MR last touched
     this exact function symbol)
   - code_review: MergeRequest → WorkItem via CLOSES/MENTIONED_IN edges
     (what business intent motivated each MR) + caller count via CALLS edges
     (blast radius)
   - security: File ← Vulnerability (any active CVEs on the blamed file)
   - ci: MergeRequest → Pipeline (did CI pass when the MR was merged?)

4. Each frame is scored: confidence = recency×0.5 + depth×0.35 + blast×0.15.
   Recency decays over 30 days; depth is 1/frame_position; blast is
   min(caller_count/10, 1.0). Fallback queries (file-level when symbol isn't
   indexed) carry a 0.7× penalty.

5. The agent posts a Markdown comment with a ranked blame table, a Mermaid
   blame graph, a primary suspect line, error-type-specific investigation
   hints, a security context section if CVEs are present, and @mentions
   for the MR author and reviewers.

6. The issue is labeled rootchain-analyzed — a permanent idempotency guard
   that prevents re-analysis if Sentry re-fires the same alert.

On-call engineers open the issue to find: "This was most likely introduced by
MR !342 (4 days ago), which implemented payment retry logic for issue #89,
approved by @alice, CI passed. The retry branch in processPayment() may not
handle a null gateway response. @alice @dave — loop in?"
```

---

## Field: How we built it

Paste exactly:

```
PRIMARY ARTIFACT: .gitlab/duo-flows/rootchain.yml

This is a Duo Agent Platform flow definition. The entire intelligence lives
here and in .gitlab/skills/rootchain/SKILL.md (the agent's runtime context
for parsing rules, Orbit query templates, confidence formula, and output
format). No backend server is required for the core flow — it runs on the
Duo Agent Platform.

The agent executes these Orbit graph queries via the query_graph MCP tool:

  Primary (source_code domain):
    MATCH (d:Definition {name: $function_name})
          -[:DEFINED_IN]->(f:File {path: $file_path})
          <-[:MODIFIES_FILE]-(mr:MergeRequest)
    WHERE mr.merged_at IS NOT NULL
    ORDER BY mr.merged_at DESC LIMIT 3

  Blast radius (source_code domain):
    MATCH (caller:Definition)-[:CALLS]->(d:Definition {name: $function_name})
    RETURN count(caller) AS caller_count

  Intent (code_review domain):
    MATCH (mr:MergeRequest {iid: $mr_iid})
          -[:CLOSES|MENTIONED_IN]->(wi:WorkItem)
    RETURN wi.iid, wi.title, wi.web_url

  Security (security domain):
    MATCH (f:File {path: $file_path})<-[:AFFECTS_FILE]-(v:Vulnerability)
    WHERE v.state IN ["detected", "confirmed"]
    RETURN v.name, v.severity, v.report_type, v.web_url

  Pipeline (ci domain):
    MATCH (mr:MergeRequest {iid: $mr_iid})-[:HAS_PIPELINE]->(p:Pipeline)
    RETURN p.status ORDER BY p.created_at DESC LIMIT 1

All per-frame queries run in parallel (asyncio.gather). All queries are
parameterized — never string-interpolated.

The Python fallback orchestrator (src/rootchain/) mirrors the same logic
using httpx (async HTTP), Pydantic v2 (data models), tenacity (retry/backoff),
and structlog (structured logging). It serves three purposes: local testing
without needing the Duo Agent Platform, CI validation via pytest, and a
fallback path for orgs running outside the platform.

An optional FastAPI webhook receiver (receiver/main.py) handles Sentry
webhooks directly for orgs where the native Sentry-GitLab integration isn't
available.

136 unit tests. 91% coverage. 7 languages. 4 Orbit domains. 28 commits.
```

---

## Field: Challenges we ran into

Paste exactly:

```
Multi-domain parallel query coordination: Security findings and caller count
both run in parallel with the primary MR lookup per frame. Then per MR,
linked issues + reviewers + pipeline status run in parallel. Getting
asyncio.gather() exception isolation right — so one failing Orbit domain
doesn't kill the entire analysis — took careful design. Each domain failure
degrades gracefully: security_findings defaults to [], pipeline_status
defaults to None, orbit_miss is true if the primary graph query fails.

Orbit response normalization: The iid field comes as either int or string
from the ClickHouse backend depending on the query path, so every iid must
be cast through int(). Timestamps arrive in varied ISO 8601 forms; the
parser handles Z-suffix and explicit +00:00 UTC offsets. merged_at being
None is a valid state for non-merged MRs that must be filtered.

Frame ordering: Sentry lists frames with the error-origin frame FIRST (the
top of the displayed stack trace), not last. Every other stack trace format
(Java, Go, Python tracebacks) lists them in call order with the most recent
call last. We discovered this mid-testing when our confidence scores were
inverted — high confidence was going to the deepest frame instead of the
frame that threw the error. Assigning depth = 1/position directly from
Sentry's listing order (not reversed) fixed it.

Language detection ordering: Kotlin traces match both the Kotlin file
pattern (.kt extension in the frame) AND the Java regex. The detection
check for Kotlin must run before the Java check — if Java runs first,
Kotlin is silently misidentified, all frames tagged with the wrong language,
and the SKILL.md parsing rules don't apply.
```

---

## Field: Accomplishments that we're proud of

Paste exactly:

```
Four Orbit domains in a single flow run. No existing hackathon project (that
we've seen) traverses source_code + code_review + security + ci in one
automated pipeline triggered by a runtime error signal. This is the first
demonstration of "cross-domain" Orbit usage we're aware of.

Inverse debugging as a pattern. The key insight is traversal direction: most
Orbit use cases are "who owns this file?" or "what changed recently?" —
forward queries. RootChain inverts: it starts from a runtime error and walks
backward through the SDLC graph. The multi-hop path (error → symbol →
file → MR → work item → user → CI pipeline) makes the answer self-evident.

Error-type-aware investigation hints. When the formatter generates the
"Suggested investigation" line, it checks the error type: NullPointerException
→ "look for unguarded nil dereferences"; TimeoutError → "look for new I/O
on the hot path"; PanicError → "examine unsafe blocks added in this MR."
This is a small touch but it makes the output feel like a colleague's note,
not a database dump.

Seven languages with full test coverage. Python, Node.js/TypeScript, Go,
Ruby, Java, Kotlin, and Rust — each with distinct regex parsers, library
frame detection patterns, and parser-level tests. Kotlin detection runs
before Java (they share frame format) to prevent silent misclassification.

91% unit test coverage on 136 tests with zero mocked business logic.
```

---

## Field: What we learned

Paste exactly:

```
The most valuable thing Orbit exposes is not any single node type — it's
the edges. Specifically: CALLS edges. Knowing that processPayment() is
called by 9 other functions before we've even looked at git history tells
us this is a high-blast-radius change. A function called by 9 places that
was modified 3 days ago is categorically more suspicious than a function
called by 1 place modified yesterday. No existing IDE plugin or code review
tool surfaces this automatically at incident time.

We also learned that LLM context documents (SKILL.md) need to be as
precise as code. The first version of SKILL.md said "parse the stack trace
and find the function names." The agent hallucinated Orbit query structure.
The second version included verbatim Cypher templates, an exact confidence
formula, and explicit "do not do X" rules. Output quality improved
dramatically — the agent stopped fabricating MR iids that don't exist.
```

---

## Field: What's next for RootChain

Paste exactly:

```
Security triage mode: The same traversal inverted for CVE response. A
security advisory names a function → Orbit finds the MR that introduced it
→ Orbit finds the work item that motivated it → now you know who to brief,
what the business intent was, and whether there's a regression test.

CI failure attribution: When a pipeline fails on main, find the MR that
broke it using the same graph. Today, engineers run git bisect manually.
RootChain can make it automatic.

Auto-assignment: After identifying the primary suspect MR's author, set
the GitLab issue assignee automatically (configurable). Gets the right
person on the issue without a human making that routing decision.

PagerDuty and OpsGenie receiver: The same flow works for any alert source
that can create a GitLab issue or call a webhook. The Sentry integration is
just the first concrete implementation.

AI Catalog distribution: Publish RootChain as a reusable flow any GitLab
group can install with one click and immediately use with their own Sentry
+ Orbit setup. The flow reads its parameters from env vars — nothing is
hardcoded.
```

---

## Field: Built With (tags — add these one by one)

```
gitlab-duo-agent-platform
gitlab-orbit
python
pydantic
httpx
fastapi
structlog
tenacity
pytest
```

---

## Pre-Submission Checklist

Complete these in order before hitting Submit on Devpost.

### 1. Push code to a GitLab project (required for AI Catalog)

```bash
# Create a new project on gitlab.com first, then:
git remote add gitlab https://gitlab.com/YOUR_USERNAME/rootchain.git
git push gitlab main
```

Make the GitLab project **public** and add MIT license if not already present.

### 2. Verify the flow file is on the default branch

The file `.gitlab/duo-flows/rootchain.yml` must be on `main` (the default branch).
The Duo Agent Platform picks it up automatically — no registration step needed.

Verify it appears:
- Navigate in GitLab to your project → **Build → Duo Agent Platform → Flows**
- `rootchain` should appear with status **active**

### 3. Create the `rootchain-analyzed` label in the project

In your GitLab project: **Manage → Labels → New label**
- Name: `rootchain-analyzed`
- Color: `#6699cc` (blue)

Also create `sentry-alert`:
- Name: `sentry-alert`
- Color: `#e24329` (red)

### 4. Test with a dry run before recording

```bash
# Install dependencies
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Run all tests to confirm 136 pass
pytest tests/unit/ -v

# Preview what the comment will look like (no GitLab API calls)
python -m src.rootchain.orchestrator \
  --project-path "your-group/your-project" \
  --issue-iid 1 \
  --dry-run
```

### 5. Record the demo video (max 3 minutes)

See `docs/demo_script.md` for the exact shot-by-shot script with voiceover.
Upload to YouTube as **public**. Do NOT use "unlisted" — the judges need to
be able to watch it without logging in.

### 6. Publish to the GitLab AI Catalog

In your GitLab project (must be public):
- Go to **Build → Duo Agent Platform → Flows → rootchain**
- Click **Publish to AI Catalog**
- Fill in:
  - **Display name:** RootChain
  - **Short description:** Trace Sentry production errors to their SDLC origin via GitLab Orbit — automatically, in under 2 minutes.
  - **Category:** DevSecOps / Incident Response
  - **Tags:** `orbit`, `sentry`, `incident-response`, `blame-chain`, `sdlc`, `debugging`
- Submit and wait for approval (allow 24–48h buffer before the deadline)

Copy the AI Catalog URL once published (format: `https://gitlab.com/explore/ai-catalog/...`).

### 7. Submit on Devpost

1. Go to https://gitlab-transcend.devpost.com/
2. Click **Submit Project**
3. Fill in every field above
4. Paste your YouTube video URL
5. Paste your AI Catalog URL
6. Select **Showcase Track**
7. Paste GitHub URL: `https://github.com/Purv-Kabaria/RootChain`
8. Hit **Submit** before June 24 @ 2:00 PM EDT
