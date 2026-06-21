# Troubleshooting

---

## Flow Issues

### Flow did not activate after issue creation

**Check 1:** Does the issue have at least one of the trigger labels?

```bash
# Fetch issue labels
curl -s --header "PRIVATE-TOKEN: $ROOTCHAIN_GITLAB_TOKEN" \
  "https://gitlab.com/api/v4/projects/$(python -c "from urllib.parse import quote; print(quote('your-group/your-project', safe=''))")/issues/42" \
  | python -c "import sys,json; print(json.load(sys.stdin)['labels'])"
```

Required: `sentry-alert` or `Sentry`. If neither is present, [configure Sentry to add them](./sentry_setup.md).

**Check 2:** Verify Duo Agent Platform recognizes the flow.

In your GitLab project: **Duo Agent Platform → Flows**. The `rootchain` flow should appear with status `active`. If it's missing, ensure `.gitlab/duo-flows/rootchain.yml` is on the default branch.

**Check 3:** Check flow execution logs.

**Project → Duo Agent Platform → Flows → rootchain → Recent Runs**

---

### Flow activated but posted no comment

The issue may already have the `rootchain-analyzed` label (idempotency guard). Check:

```bash
curl -s --header "PRIVATE-TOKEN: $ROOTCHAIN_GITLAB_TOKEN" \
  "$GITLAB_URL/api/v4/projects/$(python -c "from urllib.parse import quote; print(quote('$ROOTCHAIN_PROJECT_PATH', safe=''))")/issues/$ISSUE_IID" \
  | python -c "import sys,json; d=json.load(sys.stdin); print(d['labels'])"
```

If `rootchain-analyzed` is present, remove it and re-trigger the flow to re-analyze.

---

### "No parseable stack trace found"

The issue description doesn't contain a recognizable stack trace.

