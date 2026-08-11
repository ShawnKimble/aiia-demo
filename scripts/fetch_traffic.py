#!/usr/bin/env python3
"""Fetch per-day visit counts from GoatCounter's authenticated API and write
data/daily.json for stats.html to consume.

Runs inside GitHub Actions (see .github/workflows/traffic.yml). The read-only
API token lives in the GOATCOUNTER_TOKEN secret and never leaves the runner.

Notes on the API (learned 2026-08-10/11):
- The PUBLIC counter endpoint (/counter/*.json) 404s on past-day ranges and
  lags; it is useless for this. Only the authenticated /api/v0 works.
- The dashboard's headline number is VISITS (sessions), not pageviews. We try
  several response fields and log which one we used so a human can verify the
  first run against the dashboard.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SITE = "https://aiia-risk.goatcounter.com"
LAUNCH = "2026-08-08"  # site went live; earlier days are hard zeros
ET = ZoneInfo("America/New_York")

TOKEN = os.environ.get("GC_TOKEN", "").strip()
if not TOKEN:
    print("ERROR: GC_TOKEN not set or empty", file=sys.stderr)
    sys.exit(1)
print(f"Token present: {len(TOKEN)} chars (value not logged)")


def api(path, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{SITE}/api/v0{path}?{q}" if q else f"{SITE}/api/v0{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:500]
        except Exception:
            pass
        print(f"API ERROR {e.code} on {path}: {body}", file=sys.stderr)
        raise


def day_visits(day_str):
    """Return (visits, debug) for one calendar day."""
    resp = api("/stats/total", start=day_str, end=day_str)
    # Try likely field names in preference order; log the raw shape so the
    # first run can be human-verified against the dashboard.
    for key in ("visits", "total_unique", "total_utc", "total"):
        if isinstance(resp, dict) and key in resp and isinstance(resp[key], int):
            return resp[key], {"day": day_str, "used": key, "raw": resp}
    return 0, {"day": day_str, "used": None, "raw": resp}


def main():
    today_et = datetime.now(ET).date()
    days = [today_et - timedelta(days=i) for i in range(6, -1, -1)]

    daily = []
    debugs = []
    for d in days:
        ds = d.isoformat()
        if ds < LAUNCH:
            n = 0
            debugs.append({"day": ds, "used": "pre-launch zero"})
        else:
            n, dbg = day_visits(ds)
            debugs.append(dbg)
        daily.append({
            "date": ds,
            "label": d.strftime("%b %-d"),
            "n": n,
            "partial": ds == today_et.isoformat(),
        })

    total_resp = api("/stats/total", start=LAUNCH, end=today_et.isoformat())
    total = None
    for key in ("visits", "total_unique", "total_utc", "total"):
        if isinstance(total_resp, dict) and isinstance(total_resp.get(key), int):
            total = total_resp[key]
            total_key = key
            break
    if total is None:
        print("ERROR: could not find a total field. Raw:", json.dumps(total_resp)[:2000], file=sys.stderr)
        sys.exit(1)

    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated_et": datetime.now(ET).strftime("%b %-d, %Y %-I:%M %p ET"),
        "tz": "America/New_York",
        "source": "GoatCounter authenticated API via GitHub Action (hourly)",
        "field_used": total_key,
        "total": total,
        "daily": daily,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/daily.json", "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")

    # ---- log for human verification (first run especially) ----
    print("Wrote data/daily.json")
    print(json.dumps(out, indent=2))
    print("\n--- field-selection debug (compare against dashboard!) ---")
    print(json.dumps(debugs, indent=2, default=str)[:6000])


if __name__ == "__main__":
    main()
