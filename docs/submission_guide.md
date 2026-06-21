# Complete Submission Guide — RootChain
# GitLab Transcend Hackathon · Showcase Track
# Deadline: June 24, 2026 @ 2:00 PM EDT

This guide assumes you have a brand-new GitLab account and covers every step
from environment setup through Devpost submission. Do everything in order.

---

## SECTION 1: Prerequisites (do this first)

### 1.1 What you need installed locally

```
Python 3.11+     →  python --version   (must say 3.11 or 3.12 or 3.13)
Git              →  git --version
```

### 1.2 Verify the GitHub repo is working

```bash
# Clone it (if not already done)
git clone https://github.com/Purv-Kabaria/RootChain.git
cd RootChain

# Install dependencies
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Mac/Linux

pip install -e ".[dev]"

# Confirm all 136 tests pass
pytest tests/unit/ -v
```

You should see `136 passed` at the end. If not, stop and fix before continuing.

---

## SECTION 2: Set up your GitLab project

### 2.1 Create a new project on GitLab

1. Go to https://gitlab.com
2. Top-left → **New project** → **Create blank project**
3. Fill in:
   - **Project name:** `RootChain`
   - **Project URL:** your username → project slug `rootchain`
   - **Visibility:** ✅ **Public** (required for AI Catalog and hackathon)
   - **Initialize with README:** ❌ uncheck this
4. Click **Create project**

You now have an empty public project at `https://gitlab.com/YOUR_USERNAME/rootchain`.

### 2.2 Push the code from GitHub to GitLab

In your local RootChain directory:

```bash
# Add your GitLab project as a second remote
git remote add gitlab https://gitlab.com/YOUR_USERNAME/rootchain.git

# Push everything to GitLab
git push gitlab main
```

When prompted: enter your GitLab username and password (or a Personal Access Token
if you have 2FA enabled — see Section 2.3).

After this command completes, refresh your GitLab project page.
You should see all the files including `.gitlab/duo-flows/rootchain.yml`.

### 2.3 Create a Personal Access Token (PAT)

You'll need this for local testing, CI variables, and the Devpost form.

1. In GitLab: top-right avatar → **Edit profile**
2. Left sidebar → **Access Tokens**
3. Click **Add new token**
4. Fill in:
   - **Token name:** `rootchain-hackathon`
   - **Expiration:** July 1, 2026 (after the hackathon)
   - **Scopes:** ✅ `api` (check only this one)
5. Click **Create personal access token**
6. **Copy the token immediately** — GitLab only shows it once

Save it as `ROOTCHAIN_GITLAB_TOKEN` — you'll use it in multiple places below.

---

## SECTION 3: Enable GitLab Duo and verify the flow appears

### 3.1 Enable GitLab Duo on your project

GitLab Duo must be enabled for the flow to run.

1. In your GitLab project: left sidebar → **Settings** → **GitLab Duo**
2. If you see a toggle: turn it **on**
3. If you don't see this option: go to the group level instead:
   - Left sidebar → your username/group → **Settings** → **GitLab Duo**
   - Enable it there

> **Note on tier:** As of GitLab 18.x, the Duo Agent Platform is available on
> Free tier with GitLab Credits (paid per use) or with a Duo Pro/Enterprise
> subscription. If you don't see the GitLab Duo settings, your account may need
> Duo enabled — check https://gitlab.com/profile/gitlab_duo for your Duo status.

### 3.2 Verify the flow appears in the UI

1. In your GitLab project: left sidebar → **AI** → **Flows**
2. You should now see **rootchain** listed (instead of the empty state message)
3. The status should show as **active**

If `rootchain` doesn't appear after pushing:
- Confirm `.gitlab/duo-flows/rootchain.yml` is on the `main` branch
  (check the file browser in your GitLab project)
- Wait 1–2 minutes and refresh — the platform scans for new flow files

### 3.3 Create the required labels

The flow won't trigger without these labels existing in the project.

In your GitLab project: left sidebar → **Manage** → **Labels** → **New label**

Create label 1:
- **Name:** `sentry-alert`
- **Color:** `#e24329` (red — paste this hex code)
- Click **Create label**

