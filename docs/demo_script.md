# Demo Video Script — RootChain
# Max 3 minutes. Record at 1920×1080. No background music.

## Pre-Recording Setup

**Before you hit record, prepare all of these:**

```bash
# Terminal 1: Have this command ready to paste (don't run yet)
python scripts/generate_test_issue.py \
  --project-path "your-group/your-project" \
  --token "$ROOTCHAIN_GITLAB_TOKEN" \
  --language python

# Terminal 2: Have this ready for the dry-run section
python -m src.rootchain.orchestrator \
  --project-path "your-group/your-project" \
  --issue-iid 1 \
  --dry-run
```

**Browser tabs open and logged in:**
1. Tab 1: The GitLab project's issue list (empty, ready)
2. Tab 2: **Build → Duo Agent Platform → Flows → rootchain** (showing `active` status)
3. Tab 3: The GitHub repo README (for the architecture diagram)

**Zoom browser to 125%** so text is legible in the recording.

**Record a 30-second dry run first** to check audio levels.

---

## [0:00–0:20] The Problem (20 seconds)

**SCREEN:** Open a text editor or Sentry mock showing this error (pre-paste it):
```
TypeError: 'NoneType' object is not subscriptable

Traceback (most recent call last):
  File "payments/processor.py", line 142, in processPayment
    result_id = gateway_response['id']
  File "payments/gateway.py", line 88, in call_gateway
    return self._session.post(url, data=payload)
```

**VOICEOVER:**
> "This is what your on-call engineer sees at 2am. A Sentry alert with a stack trace. What happens next is always the same: git blame on each frame, search closed issues for context, find the MR that changed the function, message the author on Slack. Thirty to ninety minutes of archaeology before a single line of fix is written. The answer was in GitLab the whole time — in the graph. RootChain just asks it."

---

## [0:20–0:45] The Flow (25 seconds)

**SCREEN:** Switch to Tab 2 — GitLab project → Build → Duo Agent Platform → Flows

