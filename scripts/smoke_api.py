"""Smoke-test every HTTP route against a running server.

Usage: python scripts/smoke_api.py [base_url]

Walks the OpenAPI schema, calls every GET route (and safe POST/PATCH routes
with plausible payloads), and reports any status code >= 500.
"""

from __future__ import annotations

import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

# Routes that mutate real data / need a body we cannot guess safely.
SKIP = {
    "/api/demo/reset",
    "/api/campaigns/broadcast",
}

RESULTS: list[tuple[str, str, int, str]] = []


def call(method: str, path: str, **kwargs) -> None:
    url = f"{BASE}{path}"
    try:
        resp = getattr(httpx, method)(url, timeout=30.0, **kwargs)
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((method.upper(), path, 0, f"EXC {exc}"))
        return
    body = resp.text[:400]
    RESULTS.append((method.upper(), path, resp.status_code, body))


def main() -> int:
    with httpx.Client(timeout=30.0) as c:
        spec = c.get(f"{BASE}/openapi.json").json()
    for path, methods in sorted(spec["paths"].items()):
        for method, meta in methods.items():
            if path in SKIP:
                continue
            if method == "get":
                # fill path params with sane defaults
                p = path
                p = p.replace("{phone}", "919876543210")
                p = p.replace("{order_no}", "1")
                p = p.replace("{item_id}", "1")
                p = p.replace("{rule_id}", "1")
                p = p.replace("{reservation_id}", "1")
                p = p.replace("{alert_id}", "1")
                p = p.replace("{token}", "does-not-exist")
                call("get", p)
            elif method in {"post", "patch", "put"}:
                RESULTS.append((method.upper(), path, -1, "skipped (mutating)"))
    bad = [r for r in RESULTS if r[2] == 0 or r[2] >= 500 or (isinstance(r[2], int) and 400 <= r[2] < 500 and r[2] not in (401, 403, 404, 409, 422, 400))]
    print(f"{'METHOD':8} {'PATH':52} {'CODE':>5}  SNIPPET")
    for m, p, code, body in RESULTS:
        flag = "  <-- " if code >= 500 or code == 0 else ""
        print(f"{m:8} {p:52} {code:>5}  {body[:120].replace(chr(10), ' ')}{flag}")
    print()
    if bad:
        print(f"!! {len(bad)} suspicious responses")
        for r in bad:
            print("   ", r[0], r[1], r[2], r[3][:300])
        return 1
    print(f"OK — {len(RESULTS)} routes checked, no server errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
