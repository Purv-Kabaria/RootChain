# RootChain Demo Issue

Use this issue for the demo recording. It is based on a real RootChain failure observed
in the live GitLab project: a flow run started, the issue was marked analyzed, but no
useful RootChain blame comment was posted.

## Issue Title

```text
[P1] RootChain marks incidents analyzed but returns no useful Orbit blame data
```

## Issue Description

Copy everything below this line into the GitLab issue description.

---

## RootChainLowSignalAnalysis: all frames returned orbit_miss

**Service:** RootChain Duo flow  
**Environment:** GitLab.com project `purv-kabaria-group/rootchain`  
**Severity:** P1  
**First observed:** 2026-06-23 12:28 UTC  
**Detection source:** https://gitlab.com/purv-kabaria-group/rootchain/-/work_items/13  
**Flow session:** https://gitlab.com/purv-kabaria-group/rootchain/-/automate/agent-sessions/4660616

### Impact

RootChain is supposed to shorten incident triage by posting a ranked MR blame chain on
new production error issues. Instead, an issue can be marked `rootchain-analyzed` while
the output contains no actionable MR, author, or confidence signal.

This is a high-risk silent failure mode for on-call: the automation appears to have run,
but the engineer still has to manually inspect stack frames, search recent MRs, and infer
which change caused the regression.

### Evidence From The Live Project

- Orbit is enabled and healthy for `purv-kabaria-group/rootchain`.
- Orbit returns the project node for `purv-kabaria-group/rootchain`.
- Orbit returns file nodes for `src/rootchain/orbit_client.py`.
- Orbit returns merged MRs `!1`, `!2`, and `!3` in the project.
- The old RootChain query shape still misses useful blame data for some frames because it
  relies on direct neighbor lookups and `MergeRequestDiffFile.new_path`.
- A project-scoped traversal through MR diff snapshots using `old_path` returns the real MR.

### Stacktrace

Sentry-style frame order: closest-to-error first.

```text
RootChainLowSignalAnalysis: all frames resolved to orbit_miss despite indexed Orbit data
  File "src/rootchain/orbit_client.py", line 238, in _find_mrs_for_file
    nodes = await self._get_neighbors("MergeRequestDiffFile", {"new_path": file_path})
  File "src/rootchain/orbit_client.py", line 231, in _find_mrs_for_file
    nodes = await self._get_neighbors("File", {"path": file_path})
  File "src/rootchain/orbit_client.py", line 405, in _get_neighbors
    return await self._run_with_retry({...})
  File "src/rootchain/orchestrator.py", line 132, in _analyze
    histories = await orbit.get_symbol_histories(list(event.frames))
  File "src/rootchain/orchestrator.py", line 80, in run_analysis
    await _analyze(...)
```

### What The On-Call Engineer Needs

Identify the MR that changed RootChain's Orbit lookup behavior, explain the intent behind
that change, and point to the smallest production-safe fix. The answer should use real
GitLab/Orbit data, not guessed MR titles or authors.

---

## Expected RootChain Result

The useful demo outcome is:

- Primary suspect points to a real MR in `purv-kabaria-group/rootchain`.
- The top stack frame is in `src/rootchain/orbit_client.py`.
- The table shows a real MR URL, author, and confidence score.
- The investigation points at replacing direct neighbor-only file lookup with the
  project-scoped `Project <-IN_PROJECT- MergeRequest -HAS_DIFF-> MergeRequestDiff
  -HAS_FILE-> MergeRequestDiffFile` traversal using `old_path` first.