Create label 2:
- **Name:** `rootchain-analyzed`
- **Color:** `#6699cc` (blue — paste this hex code)
- Click **Create label**

---

## SECTION 4: Test the flow locally with dry-run

Before testing against a live GitLab issue, verify the parser + formatter work.

### 4.1 Copy the .env.example file

```bash
# In your local RootChain directory:
copy .env.example .env     # Windows
# cp .env.example .env     # Mac/Linux
```

Open `.env` in any text editor and fill in:

```bash
ROOTCHAIN_GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx    # your PAT from Section 2.3
ROOTCHAIN_GITLAB_URL=https://gitlab.com
ROOTCHAIN_GROUP_PATH=YOUR_USERNAME                   # your GitLab username (no slash)
ROOTCHAIN_PROJECT_PATH=YOUR_USERNAME/rootchain       # username/project-name
```

### 4.2 Run the parser on a sample Sentry event

```bash
python -c "
import os
os.environ['ROOTCHAIN_GITLAB_TOKEN'] = 'demo'
os.environ['ROOTCHAIN_GITLAB_URL'] = 'https://gitlab.com'
os.environ['ROOTCHAIN_GROUP_PATH'] = 'demo'
os.environ['ROOTCHAIN_PROJECT_PATH'] = 'demo/demo'
from src.rootchain.config import Config
from src.rootchain.sentry_parser import SentryParser
config = Config.from_env()
parser = SentryParser(config)
import json, pathlib
data = json.loads(pathlib.Path('tests/fixtures/sentry_python.json').read_text())
event = parser.parse(data['title'], data['description'])
print(f'Language: {event.language}')
print(f'Error: {event.error_type}: {event.error_message}')
for f in event.frames:
    print(f'  [{f.frame_depth}] {f.function_name} @ {f.file_path}:{f.line_number}')
"
```

Expected output: parsed frames with depth numbers, no errors.

### 4.3 Test the full formatter (no GitLab API needed)

```bash
# Run all unit tests to confirm everything is working
pytest tests/unit/ -v --tb=short
```

All 136 tests should pass.

---

## SECTION 5: Test with a live GitLab issue (optional but recommended for demo)

This requires GitLab Orbit to be enabled on your account. Orbit is a paid feature
(GitLab Premium or Ultimate required for the full graph). If you're on the Free tier,
the flow will still trigger and run, but Orbit queries will return `orbit_miss` for
all frames (the comment will be posted but say "No Orbit data available").

> **For the hackathon demo:** If you don't have Orbit access, the demo video can
> instead show the `--dry-run` output in the terminal, which demonstrates the full
> analysis pipeline. See Section 8 (Video Demo) for the fallback script.

### 5.1 Create a test Sentry-format issue

Run the test issue generator:

```bash
python scripts/generate_test_issue.py \
  --project-path "YOUR_USERNAME/rootchain" \
  --token "$ROOTCHAIN_GITLAB_TOKEN" \
  --language python
```

Or create one manually in GitLab:
1. Your project → **Plan** → **Issues** → **New issue**
2. **Title:** `[Sentry] TypeError: 'NoneType' object is not subscriptable`
3. **Description:** paste this exactly:

```
## TypeError: 'NoneType' object is not subscriptable

**Sentry Issue:** https://sentry.io/organizations/demo/issues/1234567/

**Culprit:** `payments/processor.py in processPayment`

**Times seen:** 47
**Environment:** production

### Stacktrace

```
Traceback (most recent call last):
  File "payments/processor.py", line 142, in processPayment
    result_id = gateway_response['id']
  File "payments/gateway.py", line 88, in call_gateway
    return self._session.post(url, data=payload)
  File "core/session.py", line 34, in post
    return requests.post(self.base_url + path, **kwargs)
```
```

4. **Labels:** add `sentry-alert`
5. Click **Create issue**

### 5.2 Watch the flow run

After the issue is created:
1. Left sidebar → **AI** → **Flows** → click **rootchain**
2. Look for a new run in the **Runs** or **Recent activity** section
3. Click into the run to see the step-by-step execution log

