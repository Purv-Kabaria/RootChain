# RootChain Demo Script

Target length: 2:30-3:00. Record at 1920x1080. Browser zoom 125%.

## Demo Goal

Show RootChain solving a real incident workflow:

1. A production issue arrives with a stack trace.
2. The failure mode is ambiguous: RootChain starts and marks the issue analyzed, but the useful blame chain is missing.
3. RootChain walks backward through Orbit and identifies the MR that changed the failing code.
4. The output gives the on-call engineer a production-ready next step.

## Before Recording

The ready-to-record issue is:

```text
https://gitlab.com/purv-kabaria-group/rootchain/-/work_items/15
```

Open these tabs:

| Tab | URL | Purpose |
|---|---|---|
| 1 | `https://gitlab.com/purv-kabaria-group/rootchain/-/work_items/15` | Production incident with RootChain output |
| 2 | `https://gitlab.com/purv-kabaria-group/rootchain/-/merge_requests/2` | Root-cause MR |
| 3 | `https://gitlab.com/purv-kabaria-group/rootchain/-/merge_requests/3` | Distractor MR |
| 4 | `https://gitlab.com/purv-kabaria-group/rootchain/-/blob/main/.gitlab/duo-flows/rootchain.yml` | Flow definition |
| 5 | `https://github.com/Purv-Kabaria/RootChain` | README / close |

Issue `#15` is already created and has a RootChain analysis comment. To recreate it,
create a fresh issue from `docs/demo_issue.md`, then either let the Duo flow run or run
the local orchestrator against the issue to post the comment:

```powershell
.venv\Scripts\Activate.ps1
python -m src.rootchain.orchestrator `
  --project-path "purv-kabaria-group/rootchain" `
  --issue-iid <NEW_ISSUE_IID>
```

The expected comment should identify MR `!2` as the primary suspect and show
`_find_mrs_for_file` in `orbit_client.py` as the highest-confidence row.

## Recording

### 0:00-0:25 - The Problem

Screen: demo issue title, impact section, and stack trace.

Say:

> "This is the kind of incident RootChain is built for. The flow starts, the issue can
> be marked analyzed, but the useful blame chain is missing. That is a silent production
> degradation: the on-call engineer still has to manually search stack frames and recent
> MRs. The stack trace points at `orbit_client.py`, but the real question is which MR
> changed the Orbit lookup path and why."

### 0:25-0:45 - The Flow

Screen: `.gitlab/duo-flows/rootchain.yml`.

Say:

> "RootChain is a GitLab Duo Agent Platform flow. On a new issue, it reads the stack
> trace, queries GitLab Orbit with `query_graph`, posts a note, and adds an idempotency
> label. The important part is that it starts from runtime evidence, not from a commit
> or a hand-picked file."

### 0:45-1:25 - The Orbit Walk

Screen: RootChain comment table.

Show:

1. Primary suspect line.
2. Row 1: `_find_mrs_for_file`, `orbit_client.py:238`, MR `!2`, HIGH confidence.
3. Row 2: `orchestrator.py`, MR `!3`, lower-ranked distractor.

Say:

> "The top row is the failing lookup path: `_find_mrs_for_file` in `orbit_client.py`.
> Orbit connects that file to MR `!2`, the response parsing refactor. The next frame
> points at MR `!3`, the timeout feature, which is plausible noise but not the origin.
> The confidence score ranks the Orbit lookup frame higher because it is closest to the
> low-signal failure and recently changed."

### 1:25-2:05 - The Causal Decision

Screen: MR `!2`, title and description.

Say:

> "This is what normally takes the time. MR `!2` is the recent Orbit response parsing
> refactor. It changed the assumptions around the shape of Orbit data and added response
> diagnostics. RootChain surfaces that decision and the author immediately, instead of
> making the on-call engineer reconstruct it from git blame."

### 2:05-2:35 - The Fix

Screen: RootChain comment analysis / fix prompt.

Say:

> "The next action is production-like and narrow: replace the neighbor-only file lookup
> with the project-scoped MR diff traversal using `old_path` first, keep the legacy
> queries as fallbacks, and add a regression test. The on-call engineer does not need
> to ask who touched it or manually inspect every MR. The context is already in GitLab."

### 2:35-3:00 - Close

Screen: README architecture or repository landing page.

Say:

> "RootChain generalizes this pattern. Any issue with a stack trace can be traced
> backward through Orbit: runtime error to stack frame, stack frame to MR, MR to intent,
> author, CI, and security context. That turns incident triage from archaeology into a
> ranked, actionable blame chain."

## If the Live Flow Is Slow

Use a jump cut. Show the issue being created, then cut to "90 seconds later" with the
RootChain comment visible.

## If the Flow Does Not Fire

Use the local orchestrator command above. Say:

> "For the demo I am running the same RootChain pipeline locally against the live
> GitLab issue. It still fetches the issue, queries live Orbit, and posts the same
> GitLab comment."

## Final Recording Checklist

- RootChain comment shows MR `!2` as primary suspect.
- Table includes at least one distractor MR so the ranking is visible.
- MR `!2` description is shown on screen.
- The final fix is concrete: use project-scoped `Project <-IN_PROJECT- MergeRequest -HAS_DIFF-> MergeRequestDiff -HAS_FILE-> MergeRequestDiffFile` traversal with `old_path` first.
- Video is public, not unlisted.

