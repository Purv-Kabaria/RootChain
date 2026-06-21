# Configuration Reference

All RootChain configuration is driven by environment variables. Copy `.env.example` to `.env`
for local development. In GitLab CI, set variables under **Settings → CI/CD → Variables**.

---

## Required Variables

| Variable | Example | Description |
|----------|---------|-------------|
| `ROOTCHAIN_GITLAB_TOKEN` | `glpat-xxxx` | Personal Access Token with `api` scope. Must have write access to the target project. Mask this in CI. |
| `ROOTCHAIN_GITLAB_URL` | `https://gitlab.com` | Base URL of your GitLab instance. Trailing slash is stripped automatically. |
| `ROOTCHAIN_GROUP_PATH` | `my-org` | Top-level group path with GitLab Orbit enabled. All Orbit queries are scoped to this group. |
| `ROOTCHAIN_PROJECT_PATH` | `my-org/my-app` | Full path of the project where Sentry issues land. Used for GitLab API calls (notes, labels). |

---

## Orbit Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `ROOTCHAIN_ORBIT_TIMEOUT_SECONDS` | `30` | Per-query timeout in seconds. Increase to `60` for large Orbit graphs. Range: 5–120. |
| `ROOTCHAIN_ORBIT_MAX_RETRIES` | `3` | Number of retry attempts on Orbit timeout or 5xx. Uses exponential backoff. |
| `ROOTCHAIN_ORBIT_RETRY_BASE_SECONDS` | `2` | Base delay for exponential backoff. Actual delays: 2s, 4s, 8s. |

---

## Parsing Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `ROOTCHAIN_MAX_FRAMES` | `5` | Maximum number of stack frames to analyze per issue. Increasing beyond 10 is rarely useful. Range: 1–10. |
| `ROOTCHAIN_INCLUDE_LIBRARY_FRAMES` | `false` | When `true`, library/runtime frames are included in analysis. Useful for debugging false-miss issues but generates noisy output. |

---

## Confidence Scoring

These weights must sum to exactly `1.0`. RootChain validates this on startup and fails fast if they don't.

| Variable | Default | Description |
|----------|---------|-------------|
| `ROOTCHAIN_CONFIDENCE_THRESHOLD` | `0.4` | Minimum score for a `BlameEntry` to be chosen as the `primary_suspect`. Entries below this are shown in the table but flagged as LOW confidence. |
| `ROOTCHAIN_RECENCY_WEIGHT` | `0.5` | Weight of the recency component. A change from 4 days ago is far more suspect than one from 6 months ago. |
| `ROOTCHAIN_DEPTH_WEIGHT` | `0.35` | Weight of the frame-depth component. The frame closest to the error source gets depth score 1.0; frame 5 gets 0.2. |
| `ROOTCHAIN_BLAST_WEIGHT` | `0.15` | Weight of the blast-radius component. A function called from many places is more likely to cause cascading failures. |
| `ROOTCHAIN_RECENCY_HALF_LIFE_DAYS` | `30` | Days until the recency score halves. Default: a merge from 30 days ago scores 0.5; from today scores 1.0. |

### Formula

```
recency   = 1.0 / (1 + days_since_merge / HALF_LIFE_DAYS)
depth     = 1.0 / frame_depth
blast     = min(caller_count / 10.0, 1.0)
score     = recency × W_RECENCY + depth × W_DEPTH + blast × W_BLAST
```

Apply modifiers:
- If file-level fallback was used: `score × 0.7`
- If `orbit_miss`: `score = 0.0`

---

## Output Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `ROOTCHAIN_ADD_LABEL` | `rootchain-analyzed` | Label applied to the issue after analysis. Used as the idempotency guard — issues already carrying this label are skipped. |
| `ROOTCHAIN_MENTION_AUTHORS` | `true` | @mention MR authors in the "Loop in:" section. Set to `false` in high-alert-volume projects to reduce noise. |
| `ROOTCHAIN_MENTION_REVIEWERS` | `false` | @mention MR reviewers in addition to authors. Off by default as it can be very noisy. |
| `ROOTCHAIN_MAX_MENTION_USERS` | `3` | Maximum number of unique users to @mention across the entire comment. |

---

## Webhook Receiver Settings (Option B only)

Only needed if you're using `receiver/main.py` instead of the native Sentry–GitLab integration.

| Variable | Default | Description |
|----------|---------|-------------|
| `ROOTCHAIN_WEBHOOK_SECRET` | _(empty)_ | HMAC-SHA256 secret for validating Sentry webhook signatures. Set this to the same secret configured in Sentry's internal integration. |
| `ROOTCHAIN_WEBHOOK_PORT` | `8080` | Port for the webhook receiver to listen on. |

---

## Logging Settings

| Variable | Default | Options | Description |
|----------|---------|---------|-------------|
| `ROOTCHAIN_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | Log verbosity. Use `DEBUG` when diagnosing Orbit query issues. |
| `ROOTCHAIN_LOG_FORMAT` | `json` | `json`, `console` | `json` for production (forward to Elasticsearch, Loki, etc.). `console` for local development (human-readable colored output). |

---

## Tuning Guide

### "Too many false positives — old MRs being flagged"
Lower `ROOTCHAIN_RECENCY_HALF_LIFE_DAYS` (try `14`) or raise `ROOTCHAIN_CONFIDENCE_THRESHOLD` (try `0.6`).

### "Missing results — real culprit not showing up"
- Lower `ROOTCHAIN_CONFIDENCE_THRESHOLD` (try `0.3`)
- Increase `ROOTCHAIN_MAX_FRAMES` (try `8`)
- Check that the repository is under `ROOTCHAIN_GROUP_PATH` in Orbit

### "All frames show orbit_miss"
Run `python scripts/test_orbit_connection.py` to verify Orbit is reachable. Verify the code is on the default branch — Orbit only indexes the default branch.

### "Comments are too noisy with @mentions"
Set `ROOTCHAIN_MENTION_AUTHORS=false` and `ROOTCHAIN_MENTION_REVIEWERS=false`.
