"""Render a BlameChain into a Markdown comment string.

Pure function: takes BlameChain + SentryEvent, returns str. No I/O.
"""

from __future__ import annotations

from .config import Config
from .models import BlameChain, BlameEntry, SentryEvent, VulnerabilityFinding

_CONFIDENCE_EMOJI = {
    "HIGH": "🔴",
    "MEDIUM": "🟡",
    "LOW": "🟢",
}


_PIPELINE_BADGE = {
    "passed": "✅ CI passed",
    "failed": "❌ CI failed",
    "running": "🔄 CI running",
    "pending": "⏳ CI pending",
    "canceled": "⛔ CI canceled",
}

_SEVERITY_EMOJI = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🔵",
    "info": "⚪",
    "unknown": "⚫",
}


def _mr_link(entry: BlameEntry) -> str:
    if entry.history.orbit_miss:
        return "_Not in Orbit index_"
    if entry.primary_mr is None:
        return "_No MR found_"
    mr = entry.primary_mr
    age = f"{mr.days_since_merge}d" if mr.days_since_merge < 90 else f"{mr.days_since_merge // 30}mo"
    base = f"[!{mr.iid}]({mr.web_url}) · {age} ago"
    if mr.pipeline_status:
        badge = _PIPELINE_BADGE.get(mr.pipeline_status.lower(), f"⚠️ CI {mr.pipeline_status}")
        return f"{base} · {badge}"
    return base


def _intent_cell(entry: BlameEntry) -> str:
    if entry.history.orbit_miss or entry.primary_mr is None:
        return "—"
    issues = entry.primary_mr.linked_issues
    if not issues:
        # Use truncated MR title as fallback
        title = entry.primary_mr.title
        return title[:60] + "…" if len(title) > 60 else title
    first = issues[0]
    short = first.title[:50] + "…" if len(first.title) > 50 else first.title
    return f"[#{first.iid}: {short}]({first.web_url})"


def _author_cell(entry: BlameEntry) -> str:
    if entry.primary_mr is None:
        return "—"
    return f"@{entry.primary_mr.author_username}"


def _confidence_cell(entry: BlameEntry) -> str:
    emoji = _CONFIDENCE_EMOJI.get(entry.confidence_label, "")
    return f"{emoji} {entry.confidence_label}"


def _collect_mentions(chain: BlameChain, config: Config) -> list[str]:
    seen: list[str] = []

    for entry in chain.entries:
        if not config.mention_authors or entry.primary_mr is None:
            continue
        author = entry.primary_mr.author_username
        if author and author not in seen:
            seen.append(author)

        if config.mention_reviewers:
            for reviewer in entry.primary_mr.reviewers:
                if reviewer and reviewer not in seen:
                    seen.append(reviewer)

    return seen[: config.max_mention_users]


def _build_table(chain: BlameChain) -> str:
    rows = ["| # | Function | File | Last MR | Intent | Author | Confidence |"]
    rows.append("|---|----------|------|---------|--------|--------|------------|")

    for i, entry in enumerate(chain.entries, 1):
        frame = entry.frame
        file_cell = f"{frame.file_path}:{frame.line_number}"
        rows.append(
            f"| {i} | {frame.function_name} | {file_cell} "
            f"| {_mr_link(entry)} | {_intent_cell(entry)} "
            f"| {_author_cell(entry)} | {_confidence_cell(entry)} |"
        )

    return "\n".join(rows)


def _build_mermaid_chain(chain: BlameChain, event: SentryEvent) -> str:
    """Build a Mermaid flowchart showing the error → blame path."""
    lines = ["```mermaid", "flowchart LR"]
    lines.append(f'    ERR["{event.error_type}\\nerror"]')

    for i, entry in enumerate(chain.entries, 1):
        frame = entry.frame
        func_id = f"F{i}"
        mr_id = f"MR{i}"
        wi_id = f"WI{i}"

        func_label = f"{frame.function_name}:{frame.line_number}"
        lines.append(f'    {func_id}["{func_label}"]')
        lines.append(f"    ERR --> {func_id}")

        if entry.primary_mr and not entry.history.orbit_miss:
            mr = entry.primary_mr
            age = f"{mr.days_since_merge}d" if mr.days_since_merge < 90 else f"{mr.days_since_merge // 30}mo"
            mr_label = f"MR !{mr.iid}\\n@{mr.author_username} · {age}"
            lines.append(f'    {mr_id}["{mr_label}"]')
            lines.append(f"    {func_id} --> {mr_id}")

            if mr.linked_issues:
                wi = mr.linked_issues[0]
                wi_title = wi.title[:30] + "…" if len(wi.title) > 30 else wi.title
                lines.append(f'    {wi_id}[/"#{wi.iid}: {wi_title}"/]')
                lines.append(f"    {mr_id} --> {wi_id}")
        else:
            lines.append(f'    MISS{i}["orbit miss"]')
            lines.append(f"    {func_id} --> MISS{i}")

    lines.append("```")
    return "\n".join(lines)


def _build_security_section(chain: BlameChain) -> str:
    """Return a Markdown security context block if any blamed file has active findings."""
    all_findings: list[tuple[str, VulnerabilityFinding]] = []
    for entry in chain.entries:
        for finding in entry.history.security_findings:
            all_findings.append((entry.frame.file_path, finding))

    if not all_findings:
        return ""

    rows = ["| Severity | Finding | Type | File |", "|----------|---------|------|------|"]
    for file_path, f in all_findings[:5]:
        emoji = _SEVERITY_EMOJI.get(f.severity, "⚫")
        name_cell = f"[{f.name}]({f.web_url})" if f.web_url else f.name
        rows.append(f"| {emoji} {f.severity.upper()} | {name_cell} | {f.report_type.upper()} | {file_path} |")

    table = "\n".join(rows)
    return f"""
---

### ⚠️ Security Context

> The following active security findings exist in Orbit for the blamed file(s):

{table}

> Address these findings alongside the bug fix — a security-critical path may need additional review.
"""