The flow should complete within 1–2 minutes and add a comment to the issue.

---

## SECTION 6: Publish to the AI Catalog

The hackathon requires at least one flow published to the AI Catalog.
This section covers what's confirmed about the current process.

### 6.1 What the AI Catalog is

The AI Catalog is at https://gitlab.com/explore/ai-catalog
It lists agents and flows that any GitLab user can discover and use.

### 6.2 How to publish your flow

> ⚠️ The exact publish UI varies by GitLab version and is behind authentication
> in the docs. Use this sequence based on the current (GitLab 18.x) UI:

**Path A — Through the AI menu (try this first):**
1. Left sidebar → **AI** → **Flows** → click **rootchain**
2. Look for a **"Publish to catalog"** or **"Share"** button in the flow detail view
3. If present: fill in the metadata form (see Section 6.3) and submit

**Path B — Through the AI Catalog directly:**
1. Go to https://gitlab.com/explore/ai-catalog
2. Look for a **"Submit"** or **"Add to catalog"** button (top right)
3. Point it to your GitLab project URL: `https://gitlab.com/YOUR_USERNAME/rootchain`
4. Fill in the metadata (see Section 6.3)

**Path C — Via group settings:**
1. Left sidebar → your group/username → **Settings** → **AI** (or **GitLab Duo**)
2. Look for AI Catalog publishing options

**If none of these work:** The AI Catalog publish button may not be available on
Free tier or may require manual approval. In this case:
- Email the hackathon organizers (link on the Devpost page) to explain your project
  is at `https://gitlab.com/YOUR_USERNAME/rootchain` and ask how to submit to catalog
- In your Devpost submission, put your GitLab project URL in the AI Catalog field
  as a fallback and note that you're awaiting catalog approval

### 6.3 Catalog metadata to fill in

When you reach the publish form, use exactly this content:

| Field | Value |
|-------|-------|
| **Name** | RootChain |
| **Short description** | Trace Sentry production errors to their SDLC origin via GitLab Orbit — automatically in under 2 minutes. |
| **Category** | DevSecOps / Incident Response |
| **Tags** | `orbit`, `sentry`, `incident-response`, `blame-chain`, `sdlc`, `debugging` |
| **Version** | `0.1.0` |
| **Source URL** | `https://gitlab.com/YOUR_USERNAME/rootchain` |
| **Documentation** | `https://github.com/Purv-Kabaria/RootChain` |
| **License** | MIT |

**Long description (paste into the description field):**

```
RootChain is a GitLab Duo Agent Platform flow that automatically traces
production Sentry errors to their SDLC origin.

When Sentry creates a GitLab issue for a production alert, RootChain:
1. Parses the stack trace (Python, Node.js, Go, Ruby, Java, Kotlin, Rust)
2. Queries GitLab Orbit across 4 domains: source_code, code_review,
   security, and ci — finding which MR last modified each function, the
   business intent behind it, any active CVEs in the blamed file, and
   whether CI passed when the MR was merged
3. Scores each frame with confidence = recency×0.5 + depth×0.35 + blast×0.15
4. Posts a ranked blame-chain analysis comment within 2 minutes

Result: on-call engineers open the GitLab issue to find the causal MR,
its business intent, who changed it, who reviewed it, CI status, and
where to look — no git blame, no Slack archaeology.

Setup: requires GitLab Duo enabled + Sentry-GitLab integration.
Full setup guide in README.
```

---

## SECTION 7: Devpost submission — exact fields

Go to: **https://gitlab-transcend.devpost.com/** → **Submit Project**

### Field: Project Name
```
RootChain
```

### Field: Tagline
```
Trace Sentry production errors to their SDLC origin automatically — no git blame, no Slack DMs, just Orbit.
```

### Field: Track
Select: **Showcase Track**

### Field: Link to your GitLab project (Showcase track field)
```
https://gitlab.com/YOUR_USERNAME/rootchain
```
Replace `YOUR_USERNAME` with your actual GitLab username.

### Field: GitHub repo (if there's a separate field for source code)
```
https://github.com/Purv-Kabaria/RootChain
```