Slowly scroll to show:
- The `rootchain` flow in the list
- Status: `active`
- Brief glimpse of the YAML (just enough to show it's one file)

**VOICEOVER:**
> "RootChain is a GitLab Duo Agent Platform flow — one YAML file in the repo at `.gitlab/duo-flows/rootchain.yml`. No backend server, no cron job. It activates automatically on `work_item_created` whenever Sentry's native integration creates a GitLab issue. Zero additional infrastructure."

---

## [0:45–1:20] The Trigger (35 seconds)

**SCREEN:** Switch to Terminal 1. Paste and run the generate_test_issue command.
Show the output: issue created, URL printed.
Switch to Tab 1 (GitLab issue list) and refresh — show the new issue with `sentry-alert` label.
Click into the issue to show the Sentry-format description with the stack trace.

**VOICEOVER:**
> "I'm creating a test issue that looks exactly like what Sentry's native integration creates — including the label and the stack trace format. Watch the Duo Agent Platform. The RootChain flow will activate within seconds."

_(Keep the issue tab open. You'll come back to it after the Orbit section.)_

---

## [1:20–2:00] The Orbit Queries (40 seconds)

**SCREEN:** Switch to Tab 2 → Duo Agent Platform → Flows → rootchain → Recent Runs

Click into the active/completed run. Show the query_graph calls in the log.
If possible, expand one call to show the Cypher query and the result returned.

**VOICEOVER:**
> "RootChain queries four Orbit domains for each frame. First: the source code domain — it traverses Definition to File to MergeRequest to find which MR last modified the exact function symbol `processPayment`. Second: the code review domain — it follows MergeRequest to WorkItem via CLOSES edges to get the business intent behind each MR. Third: it counts callers via CALLS edges for blast radius — how many other functions depend on this one. Fourth: the security domain surfaces any active vulnerabilities in the blamed file, and the CI domain checks whether the pipeline passed when the MR was merged."

_(If the flow log isn't showing query details, briefly switch to the dry-run terminal output showing the JSON-structured logs instead.)_

---

## [2:00–2:45] The Output (45 seconds)

**SCREEN:** Return to the GitLab issue tab. Scroll to the RootChain comment at the bottom.

Slowly scroll through:
1. The "Primary suspect" line with the MR link and age
2. The blame table (# | Function | File | Last MR | Intent | Author | Confidence)
3. Expand the "Blame graph" details section to show the Mermaid diagram
4. The "Analysis" section with the investigation hint
5. The "Loop in:" @mention line

**VOICEOVER:**
> "Two minutes after the alert fired, here's what the on-call engineer sees. Primary suspect: MR !342, merged 4 days ago, implementing payment retry logic for issue #89. The function `processPayment` is at depth 1 — the frame that threw the error. The MR was authored by @alice, reviewed by @dave, and CI passed at the time of merge."

> "The analysis section gives an error-type-specific hint: this is a TypeError, so RootChain flags the return type change in the retry branch as the likely cause. No git blame. No Slack messages. This context was already in Orbit."

---

## [2:45–3:00] The Close (15 seconds)

**SCREEN:** Switch to the README architecture diagram (either the mermaid chart in README.md rendered on GitHub, or the flowchart image).

**VOICEOVER:**
> "The core insight is inversion: start from a production error, walk backward through Orbit's graph, and surface the causal human decision. RootChain is open-source, MIT-licensed, and published to the GitLab AI Catalog. The same pattern extends to security triage and CI failure attribution. Links in the description."

---

## Recording Tips

- **Do a full timed dry run before recording.** If you're over 3:00, cut the Orbit query detail section to 25 seconds.
- **Edit out the 90-second wait** between creating the test issue and the comment appearing. Jump cut directly to the result.
- **If the flow has never run in a live environment**, use the dry-run terminal output as a substitute for the flow log section. Show `python -m src.rootchain.orchestrator --dry-run` printing the full Markdown comment to the terminal — it's a clear demonstration of the analysis.
- **Captions**: Use YouTube's auto-captions and review before publishing.
- **Upload as Public**, not Unlisted — the judges must be able to watch without logging in.

## Fallback: Showing dry-run output instead of live GitLab

If you don't have a live Orbit-enabled GitLab instance:

```bash
# This shows the full analysis pipeline without any live API calls
# Pre-populate a mock issue description in a file:
cat > /tmp/issue.txt << 'EOF'
## TypeError: 'NoneType' object is not subscriptable

Traceback (most recent call last):
  File "payments/processor.py", line 142, in processPayment
    result_id = gateway_response['id']
  File "payments/gateway.py", line 88, in call_gateway
    return self._session.post(url, data=payload)
EOF

# Then run with dry-run (will show orbit_miss since no real Orbit)
# Alternatively, use the test fixtures to demonstrate parser:
python -c "
from src.rootchain.config import Config
from src.rootchain.sentry_parser import SentryParser
import os
os.environ['ROOTCHAIN_GITLAB_TOKEN'] = 'demo'
os.environ['ROOTCHAIN_GITLAB_URL'] = 'https://gitlab.com'
os.environ['ROOTCHAIN_GROUP_PATH'] = 'demo-group'
os.environ['ROOTCHAIN_PROJECT_PATH'] = 'demo-group/demo-project'
config = Config.from_env()
parser = SentryParser(config)
with open('tests/fixtures/sentry_python.json') as f:
    import json; data = json.load(f)
event = parser.parse(data['title'], data['description'])
if event:
    print(f'Parsed: {event.error_type}: {len(event.frames)} frames')
    for f in event.frames:
        print(f'  [{f.frame_depth}] {f.function_name} in {f.file_path}:{f.line_number}')
"
```

## Timestamps to aim for

| Section | Target | Maximum |
|---------|--------|---------|
| Problem | 0:20 | 0:25 |
| The Flow | 0:45 | 0:50 |
| Trigger | 1:20 | 1:30 |
| Orbit Queries | 2:00 | 2:10 |
| Output | 2:45 | 2:55 |
| Close | 3:00 | 3:00 |
