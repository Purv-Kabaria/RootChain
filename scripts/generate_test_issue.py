"""Create a test Sentry-format issue in GitLab to simulate an alert.

Usage:
    python scripts/generate_test_issue.py --language python
    python scripts/generate_test_issue.py --language node
    python scripts/generate_test_issue.py --language go
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


PYTHON_DESCRIPTION = """\
## TypeError: 'NoneType' object is not subscriptable

**Sentry Issue:** https://sentry.io/organizations/test-org/issues/9999999/

**Culprit:** `payments/processor.py in processPayment`

**Times seen:** 47
**Users affected:** 12
**Environment:** production
**First seen:** {ts}
**Last seen:** {ts}

### Stacktrace

```
Traceback (most recent call last):
  File "/app/payments/processor.py", line 142, in processPayment
    result_id = gateway_response['id']
  File "/app/payments/gateway.py", line 88, in call_gateway
    return self._session.post(url, data=payload)
  File "/app/core/session.py", line 34, in post
    return requests.post(self.base_url + path, **kwargs)
  File "/usr/local/lib/python3.11/site-packages/requests/api.py", line 73, in post
    return request('post', url, data=data, json=json, **kwargs)
TypeError: 'NoneType' object is not subscriptable
```
"""

NODE_DESCRIPTION = """\
## ReferenceError: Cannot read properties of undefined (reading 'userId')

**Sentry Issue:** https://sentry.io/organizations/test-org/issues/8888888/

**Culprit:** payments/checkout.js in processOrder

**Times seen:** 23
**Environment:** production

### Stacktrace

```
ReferenceError: Cannot read properties of undefined (reading 'userId')
    at processOrder (payments/checkout.js:89:15)
    at handleCheckout (api/routes/checkout.js:45:5)
    at Layer.handle [as handle_request] (node_modules/express/lib/router/layer.js:95:5)
    at next (node_modules/express/lib/router/route.js:144:13)
```
"""

GO_DESCRIPTION = """\
## panic: runtime error: index out of range

**Sentry Issue:** https://sentry.io/organizations/test-org/issues/7777777/

**Culprit:** payments/processor.go in processPayment

**Times seen:** 8
**Environment:** production

### Stacktrace

```
panic: runtime error: index out of range [5] with length 3

goroutine 42 [running]:
github.com/myorg/app/payments.processPayment(0xc0001a4000, 0x5)
\t/app/payments/processor.go:142 +0x1f4
github.com/myorg/app/api.handlePayment(0x14000123456)
\t/app/api/handler.go:88 +0x9c
net/http.HandlerFunc.ServeHTTP(0x14000123456, 0x1400034f780, 0x14000305b40)
\t/usr/local/go/src/net/http/server.go:2136 +0x34
```
"""

TEMPLATES = {
    "python": ("[Sentry] TypeError: 'NoneType' object is not subscriptable", PYTHON_DESCRIPTION),
    "node": ("[Sentry] ReferenceError: Cannot read properties of undefined", NODE_DESCRIPTION),
    "go": ("[Sentry] panic: runtime error: index out of range", GO_DESCRIPTION),
}


async def create_issue(
    project_path: str,
    token: str,
    gitlab_url: str,
    language: str,
) -> None:
    import httpx
    from urllib.parse import quote

    title_template, desc_template = TEMPLATES[language]
    ts = datetime.utcnow().isoformat() + "Z"
    description = desc_template.format(ts=ts)

    async with httpx.AsyncClient(
        base_url=f"{gitlab_url}/api/v4",
        headers={"PRIVATE-TOKEN": token, "Content-Type": "application/json"},
    ) as client:
        resp = await client.post(
            f"/projects/{quote(project_path, safe='')}/issues",
            json={
                "title": title_template,
                "description": description,
                "labels": "sentry-alert,Sentry",
            },
        )
        resp.raise_for_status()
        issue = resp.json()

    print(f"[OK] Created issue #{issue['iid']}: {issue['title']}")
    print(f"     URL: {issue['web_url']}")
    print()
    print("The RootChain flow should activate within ~2 minutes.")
    print("Watch: Project → Duo Agent Platform → Flows → rootchain → Logs")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a test Sentry issue in GitLab")
    parser.add_argument(
        "--language", choices=["python", "node", "go"], default="python",
        help="Stack trace language to simulate"
    )
    parser.add_argument("--project-path", default=os.getenv("ROOTCHAIN_PROJECT_PATH"))
    parser.add_argument("--token", default=os.getenv("ROOTCHAIN_GITLAB_TOKEN"))
    parser.add_argument("--gitlab-url", default=os.getenv("ROOTCHAIN_GITLAB_URL", "https://gitlab.com"))
    args = parser.parse_args()

    if not args.project_path:
        print("[ERROR] --project-path or ROOTCHAIN_PROJECT_PATH is required")
        sys.exit(1)
    if not args.token:
        print("[ERROR] --token or ROOTCHAIN_GITLAB_TOKEN is required")
        sys.exit(1)

    asyncio.run(create_issue(args.project_path, args.token, args.gitlab_url, args.language))


if __name__ == "__main__":
    main()