def format_blame_comment(
    chain: BlameChain,
    event: SentryEvent,
    config: Config,
    project_path: str,
) -> str:
    """Render the full Markdown comment to post on the GitLab issue."""
    ts = chain.generated_at.strftime("%Y-%m-%d %H:%M:%S")
    error_summary = f"`{event.error_type}: {event.error_message}`" if event.error_message else f"`{event.error_type}`"

    suspect_line: str
    if chain.primary_suspect and chain.primary_suspect.primary_mr:
        mr = chain.primary_suspect.primary_mr
        suspect_line = (
            f"[MR !{mr.iid}]({mr.web_url}) by @{mr.author_username} · {mr.days_since_merge}d ago"
        )
    else:
        suspect_line = "_Could not identify a primary suspect with sufficient confidence._"

    orbit_miss_note = ""
    if chain.orbit_misses > 0:
        orbit_miss_note = (
            f"\n> ⚠️ {chain.orbit_misses} frame(s) had no Orbit data "
            "(code may be too new, not on default branch, or outside the indexed group).\n"
        )

    table = _build_table(chain)
    mermaid_chain = _build_mermaid_chain(chain, event)
    analysis_section = _build_analysis(chain, event)
    security_section = _build_security_section(chain)

    mentions = _collect_mentions(chain, config)
    loop_in = ""
    if mentions:
        loop_in = f"\n**Loop in:** {' · '.join(f'@{u}' for u in mentions)}\n"

    gitlab_url = config.gitlab_url
    disable_link = f"{gitlab_url}/{project_path}/-/settings/integrations"
    fp_link = f"{gitlab_url}/{project_path}/-/issues/new?issue[title]=RootChain+false+positive"

    return f"""## 🔗 RootChain SDLC Blame Analysis

**Analyzed:** {ts} UTC
**Error:** {error_summary}
**Frames analyzed:** {chain.frames_analyzed} (filtered from {chain.frames_total} total)
**Primary suspect:** {suspect_line}

---

### Stack Trace → SDLC Chain

{table}

<details>
<summary>Blame graph (click to expand)</summary>

{mermaid_chain}

</details>

---
{orbit_miss_note}
### Analysis

{analysis_section}
{security_section}{loop_in}
---

<sub>Generated by [RootChain]({gitlab_url}/{project_path}) · \
[Disable for this project]({disable_link}) · \
[Report false positive]({fp_link})</sub>"""


def _build_analysis(chain: BlameChain, event: SentryEvent) -> str:
    if not chain.primary_suspect or chain.primary_suspect.primary_mr is None:
        all_miss = all(e.history.orbit_miss for e in chain.entries)
        if all_miss:
            return (
                "RootChain could not find Orbit data for any stack frame. "
                "This typically means the code is very new (< 1h since merge), "
                "on a non-default branch, or outside the configured group. "
                "Enable `ROOTCHAIN_LOG_LEVEL=DEBUG` to inspect Orbit query responses."
            )
        return (
            "RootChain could not identify a primary suspect above the confidence threshold. "
            "The blame table above shows all frames with partial data. "
            "Review the frames manually or lower `ROOTCHAIN_CONFIDENCE_THRESHOLD`."
        )

    suspect = chain.primary_suspect
    mr = suspect.primary_mr
    frame = suspect.frame
    assert mr is not None

    intent = ""
    if mr.linked_issues:
        issue = mr.linked_issues[0]
        intent = (
            f"MR !{mr.iid} was linked to issue #{issue.iid} ({issue.title}). "
        )
    else:
        intent = f"MR !{mr.iid} ({mr.title}) has no linked issue. "

    suggestion = (
        f"**Suggested investigation:** Review `{frame.file_path}` around line {frame.line_number}, "
        f"specifically changes introduced in [MR !{mr.iid}]({mr.web_url}). "
        f"Check whether the `{frame.function_name}` function handles all return paths correctly "
        f"for the `{event.error_type}` scenario."
    )

    return f"{intent}{suggestion}"


def format_no_stack_trace_comment(event_title: str) -> str:
    """Comment to post when no parseable stack trace is found."""
    return (
        "## 🔗 RootChain SDLC Blame Analysis\n\n"
        f"**Issue:** {event_title}\n\n"
        "No parseable stack trace found in this issue description. "
        "Possible reasons:\n"
        "- The issue was created without a stack trace\n"
        "- The stack trace format is not supported (supported: Python, Node.js, Go, Ruby, Java)\n"
        "- If this is a minified JavaScript error: enable Sentry source maps\n\n"
        "_No SDLC analysis was performed._"
    )


def format_all_library_frames_comment(total_frames: int) -> str:
    """Comment to post when all frames are filtered as library code."""
    return (
        "## 🔗 RootChain SDLC Blame Analysis\n\n"
        f"All {total_frames} stack frame(s) were identified as library or runtime code "
        "and filtered out.\n\n"
        "Possible reasons:\n"
        "- The error originates inside a third-party library (not application code)\n"
        "- Source maps are missing (for JavaScript)\n"
        "- The stack trace shows only standard library frames\n\n"
        "If this is incorrect, set `ROOTCHAIN_INCLUDE_LIBRARY_FRAMES=true` to bypass filtering. "
        "_No SDLC analysis was performed._"
    )