### Field: AI Catalog link
Paste the URL from Section 6 after publishing. If the catalog isn't showing a
published entry yet, paste the GitLab project URL as a placeholder and note
in the description that catalog submission is pending approval.

### Field: Demo Video URL
Paste your YouTube URL after recording. See Section 8 for the exact script.
The video must be **public** (not unlisted) and **≤ 3 minutes**.

### Field: Inspiration
```
Every on-call engineer has a muscle-memory sequence: Sentry alert fires, open
stack trace, git blame each frame, search closed issues, find the MR, message
the author on Slack, wait. That's 30-90 minutes before a single line of fix is
written — at 2am.

The answer was sitting in GitLab the whole time. The MR that changed the
function, the issue that motivated it, the reviewer who approved it, the CI
pipeline that passed it — all of it is already in the Orbit graph, just
disconnected from the runtime error.

RootChain is the bridge. We built it because inverse debugging — starting from
a production signal and walking backward through the SDLC graph to find the
causal human decision — is a primitive that belongs in every team's incident
response playbook.
```

### Field: What it does
```
When Sentry creates a GitLab issue for a production error, RootChain activates
automatically via the work_item_created event. Within 2 minutes, it posts a
structured SDLC blame analysis directly on the issue.

Step by step:

1. The Duo Agent Platform flow triggers on work_item_created (filtered by the
   sentry-alert label added by Sentry's native GitLab integration).

2. The agent parses the stack trace. Supported: Python, Node.js/TypeScript,
   Go, Ruby, Java, Kotlin, and Rust. Library frames are filtered out. Up to
   5 application frames are analyzed.

3. For each frame, the agent queries GitLab Orbit across 4 domains:
   - source_code: finds which MR last modified the exact function symbol
   - code_review: finds the work item that motivated each MR (business intent)
     + caller count via CALLS edges (blast radius)
   - security: surfaces active CVEs in the blamed file
   - ci: checks whether CI passed when the MR was merged

4. Each frame is scored: confidence = recency×0.5 + depth×0.35 + blast×0.15

5. A Markdown comment is posted with a ranked blame table, Mermaid blame graph,
   primary suspect line, error-type-specific investigation hint, security context
   if CVEs exist, and @mentions for the MR author and reviewers.

6. The issue is labeled rootchain-analyzed — permanent idempotency guard.

On-call engineers open the issue to find: "Most likely introduced by MR !342
(4 days ago), implementing payment retry logic for issue #89, approved by
@alice, CI passed. Check the retry branch in processPayment() around line 142
for the null gateway response case."
```

### Field: How we built it
```
Primary artifact: .gitlab/duo-flows/rootchain.yml

A Duo Agent Platform flow definition. The agent uses the query_graph MCP tool
to execute parameterized Cypher-like traversals across four Orbit domains.
The agent's behavior is specified in .gitlab/skills/rootchain/SKILL.md, which
is loaded as context at runtime and contains parsing rules, query templates,
the confidence formula, and the exact output format.

Core Orbit queries:

  Source code domain:
  MATCH (d:Definition {name: $function_name})
        -[:DEFINED_IN]->(f:File {path: $file_path})
        <-[:MODIFIES_FILE]-(mr:MergeRequest)
  ORDER BY mr.merged_at DESC LIMIT 3

  Code review domain (blast radius):
  MATCH (caller:Definition)-[:CALLS]->(d:Definition {name: $function_name})
  RETURN count(caller) AS caller_count

  Security domain:
  MATCH (f:File {path: $file_path})<-[:AFFECTS_FILE]-(v:Vulnerability)
  WHERE v.state IN ["detected", "confirmed"]

  CI domain:
  MATCH (mr:MergeRequest {iid: $mr_iid})-[:HAS_PIPELINE]->(p:Pipeline)
  RETURN p.status ORDER BY p.created_at DESC LIMIT 1

All queries are parameterized — never string-interpolated. All per-frame
queries run in parallel (asyncio.gather). Exception isolation ensures one
failing Orbit domain doesn't block the whole analysis.

A Python fallback orchestrator (src/rootchain/) mirrors the full logic using
httpx, Pydantic v2, tenacity, and structlog — for local testing and CI.
An optional FastAPI webhook receiver handles Sentry webhooks directly for orgs
without the native Sentry-GitLab integration.

136 unit tests. 91% coverage. 7 languages. 4 Orbit domains. 28 commits.
```

