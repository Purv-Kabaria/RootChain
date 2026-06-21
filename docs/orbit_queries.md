# Orbit Query Reference

All Orbit queries used by RootChain are documented here with annotated examples.
Every query uses parameterized syntax — never string interpolation.

---

## Endpoint

```
POST https://gitlab.com/api/v4/orbit/query
Content-Type: application/json
PRIVATE-TOKEN: {ROOTCHAIN_GITLAB_TOKEN}
```

Request body:
```json
{
  "query": "MATCH ... RETURN ...",
  "parameters": { "key": "value" },
  "timeout": 30000
}
```

Response on success:
```json
{
  "data": {
    "nodes": [
      { "id": "mr:342", "type": "MergeRequest", "properties": { ... } }
    ],
    "edges": [
      { "source": "mr:342", "target": "wi:89", "type": "CLOSES" }
    ]
  },
  "meta": { "query_time_ms": 142 }
}
```

Response on error:
```json
{ "error": "Syntax error at position 14" }
```

Always check for the `error` key before accessing `data`.

---

## Query 1 — Primary: Definition → MergeRequest

Finds MRs that last modified a specific function symbol.

```cypher
MATCH (d:Definition {name: $function_name})
      -[:DEFINED_IN]->(f:File {path: $file_path})
      <-[:MODIFIES_FILE]-(mr:MergeRequest)
WHERE mr.merged_at IS NOT NULL
  AND mr.project_full_path STARTS WITH $group_path
RETURN
  mr.iid          AS iid,
  mr.title        AS title,
  mr.description  AS description,
  mr.web_url      AS url,
  mr.merged_at    AS merged_at,
  mr.author_username AS author
ORDER BY mr.merged_at DESC
LIMIT 3
```

**Parameters:**
- `$function_name` — exact function name from the stack frame (e.g., `"processPayment"`)
- `$file_path` — file path as it appears in the stack trace (e.g., `"payments/processor.py"`)
- `$group_path` — top-level group path (e.g., `"myorg"`)

**Notes:**
- `merged_at IS NOT NULL` excludes open MRs (only analyze merged changes)
- `STARTS WITH $group_path` scopes to your organization's repos
- Returns at most 3 MRs, newest first
- If this returns 0 results, try Query 2 (file-level fallback)

---

## Query 2 — Fallback: File → MergeRequest

Used when the primary query returns 0 results. Skips the `Definition` node hop
and queries at the file level. Results carry less confidence (`fallback_used=True`,
confidence multiplied by 0.7).

```cypher
MATCH (f:File {path: $file_path})
      <-[:MODIFIES_FILE]-(mr:MergeRequest)
WHERE mr.merged_at IS NOT NULL
  AND mr.project_full_path STARTS WITH $group_path
RETURN
  mr.iid          AS iid,
  mr.title        AS title,
  mr.description  AS description,
  mr.web_url      AS url,
  mr.merged_at    AS merged_at,
  mr.author_username AS author
ORDER BY mr.merged_at DESC
LIMIT 3
```

**When this triggers:** Definition not indexed (function may be unnamed, new, or in an unsupported language for Orbit's code-intel).

---

## Query 3 — Linked Work Items

Finds GitLab issues linked to a specific MR via closing patterns or mentions.

```cypher
MATCH (mr:MergeRequest {iid: $mr_iid, project_full_path: $project_path})
      -[:CLOSES|MENTIONED_IN]->(wi:WorkItem)
RETURN
  wi.iid    AS iid,
  wi.title  AS title,
  wi.state  AS state,
  wi.web_url AS url
```

**Parameters:**
- `$mr_iid` — integer MR IID (cast from string if needed)
- `$project_path` — full project path (e.g., `"myorg/myapp"`)

**Returns:** Work items (issues) that the MR closes or mentions. These provide the "intent" column in the output table.

---

## Query 4 — Reviewers

Finds users who reviewed a specific MR.

```cypher
MATCH (u:User)-[:REVIEWED]->(mr:MergeRequest {iid: $mr_iid, project_full_path: $project_path})
RETURN u.username AS username
```

**Returns:** Usernames of MR reviewers. Used for the "Loop in:" section when `ROOTCHAIN_MENTION_REVIEWERS=true`.

---

## Query 5 — Caller Count (Hot-Path Detection)

Counts how many other functions call the target function. Higher caller count = higher blast radius.

```cypher
MATCH (caller:Definition)-[:CALLS]->(d:Definition {name: $function_name})
RETURN count(caller) AS caller_count
```

**Returns:** Integer count. If unavailable (e.g., Orbit hasn't indexed call graphs for this language), defaults to 0, which results in a `blast` score of 0.0 (no blast-radius contribution).

---

## Checking the Live Schema

The node types, property names, and edge types above are based on GitLab Orbit's
standard schema. Verify the live schema for your instance:

```bash
curl -s \
  --header "PRIVATE-TOKEN: $ROOTCHAIN_GITLAB_TOKEN" \
  "https://gitlab.com/api/v4/orbit/schema" \
  | jq '.domains[].node_types[] | {name, properties: [.properties[].name]}'
```

---

## Handling Response Differences

Orbit uses ClickHouse as its backing store. A few quirks:

| Field | Expected type | ClickHouse may return | Fix |
|-------|--------------|----------------------|-----|
| `iid` | `int` | `string` | Always `int(props.get("iid", 0))` |
| `merged_at` | `datetime` | `"2024-01-11T14:23:00Z"` | `datetime.fromisoformat(v.replace("Z", "+00:00"))` |
| `caller_count` | `int` | `string` or `float` | `int(props.get("caller_count", 0))` |

---

## Troubleshooting Queries

### No results from primary query

1. Check that `$file_path` matches what's indexed. Orbit may strip leading `/app/`:
   ```bash
   # Test path normalization
   curl -s -X POST "$GITLAB_URL/api/v4/orbit/query" \
     -H "PRIVATE-TOKEN: $ROOTCHAIN_GITLAB_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"query": "MATCH (f:File) WHERE f.path CONTAINS $path RETURN f.path LIMIT 5", "parameters": {"path": "processor.py"}}'
   ```

2. Orbit indexes only the **default branch**. If the code is on a feature branch, no results will appear until it's merged.

3. For functions with very generic names (e.g., `get`, `post`, `run`), the `Definition` hop may return too many candidates. The file-path filter narrows it down.

### Rate limiting

Orbit queries are subject to rate limits. If you see HTTP 429, the retry logic
handles it automatically using the `Retry-After` header. For sustained 429s,
consider reducing `ROOTCHAIN_MAX_FRAMES` or increasing `ROOTCHAIN_ORBIT_TIMEOUT_SECONDS`.
