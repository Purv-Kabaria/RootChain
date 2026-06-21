# Demo Script — 3 Minutes

Record at 1080p. No background music. Narrate everything you show.

---

## [0:00–0:20] The Problem (20 seconds)

**Screen:** Show a Sentry alert with a Python stack trace — the `TypeError: 'NoneType' object is not subscriptable` example.

**Say:**
> "This is what every on-call engineer sees at 2am. A Sentry alert with a stack trace. Now starts the archaeology: git blame on each frame, search closed issues, find the MR that changed it, message the author. This takes 30 to 90 minutes before a single line of fix is written. The answer has been sitting inside GitLab the whole time."

---

## [0:20–0:40] The Setup (20 seconds)

**Screen:** Show the `.gitlab/duo-flows/rootchain.yml` file briefly, then navigate to **Duo Agent Platform → Flows → rootchain → active**.

**Say:**
> "RootChain is a GitLab Duo Agent Platform flow. It activates automatically whenever Sentry creates a GitLab issue. No additional infrastructure — just a YAML file in your repo and GitLab Orbit enabled on your group."

---

## [0:40–1:20] The Demo — Flow Activating (40 seconds)

**Screen:** Run the test issue generator:
```bash
python scripts/generate_test_issue.py \
  --project-path "myorg/myapp" \
  --token "$ROOTCHAIN_GITLAB_TOKEN" \
  --language python
```

Show the GitLab issue being created (with the `sentry-alert` label).

**Say:**
> "I'm creating a test GitLab issue that looks exactly like what Sentry's native integration creates. Watch the Duo Agent Platform — the RootChain flow activates within seconds of the issue being created."

Navigate to **Duo Agent Platform → Flows → rootchain → Recent Runs** and show the run in progress.

---

## [1:20–2:00] The Orbit Queries (40 seconds)

**Screen:** Show the flow run log — specifically the `query_graph` calls. Highlight one call showing the Cypher query and the result with MR data.

**Say:**
> "For each stack frame, RootChain runs Orbit graph queries. This query traverses three hops: function symbol to file to merge request. Orbit returns the MR that last modified `processPayment()`, when it was merged, and who authored it. A second query finds the work item that MR closed — the business intent. A third counts how many functions call this one, measuring its blast radius."

---

## [2:00–2:30] The Output Comment (30 seconds)

**Screen:** Navigate to the GitLab issue. Scroll to the new comment from RootChain.

**Say:**
> "Two minutes after the alert fired, the issue has a RootChain comment. There's a ranked blame table: each frame, its last MR, the intent behind it, the author, and a confidence score. The primary suspect is MR !342, merged 4 days ago, implementing payment retry logic. RootChain suggests reviewing the retry branch in `processPayment()` around line 142 for the null gateway response case. @alice is mentioned because she authored the MR. All of this came from GitLab Orbit — no guessing, no hallucination."

---

## [2:30–3:00] The Why and What's Next (30 seconds)

**Screen:** Show the Mermaid flow diagram from the README or the architecture ASCII art.

**Say:**
> "The key insight is the multi-hop path: runtime error → function symbol → merge request → work item → business intent. This exists in Orbit's graph; RootChain just traverses it automatically. The same pattern extends to security triage — tracing a CVE to the MR that introduced the vulnerability — and to CI failure attribution. RootChain is published to the GitLab AI Catalog and open-source under MIT. Thank you."

---

## Recording Tips

- Use OBS or QuickTime. Record at 1920×1080.
- Zoom browser to 125% so text is readable in the recording.
- Do a dry run first — time it against a stopwatch.
- If the flow takes > 2 minutes, edit the video to cut the waiting and show the result.
- Upload to YouTube as **unlisted**, paste the URL in the Devpost submission.
- Caption: use YouTube's auto-captions and review them.

## Commands to prepare before recording

```bash
# 1. Verify flow is active
curl -s --header "PRIVATE-TOKEN: $ROOTCHAIN_GITLAB_TOKEN" \
  "https://gitlab.com/api/v4/projects/YOUR_PROJECT_ID/ai/agent_flows" \
  | python -c "import sys,json; [print(f['name'], f['status']) for f in json.load(sys.stdin)]"

# 2. Verify Orbit is healthy
python scripts/test_orbit_connection.py

# 3. Have the test issue generator ready
python scripts/generate_test_issue.py --help
```