### Field: Challenges we ran into
```
Parallel query coordination: Security findings and caller count run in parallel
with the primary MR lookup per frame. Then per MR, linked issues + reviewers +
pipeline status run in parallel. Getting asyncio.gather() exception isolation
right — so one failing Orbit domain doesn't kill the whole analysis — was the
core engineering challenge. Each domain failure degrades gracefully.

Frame ordering inversion: Sentry lists frames with the error-origin frame FIRST
(opposite of most stack trace formats). We discovered this mid-testing when
confidence scores were inverted — high scores were going to the deepest frames
instead of the frame that threw the error. Assigning depth = 1/position from
Sentry's listing order (not reversed) fixed it.

Orbit response normalization: iid comes as int or string from ClickHouse
depending on the query path. merged_at arrives in varied ISO 8601 forms.
Every iid must be cast through int(). Every timestamp needs Z-suffix handling.

Language detection ordering: Kotlin traces match both the .kt file pattern AND
the Java regex. Kotlin detection must run before Java — otherwise Kotlin is
silently misclassified and the wrong parsing rules apply.

SKILL.md precision: The first version said "parse the stack trace and find the
function names." The agent hallucinated Orbit query structure. The second version
included verbatim Cypher templates, the exact confidence formula, and explicit
prohibitions. Output quality improved dramatically.
```

### Field: Accomplishments that we're proud of
```
Four Orbit domains in a single automated flow. Source_code, code_review,
security, and ci — traversed in parallel, per frame, triggered by a runtime
error signal. This is the first demonstration of cross-domain Orbit usage in
a single automated pipeline that we're aware of.

Inverse debugging as a pattern. Most Orbit queries are forward ("who changed
this file?"). RootChain inverts: start from a runtime error, walk backward
through the graph, surface the causal human decision.

Error-type-aware investigation hints. The formatter checks the error type:
NullPointerException → "check nil dereferences"; TimeoutError → "look for
new I/O on the hot path"; panic → "examine unsafe blocks." Small touch that
makes the output feel like a colleague's note, not a database dump.

Seven languages with full test coverage. Python, Node.js, Go, Ruby, Java,
Kotlin, and Rust — each with distinct parsers, library detection, and tests.

91% unit test coverage on 136 tests.
```

### Field: What we learned
```
The most valuable thing Orbit exposes is not any single node type — it's
the CALLS edges. Knowing a function is called by 9 other places before
even looking at git history tells you this is a high-blast-radius change.
No existing tool surfaces this automatically at incident time.

LLM context documents (SKILL.md) need to be as precise as code. Vague
instructions produce hallucinated Orbit query structure. Verbatim Cypher
templates, exact formulas, and explicit prohibitions produce reliable output.
```

### Field: What's next for RootChain
```
Security triage: CVE advisory → file → MR → author who introduced it.
Same traversal, different starting node.

CI failure attribution: When a pipeline fails on main, trace failing tests
back to the last MR that touched those files. Makes git bisect automatic.

Auto-assign: After identifying the primary suspect MR's author, set the
GitLab issue assignee automatically.

PagerDuty/OpsGenie receiver: Same flow, different alert source. The webhook
receiver already exists — just needs a different payload parser.

AI Catalog distribution: Any GitLab group should be able to install
RootChain with one click and immediately use it with their own Sentry setup.
```

### Field: Built With (add as individual tags)
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

## SECTION 8: Record the demo video

### Before you record

**Have these open and ready:**
- Tab 1: Your GitLab project → **AI** → **Flows** (showing rootchain as active)
- Tab 2: Your GitLab project → issue you just created (the test Sentry issue)
- Tab 3: The README on GitHub (for the architecture diagram at the end)
- Terminal: ready to paste the `generate_test_issue.py` command

