#!/usr/bin/env python3
"""Fetch per-day VISIT counts from GoatCounter's authenticated API and write
data/daily.json for stats.html to consume.

Runs inside GitHub Actions (.github/workflows/traffic.yml); read-only token in
the GOATCOUNTER_TOKEN secret.

API notes (learned the hard way, 2026-08-11):
- /api/v0/stats/total counts PAGEVIEWS; the dashboard headline is VISITS.
  Visits = sum of per-path "count" from /api/v0/stats/hits (verified: dashboard
  72 = 58+6+3+2+1+1+1 across paths).
- start/end are date-time values "rounded to the hour", not bare dates
  (bare dates 404). We probe a few accepted formats and use the first that
  works, logging the choice.
- The site dashboard displays days in America/New_York; we query ET day
  boundaries so our numbers match what the dashboard shows.
"""
import json
import os
import sys
import urllib.request
import urllib.error
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


def api_raw(path, query):
    url = f"{SITE}/api/v0{path}?{query}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def fmt_candidates(dt):
    """Different renderings of a datetime the API might accept."""
    return [
        ("rfc3339-z", dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ("space-utc", dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
        ("rfc3339-offset", dt.strftime("%Y-%m-%dT%H:%M:%S%z")),
    ]


CHOSEN_FMT = None


def hits_for_range(start_dt, end_dt):
    """Return (visits_sum, per_path_debug) for a datetime range, probing
    accepted time formats on first use."""
    global CHOSEN_FMT
    from urllib.parse import quote
    fmts = [CHOSEN_FMT] if CHOSEN_FMT else [f[0] for f in fmt_candidates(start_dt)]
    last_err = None
    for name in fmts:
        s = dict(fmt_candidates(start_dt))[name]
        e = dict(fmt_candidates(end_dt))[name]
        q = f"start={quote(s)}&end={quote(e)}&limit=100"
        try:
            resp = api_raw("/stats/hits", q)
            if CHOSEN_FMT is None:
                CHOSEN_FMT = name
                print(f"Time format accepted: {name}")
            hits = resp.get("hits", [])
            total = sum(h.get("count", 0) for h in hits)
            if resp.get("more"):
                print("WARNING: hits paginated (more=true); sum may be low", file=sys.stderr)
            dbg = [{"path": h.get("path"), "count": h.get("count")} for h in hits[:15]]
            return total, dbg
        except urllib.error.HTTPError as ex:
            body = ""
            try:
                body = ex.read().decode()[:300]
            except Exception:
                pass
            last_err = f"{name}: HTTP {ex.code} {body}"
            print(f"format {name} rejected -> {last_err}", file=sys.stderr)
    raise RuntimeError(f"All time formats rejected. Last: {last_err}")


def et_day_bounds(d):
    start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=ET)
    end = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=ET)
    return start, end


def main():
    now_et = datetime.now(ET)
    today = now_et.date()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]

    daily = []
    for d in days:
        ds = d.isoformat()
        if ds < LAUNCH:
            n, dbg = 0, "pre-launch"
        else:
            s, e = et_day_bounds(d)
            n, dbg = hits_for_range(s, e)
        daily.append({
            "date": ds,
            "label": d.strftime("%b %-d"),
            "n": n,
            "partial": ds == today.isoformat(),
        })
        print(f"{ds}: {n} visits  {dbg}")

    launch_start = datetime(2026, 8, 8, 0, 0, 0, tzinfo=ET)
    total, tdbg = hits_for_range(launch_start, now_et)
    print(f"all-time total: {total} visits  {tdbg}")

    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated_et": now_et.strftime("%b %-d, %Y %-I:%M %p ET"),
        "tz": "America/New_York",
        "source": "GoatCounter authenticated API (visits via /stats/hits) — GitHub Action, hourly",
        "total": total,
        "daily": daily,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/daily.json", "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    print("Wrote data/daily.json")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