1. Verify the description format matches [Sentry's GitLab issue format](./sentry_setup.md#sentry-issue-format)
2. Run locally to debug:
   ```bash
   ROOTCHAIN_LOG_LEVEL=DEBUG python -c "
   from src.rootchain.config import Config
   from src.rootchain.sentry_parser import SentryParser
   config = Config.from_env()
   parser = SentryParser(config)
   desc = open('your_issue_description.txt').read()
   result = parser.debug_parse('[Sentry] Test', desc)
   import json; print(json.dumps(result, indent=2, default=str))
   "
   ```
3. Check `raw_frame_counts` in the debug output. If all are 0, the format is not recognized.

---

## Orbit Issues

### "Orbit status is not healthy"

Run the smoke test:
```bash
python scripts/test_orbit_connection.py
```

Common causes:
- Orbit is not enabled on the group: Go to **Group → Settings → AI & Analytics → Orbit → Enable**
- Your GitLab tier doesn't include Orbit (requires Premium or Ultimate)
- Orbit is still indexing — initial indexing takes 10–30 minutes for large groups

Check group indexing status:
```bash
curl -s --header "PRIVATE-TOKEN: $ROOTCHAIN_GITLAB_TOKEN" \
  "$GITLAB_URL/api/v4/groups/YOUR_GROUP_ID/orbit/status" \
  | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('indexing_status', 'unknown'))"
```

Expected: `indexed` or `indexing`.

---

### "Orbit queries return 0 results for all frames"

1. **File path mismatch.** The path in the stack trace might not match what Orbit has indexed. Orbit indexes relative paths from the repository root. Check:
   ```bash
   # Query Orbit for files matching your path
   curl -s -X POST "$GITLAB_URL/api/v4/orbit/query" \
     -H "PRIVATE-TOKEN: $ROOTCHAIN_GITLAB_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"query": "MATCH (f:File) WHERE f.path CONTAINS $p RETURN f.path LIMIT 5", "parameters": {"p": "processor.py"}}'
   ```

2. **Code is on a non-default branch.** Orbit only indexes the default branch (`main` or `master`). Ensure the code is merged to the default branch.

3. **Recent merge.** Code merged within the last ~1 hour may not be indexed yet. Orbit re-indexes on a cycle.

4. **Project outside Orbit group.** The project must be under `ROOTCHAIN_GROUP_PATH`. Verify:
   ```bash
   # Should show your project's namespace
   curl -s --header "PRIVATE-TOKEN: $ROOTCHAIN_GITLAB_TOKEN" \
     "$GITLAB_URL/api/v4/projects/$(python -c "from urllib.parse import quote; print(quote('$ROOTCHAIN_PROJECT_PATH', safe=''))")" \
     | python -c "import sys,json; d=json.load(sys.stdin); print(d['namespace']['full_path'])"
   ```

---

### Orbit API timeout

Default timeout is 30 seconds. For large graphs, increase:
```
ROOTCHAIN_ORBIT_TIMEOUT_SECONDS=60
```

The retry logic will retry 3 times (configurable via `ROOTCHAIN_ORBIT_MAX_RETRIES`).

---

### High Orbit latency in CI

If the smoke test stage is slow, verify you're not querying Orbit from a region
far from your GitLab instance. For GitLab.com, EU-west runners have lower latency.

---

## GitLab API Issues

### HTTP 403 on issue update

The `ROOTCHAIN_GITLAB_TOKEN` needs `api` scope (not just `read_api`). Check:
```bash
curl -s --header "PRIVATE-TOKEN: $ROOTCHAIN_GITLAB_TOKEN" \
  "$GITLAB_URL/api/v4/user" | python -c "import sys,json; print(json.load(sys.stdin).get('username', 'error'))"
```

If this returns an error, the token is invalid. If it returns a username but the 403 persists, the token doesn't have `api` scope or doesn't have access to the project.

For **group tokens**: ensure group-level API access is enabled under **Group → Settings → General → Permissions**.

---

### HTTP 429 rate limit on issue note creation

GitLab API has rate limits (typically 300 requests/minute per user for REST API). 
RootChain's `GitLabClient` automatically reads `Retry-After` and waits. If you're
processing many issues simultaneously, consider:
- Running the flow with a bot user that has higher rate limits
- Reducing `ROOTCHAIN_MAX_FRAMES` to make fewer Orbit queries per issue

---

## Confidence Score Issues

### "Confidence scores are all 0.0"

All frames returned `orbit_miss=True`. See the "Orbit queries return 0 results" section above.

### "Primary suspect is always the same old MR"

The recency weight (50%) ensures recent changes are preferred. If an old MR keeps
winning, it may be because:
1. No newer MRs have modified that function (it hasn't changed recently)
2. The function is very deep in the call stack (low depth score) but has high caller count

Consider lowering `ROOTCHAIN_CONFIDENCE_THRESHOLD` and checking if the analysis
is actually correct — the old MR may genuinely be the culprit.

### "All scores are LOW (below 0.4)"

Check:
1. Are all MRs from more than 60 days ago? Recency score drops significantly over time.
2. Is `fallback_used=True` for all frames? The 0.7× penalty reduces scores by 30%.
3. Is the code analyzed rarely called? Low `caller_count` reduces blast score.

---

## Local Development Issues

### `ModuleNotFoundError: No module named 'rootchain'`

Install the package in editable mode:
```bash
pip install -e ".[dev]"
```

### `RuntimeError: Required environment variable 'ROOTCHAIN_GITLAB_TOKEN' is not set`

Copy `.env.example` to `.env` and fill in your values, then:
```bash
# Using python-dotenv (installed automatically)
python -c "from dotenv import load_dotenv; load_dotenv(); from src.rootchain.config import Config; print(Config.from_env())"
```

### Tests fail with `ImportError`

Ensure you're in the project root directory and the virtualenv is activated:
```bash
cd /path/to/rootchain
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/unit/ -v
```
