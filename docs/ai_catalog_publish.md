# Publishing to the GitLab AI Catalog

The hackathon requires at least one flow published to the GitLab AI Catalog.
This document covers the prerequisites, the publish steps, and how to update
a published flow.

---

## Prerequisites

Before publishing:

- [ ] The project is **public** (AI Catalog entries must be publicly accessible)
- [ ] `LICENSE` file is present (MIT recommended)
- [ ] `.gitlab/duo-flows/rootchain.yml` is on the default branch
- [ ] `.gitlab/skills/rootchain/SKILL.md` is on the default branch
- [ ] The flow has been tested end-to-end at least once
- [ ] GitLab Duo is enabled for the project

---

## Method 1 — GitLab UI (Recommended)

1. Navigate to your project in GitLab
2. Go to **Duo Agent Platform → Flows**
3. Find `rootchain` in the list
4. Click **Publish to AI Catalog**
5. Fill in the catalog metadata:

| Field | Value |
|-------|-------|
| **Display name** | RootChain |
| **Tagline** | Trace Sentry production errors to their SDLC origin via GitLab Orbit |
| **Category** | DevSecOps / Incident Response |
| **Tags** | `orbit`, `sentry`, `incident-response`, `blame-chain`, `sdlc` |
| **Version** | `0.1.0` |

6. Click **Submit for Review**
7. GitLab's catalog team reviews within 1–3 business days

---

## Method 2 — API

```bash
curl --request POST \
  --header "PRIVATE-TOKEN: $ROOTCHAIN_GITLAB_TOKEN" \
  --header "Content-Type: application/json" \
  --data '{
    "flow_name": "rootchain",
    "display_name": "RootChain",
    "description": "Automatically traces production Sentry errors to their SDLC blame chain via GitLab Orbit. When Sentry creates a GitLab issue, RootChain queries the Orbit knowledge graph to find which MRs last modified each stack frame, what work items motivated those changes, and who the relevant authors and reviewers are. Posts a confidence-ranked analysis comment within 2 minutes.",
    "tags": ["orbit", "sentry", "incident-response", "blame-chain", "sdlc"],
    "category": "incident_response",
    "version": "0.1.0",
    "source_url": "https://gitlab.com/YOUR_USERNAME/rootchain",
    "documentation_url": "https://gitlab.com/YOUR_USERNAME/rootchain/-/blob/main/README.md"
  }' \
  "$GITLAB_URL/api/v4/ai_catalog/flows"
```

---

## Catalog Listing Copy

Use this copy for the catalog description:

**Short description (≤ 160 chars):**
> Trace production Sentry errors to their SDLC origin via GitLab Orbit. Automated blame chain in < 2 minutes.

**Full description:**

> RootChain is a GitLab Duo Agent Platform flow that automatically traces production errors to their SDLC origin.
>
> When Sentry creates a GitLab issue for a production alert, RootChain:
> 1. Parses the stack trace (Python, Node.js, Go, Ruby, Java supported)
> 2. Queries GitLab Orbit to find which MRs last modified each stack frame
> 3. Traces MRs back to their motivating work items (issues)
> 4. Scores each frame by confidence (recency × depth × blast radius)
> 5. Posts a structured analysis comment with the primary suspect and suggested investigation path
>
> **Result:** On-call engineers open the GitLab issue to find context already waiting for them — the causal MR, the intent behind it, who changed it, who reviewed it, and where to look.
>
> **Setup:** Requires GitLab Orbit Remote (Premium/Ultimate), Sentry integration, and a GitLab PAT with `api` scope.

---

## Updating a Published Flow

After making changes to `rootchain.yml` or `SKILL.md`:

1. Merge your changes to the default branch
2. Bump the `version` field in `.gitlab/duo-flows/rootchain.yml`
3. Re-publish via the UI or API (the catalog supports versioning)

Consumers who have installed RootChain will see an "Update available" notification
in their Duo Agent Platform → Flows view.

---

## Catalog Checklist (Hackathon Submission)

- [ ] Flow published to AI Catalog
- [ ] Repository is public
- [ ] MIT license in place
- [ ] End-to-end demo recorded (link to video in catalog description)
- [ ] README includes setup instructions, architecture diagram, and example output
- [ ] At least one test issue demonstrating the comment format