**Zoom browser to 125%** — text must be legible in 1080p.

### SHOT-BY-SHOT SCRIPT (≤ 3 minutes)

---

**[0:00–0:20] The Problem**

SCREEN: Open any text editor and have this pre-typed:
```
TypeError: 'NoneType' object is not subscriptable

  File "payments/processor.py", line 142, in processPayment
    result_id = gateway_response['id']
  File "payments/gateway.py", line 88, in call_gateway
    return self._session.post(url, data=payload)
```

VOICEOVER:
> "This is what every on-call engineer sees at 2am. A production error with a
> stack trace. What happens next: git blame on each frame, search closed issues,
> find the MR, message the author on Slack. Thirty to ninety minutes of
> archaeology. The answer has been in GitLab's graph the whole time. RootChain
> just asks it."

---

**[0:20–0:45] The Flow**

SCREEN: Switch to Tab 1 — GitLab project → AI → Flows
Show the rootchain flow with `active` status. Briefly show the YAML file in
the repository (`.gitlab/duo-flows/rootchain.yml`).

VOICEOVER:
> "RootChain is a GitLab Duo Agent Platform flow — one YAML file in the
> repository. It activates automatically whenever Sentry creates a GitLab issue,
> with no additional servers or cron jobs. Here it is in AI > Flows, active and
> ready."

---

**[0:45–1:25] Trigger**

SCREEN: Run the generate_test_issue command in terminal:
```bash
python scripts/generate_test_issue.py \
  --project-path "YOUR_USERNAME/rootchain" \
  --token "YOUR_TOKEN" \
  --language python
```
Show the output (issue URL printed). Switch to Tab 2 and navigate to the new
issue, showing the Sentry-format description and the `sentry-alert` label.

VOICEOVER:
> "I'm creating a test GitLab issue in the exact format Sentry's native
> integration creates — with the sentry-alert label and stack trace. This
> triggers the RootChain flow. Let me navigate to AI > Flows to watch it run."

Switch to AI → Flows → rootchain → show the run in progress.

---

**[1:25–2:05] Orbit Queries**

SCREEN: Show the flow run log. If you can see query_graph calls, show them.
If not, switch to a terminal and show the dry-run output:

```bash
python -m src.rootchain.orchestrator \
  --project-path "YOUR_USERNAME/rootchain" \
  --issue-iid 1 \
  --dry-run
```

VOICEOVER:
> "For each stack frame, RootChain queries four Orbit domains in parallel.
> First: the source code domain — Definition node to File to MergeRequest —
> finding which MR last modified the exact function symbol. Second: code review
> domain — MergeRequest to WorkItem via CLOSES edges — the business intent
> behind each MR, plus CALLS edges for blast radius. Third: security domain —
> any active CVEs on the blamed file. Fourth: CI domain — did the pipeline pass
> when this MR was merged? All parameterized, no string interpolation."

---

**[2:05–2:45] The Output**

