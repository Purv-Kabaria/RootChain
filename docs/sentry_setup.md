# Sentry Integration Setup

RootChain supports two ways to receive Sentry alerts:

- **Option A** — Native Sentry–GitLab integration (recommended, zero infrastructure)
- **Option B** — Webhook receiver (fallback if native integration is unavailable)

---

## Option A — Native Integration

Sentry's native GitLab integration creates GitLab issues automatically when an
alert fires. This is the recommended path because it requires no additional services.

### Step 1: Create the `sentry-alert` label

In your GitLab project: **Settings → Labels → New label**

- Name: `sentry-alert`
- Color: `#e24329` (red)
- Description: "Created by Sentry automatic alert"

### Step 2: Connect Sentry to GitLab

In Sentry: **Settings → Integrations → GitLab**

1. Click **Add Installation**
2. Authorize Sentry's OAuth app in GitLab
3. Select the GitLab group or project to connect

### Step 3: Configure Sentry alert rules

In Sentry: **Alerts → Alert Rules → New Alert Rule**

1. Select: **Issue Alert**
2. Conditions: choose when to fire (e.g., "A new issue is created")
3. Actions: **Create a GitLab issue**
   - Project: your GitLab project
   - Labels to add: `Sentry, sentry-alert`
   - Title format: `[Sentry] {title}` ← this format triggers RootChain's title filter

### Step 4: Verify

Create a test issue manually to confirm the flow:

```bash
python scripts/generate_test_issue.py \
  --project-path "your-group/your-project" \
  --token "$ROOTCHAIN_GITLAB_TOKEN" \
  --language python
```

RootChain should analyze the issue within ~2 minutes.

---

## Option B — Webhook Receiver

Use this if the native Sentry–GitLab integration is not available (e.g., Sentry
self-hosted without GitLab OAuth, or you need more control over issue creation).

### Step 1: Deploy the receiver

```bash
cd receiver/

# Set secrets
fly secrets set ROOTCHAIN_GITLAB_TOKEN="glpat-xxx"
fly secrets set ROOTCHAIN_WEBHOOK_SECRET="your-32-char-random-secret"
fly secrets set ROOTCHAIN_GITLAB_URL="https://gitlab.com"
fly secrets set ROOTCHAIN_PROJECT_PATH="your-group/your-project"
fly secrets set ROOTCHAIN_GROUP_PATH="your-group"

# Deploy
fly deploy
```

The receiver will be available at `https://rootchain-receiver.fly.dev`.

### Step 2: Configure Sentry webhook

In Sentry: **Settings → Developer Settings → Internal Integrations → New**

- Name: `RootChain`
- Webhook URL: `https://rootchain-receiver.fly.dev/webhook/sentry`
- Events: `Issue` (check both `created` and `triggered`)
- Add header: `X-RootChain-Secret: your-32-char-random-secret`

### Step 3: Test

```bash
curl -X POST https://rootchain-receiver.fly.dev/health
# {"status": "ok", "version": "0.1.0"}
```

---

## Sentry Issue Format

RootChain understands the issue format created by Sentry's native GitLab integration.

### Title pattern

```
[Sentry] ErrorType: error message
```

Examples:
- `[Sentry] TypeError: Cannot read property 'id' of undefined`
- `[Sentry] NullPointerException: Cannot invoke method getId() on null object`
- `[Sentry] panic: runtime error: index out of range`

The flow's `title_matches` filter accepts these patterns:
```
^\[Sentry\]|\[Error\]|TypeError|ValueError|NullPointerException|RuntimeError|ReferenceError|panic
```

### Description format

Sentry creates descriptions in this format (example for Python):

```markdown
## TypeError: 'NoneType' object is not subscriptable

**Sentry Issue:** https://sentry.io/organizations/myorg/issues/1234567/

**Culprit:** `payments/processor.py in processPayment`

**Times seen:** 47
**Users affected:** 12
**Environment:** production
**First seen:** 2024-01-15T02:14:37Z
**Last seen:** 2024-01-15T02:47:12Z

### Stacktrace

```
Traceback (most recent call last):
  File "/app/payments/processor.py", line 142, in processPayment
    result_id = gateway_response['id']
  ...
TypeError: 'NoneType' object is not subscriptable
```
```

RootChain parses the `### Stacktrace` section to extract frames.

---

## Label Requirements

The flow activates when an issue has **at least one** of these labels:
- `sentry-alert`
- `Sentry`

If your Sentry integration doesn't add either label, add a GitLab label event
trigger:

1. **Settings → Integrations → Pipeline Triggers** or use the GitLab API:

```bash
# Add sentry-alert whenever Sentry label is added via webhook
# (example: use GitLab group label events to auto-add sentry-alert)
```

Or configure Sentry to add `sentry-alert` directly in its GitLab integration
settings under **Additional Labels**.

---

## Supported Languages

| Language | Stack trace format | Library filter |
|----------|-------------------|----------------|
| Python | `File "path", line N, in func` | `site-packages/`, `/usr/lib/`, `/usr/local/lib/` |
| JavaScript/TypeScript | `at FuncName (path:line:col)` | `node_modules/`, `dist/` |
| Go | `goroutine N [...]\nfunc(args)\n\tfile.go:line` | `/usr/local/go/`, `vendor/` |
| Ruby | `path:line:in 'method'` | `gems/`, `rubygems/` |
| Java | `at class.method(File.java:line)` | `java.`, `sun.`, `javax.`, `org.springframework.` |

For unknown languages, RootChain tries all parsers in order and uses the first
that yields parseable frames.

---

## Source Maps (JavaScript)

Minified JavaScript produces stack traces with `<anonymous>` function names, which
RootChain filters out. To get useful stack traces:

1. In Sentry: **Settings → Projects → {project} → Source Maps**
2. Upload source maps with each deployment, or configure Sentry's release integration
3. Verify: Sentry should show de-minified stack traces with real function names

Without source maps, RootChain will comment "all frames were anonymous/skipped"
and not perform an analysis.
