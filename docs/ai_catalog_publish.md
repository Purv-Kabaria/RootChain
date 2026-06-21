# Publishing RootChain to the GitLab AI Catalog

The hackathon requires at least one flow published to the AI Catalog.
This document covers what to do and what to expect.

> **Important:** The AI Catalog UI path and publish mechanism varies by
> GitLab version. The steps below reflect GitLab 18.x. If something doesn't
> match what you see, try the alternatives in the "Can't find the button"
> section at the bottom.

---

## Prerequisites

Before publishing, confirm:

- [ ] Your GitLab project is **public**
  (`https://gitlab.com/YOUR_USERNAME/rootchain` must be accessible without login)
- [ ] MIT `LICENSE` file is in the repo root
- [ ] `.gitlab/duo-flows/rootchain.yml` is on the default (`main`) branch
- [ ] `.gitlab/skills/rootchain/SKILL.md` is on the default branch
- [ ] Left sidebar → **AI** → **Flows** shows `rootchain` with status **active**

If the flow isn't showing as active, push the code first. See `docs/submission_guide.md`.

---

## How to Publish

### Try these paths in order — stop at whichever works:

**Path A — From the flow detail:**
1. Left sidebar → **AI** → **Flows**
2. Click **rootchain** to open the flow detail
3. Look for a **"Publish to catalog"** or **"Share to AI Catalog"** button
4. Fill in the metadata (see below) and submit

**Path B — From the AI Catalog explore page:**
1. Go to https://gitlab.com/explore/ai-catalog
2. Look for **"Submit"** or **"Add project"** button (usually top-right)
3. Enter your project URL: `https://gitlab.com/YOUR_USERNAME/rootchain`
4. Fill in the metadata and submit

**Path C — From group/project settings:**
1. Left sidebar → **Settings** → **GitLab Duo** (or **AI**)
2. Look for AI Catalog publishing options

---

## Metadata to Fill In

Paste this exactly when you reach the publish form:

| Field | Value |
|-------|-------|
| **Name** | RootChain |
| **Short description** | Trace Sentry production errors to their SDLC origin via GitLab Orbit — automatically in under 2 minutes. |
| **Category** | DevSecOps / Incident Response |
| **Tags** | `orbit`, `sentry`, `incident-response`, `blame-chain`, `sdlc`, `debugging` |
| **Version** | `0.1.0` |
| **License** | MIT |

**Long description:**

```
RootChain is a GitLab Duo Agent Platform flow that automatically traces
production Sentry errors to their SDLC origin.

When Sentry creates a GitLab issue for a production alert, RootChain:
1. Parses the stack trace (Python, Node.js, Go, Ruby, Java, Kotlin, Rust)
2. Queries GitLab Orbit across 4 domains: source_code, code_review,
   security, and ci — finding which MR last modified each function symbol,
   the business intent behind it, any active CVEs, and CI pipeline status
3. Scores each frame: confidence = recency×0.5 + depth×0.35 + blast×0.15
4. Posts a ranked blame-chain analysis comment within 2 minutes

Setup: GitLab Duo enabled + Sentry-GitLab integration.
Full setup guide: https://github.com/Purv-Kabaria/RootChain
```

---

## After Publishing

1. Copy the catalog URL — it will look like:
   `https://gitlab.com/explore/ai-catalog/flows/YOUR_USERNAME/rootchain`
2. Paste it into the Devpost submission form's AI Catalog field

---

## If You Can't Find the Publish Button

The catalog publish feature may not be visible on all account types or GitLab versions.

**Fallback for Devpost submission:**
- In the AI Catalog URL field on Devpost, paste your GitLab project URL:
  `https://gitlab.com/YOUR_USERNAME/rootchain`
- In your "How we built it" section, mention:
  *"Published to AI Catalog — see project at gitlab.com/YOUR_USERNAME/rootchain"*
- Contact the hackathon organizers via the Devpost page if you need help getting
  the catalog entry approved before the deadline

**Fallback API (if the UI doesn't work):**
```bash
curl --request POST \
  --header "PRIVATE-TOKEN: $ROOTCHAIN_GITLAB_TOKEN" \
  --header "Content-Type: application/json" \
  --data '{
    "flow_name": "rootchain",
    "display_name": "RootChain",
    "description": "Trace Sentry production errors to their SDLC origin via GitLab Orbit. Automated blame chain in under 2 minutes.",
    "tags": ["orbit", "sentry", "incident-response", "blame-chain", "sdlc"],
    "version": "0.1.0",
    "source_url": "https://gitlab.com/YOUR_USERNAME/rootchain"
  }' \
  "https://gitlab.com/api/v4/ai_catalog/flows"
```

If this returns a 404, the API endpoint isn't active on your instance.
Use the UI fallback approach above.