SCREEN: Navigate to the GitLab issue. Scroll to the RootChain comment. Slowly
scroll through:
1. Primary suspect line with MR link and age
2. The blame table (# | Function | File | Last MR | Intent | Author | Confidence)
3. Expand the Mermaid blame graph
4. The Analysis section with the investigation hint
5. The "Loop in:" @mention line

If the comment shows orbit_miss (no Orbit data), that's fine — narrate:
> "In a production environment with Orbit enabled, each frame resolves to its
> causal MR and work item. Here the analysis runs but marks frames as orbit_miss
> since this is a demo environment without Orbit indexing — the structure is
> identical."

VOICEOVER (for live Orbit case):
> "Two minutes after the alert fired. Primary suspect: the MR that modified
> processPayment, merged 4 days ago, implementing payment retry logic for
> issue #89. Author @alice, reviewer @dave, CI passed. The analysis suggests
> checking the retry branch for a null gateway response — a TypeError-specific
> hint. No git blame. No Slack message. This was all in Orbit."

---

**[2:45–3:00] Close**

SCREEN: Show the GitHub README architecture diagram.

VOICEOVER:
> "The key insight is inversion: start from a production error, walk backward
> through Orbit's graph, surface the causal human decision. Open source, MIT
> licensed, published to the GitLab AI Catalog. Links below."

---

### After recording

1. Upload to YouTube → set visibility to **Public** (not Unlisted)
2. Wait for processing to complete
3. Copy the URL: `https://youtube.com/watch?v=XXXXXXX`
4. Paste into the Devpost form

---

## SECTION 9: Submit on Devpost

1. Go to https://gitlab-transcend.devpost.com/
2. Click **Submit Project** (top right)
3. If prompted to log in or create a Devpost account: do so
4. Fill in every field from Section 7
5. Attach your YouTube video URL
6. Select **Showcase Track**
7. Submit before **June 24, 2026 @ 2:00 PM EDT**

After submitting: you'll get a confirmation email. Keep it.

---

## SECTION 10: Checklist before hitting Submit

Go through this line by line before clicking Submit on Devpost.

**GitLab project:**
- [ ] Project is public (`https://gitlab.com/YOUR_USERNAME/rootchain`)
- [ ] MIT LICENSE file is in the repo (check: it's in the GitHub repo, push confirmed)
- [ ] `.gitlab/duo-flows/rootchain.yml` is on the main branch
- [ ] `.gitlab/skills/rootchain/SKILL.md` is on the main branch
- [ ] `sentry-alert` label exists in the GitLab project
- [ ] `rootchain-analyzed` label exists in the GitLab project
- [ ] AI → Flows shows rootchain with status `active`

**Demo video:**
- [ ] Video is ≤ 3 minutes (use YouTube's duration display to confirm)
- [ ] Video is set to **Public** (not Unlisted or Private)
- [ ] Video URL is `https://www.youtube.com/watch?v=...`
- [ ] Audio is clear — narrate every screen you show

**AI Catalog:**
- [ ] Flow is published or submission is pending
- [ ] You have a catalog URL (or GitLab project URL as fallback)

**Devpost form:**
- [ ] Project name: RootChain
- [ ] Track: Showcase Track
- [ ] GitLab project URL filled in
- [ ] Video URL filled in
- [ ] All text fields (Inspiration, What it does, How we built it, etc.) filled in
- [ ] Built With tags added
- [ ] Submitted before June 24 @ 2:00 PM EDT

---

## SECTION 11: Troubleshooting

### "AI → Flows doesn't show rootchain after I pushed"

Check that the file is actually on `main` and not another branch:

In your GitLab project file browser, look for:
`.gitlab/` → `duo-flows/` → `rootchain.yml`

If it's not there, the push may not have included that directory. Try:
```bash
git push gitlab main --force-with-lease
```

Then refresh AI → Flows.

### "I can't push to GitLab — authentication error"

GitLab now requires a token for HTTPS pushes (not your password).

```bash
# Remove old remote and re-add with token embedded
git remote remove gitlab
git remote add gitlab https://YOUR_USERNAME:YOUR_PAT@gitlab.com/YOUR_USERNAME/rootchain.git
git push gitlab main
```

Replace `YOUR_PAT` with your Personal Access Token from Section 2.3.

### "The flow triggered but the comment shows all orbit_miss"

This means GitLab Orbit is not enabled or not indexed for your project.
For the hackathon demo, this is acceptable — the flow still runs correctly
and posts a well-structured comment. Use the `--dry-run` terminal output
to demonstrate what the comment looks like with real Orbit data.

### "GitLab Duo is not available on my account"

Go to https://gitlab.com/profile/gitlab_duo and check your status.
If you don't have Duo, you may be able to start a trial:
- Your GitLab group → **Settings** → **GitLab Duo** → **Start trial**
- Or go to https://about.gitlab.com/gitlab-duo/ to start a trial

### "I can't find a Publish button for the AI Catalog"

The AI Catalog publish flow varies by GitLab version. Try:
1. Left sidebar → **AI** → and look for **Catalog** or **AI Catalog**
2. https://gitlab.com/explore/ai-catalog → look for a submit button
3. Contact hackathon support via the Devpost page and explain you need
   help publishing to the catalog
