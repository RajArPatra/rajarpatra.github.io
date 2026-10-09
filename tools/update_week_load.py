#!/usr/bin/env python3
"""Refresh week-load/data.json from the local calendar and publish it.

Prints exactly one status word on the last line, matching update_activity.sh:
    NO_CHANGE  data identical, nothing committed
    PUSHED     new data committed and pushed
    DIVERGED   remote history moved in a way we will not resolve unattended
    FAILED     something else went wrong

Privacy contract: event titles are read into memory so that duplicate entries
can be collapsed, and are NEVER written to disk. data.json holds dates and
integers only. Do not add fields that carry titles, locations or attendees.
"""

import collections
import datetime as dt
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = REPO / "week-load" / "data.json"
EXPORTER = REPO / "tools" / "export_calendar.js"

HOLIDAY = {"Holidays in India", "India Holidays", "United States holidays"}
HISTORY_WEEKS = 9            # weeks of past shown, counting back from this Monday
MAX_AHEAD_WEEKS = 16         # never run further ahead than this, however far out events sit
W0, W1 = 420, 1380           # a day's load is measured inside 07:00-23:00
FREE = 2                     # EKEventAvailability.free, an informational hold
CANCELLED = 3                # EKEventStatus.canceled
MIN_CLASH_MIN = 5            # shorter overlaps are rounding, not a clash


def fail(msg):
    print(msg)
    print("FAILED")
    sys.exit(1)


def git(*args, check=True):
    r = subprocess.run(["git", "-C", str(REPO), *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        fail("git " + " ".join(args) + " failed: " + (r.stderr.strip() or r.stdout.strip()))
    return r


def load_events(lo, hi):
    r = subprocess.run(
        ["osascript", "-l", "JavaScript", str(EXPORTER), lo.isoformat(), hi.isoformat()],
        capture_output=True, text=True)
    # JXA's console.log writes to stderr; fall back to stdout if that ever changes.
    raw = (r.stderr or "").strip() or (r.stdout or "").strip()
    if r.returncode != 0 and not raw:
        fail("calendar export failed: " + (r.stderr or r.stdout or "no output").strip())
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        fail("calendar export did not return JSON: " + raw[:300])
    if isinstance(rows, dict) and rows.get("error") == "NO_CALENDAR_ACCESS":
        fail("Calendar access was refused. Enable System Settings > Privacy & Security "
             "> Calendars for the app running this task.")
    return rows


def build(rows, lo, today):
    P = dt.datetime.fromisoformat

    # Collapse entries that are the same event recorded twice. Title is used
    # here and then dropped; nothing below this line keeps it.
    seen, ev = set(), []
    considered = 0
    for r in rows:
        if r["cal"] in HOLIDAY or r["st"] == CANCELLED:
            continue
        considered += 1
        key = (r["t"].strip().lower(), r["s"], r["e"], r["ad"])
        if key in seen:
            continue
        seen.add(key)
        ev.append({"a": P(r["s"]), "b": P(r["e"]),
                   "ad": bool(r["ad"]), "free": r["av"] == FREE})
    dupes = considered - len(ev)

    timed = sorted((e for e in ev if not e["ad"]), key=lambda e: (e["a"], e["b"]))
    allday = [e for e in ev if e["ad"]]

    # Clashes: maximal clusters of events that really overlap.
    busy = [e for e in timed if not e["free"]]
    adj = collections.defaultdict(set)
    for i in range(len(busy)):
        for j in range(i + 1, len(busy)):
            if busy[j]["a"] >= busy[i]["b"]:
                break
            overlap = (min(busy[i]["b"], busy[j]["b"]) - busy[j]["a"]).total_seconds() / 60
            if overlap > MIN_CLASH_MIN:
                adj[i].add(j)
                adj[j].add(i)
    day_clash = collections.defaultdict(lambda: [0, 0])
    placed = set()
    for i in range(len(busy)):
        if i in placed or not adj[i]:
            continue
        stack, grp = [i], []
        while stack:
            k = stack.pop()
            if k in placed:
                continue
            placed.add(k)
            grp.append(k)
            stack.extend(adj[k] - placed)
        d = min(busy[g]["a"] for g in grp).date()
        day_clash[d][0] += 1
        day_clash[d][1] += len(grp)

    # Daily load, with overlapping events merged so a double-booked hour counts once.
    iv = collections.defaultdict(list)
    n_timed = collections.Counter()
    n_allday = collections.Counter()
    for e in timed:
        n_timed[e["a"].date()] += 1
        cur = e["a"]
        while cur < e["b"]:
            d = cur.date()
            eod = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0, 0))
            seg = min(e["b"], eod)
            s_m = cur.hour * 60 + cur.minute
            e_m = 1440 if seg == eod else seg.hour * 60 + seg.minute
            if e_m > s_m:
                iv[d].append((s_m, e_m))
            cur = seg
    for e in allday:
        d, last = e["a"].date(), min(e["b"].date(), e["a"].date() + dt.timedelta(days=30))
        while d <= last:
            n_allday[d] += 1
            d += dt.timedelta(days=1)

    def merge(spans):
        out = []
        for s, e in sorted(spans):
            if out and s <= out[-1][1]:
                out[-1][1] = max(out[-1][1], e)
            else:
                out.append([s, e])
        return out

    hi_day = max([*iv, *n_timed, *n_allday], default=today) 
    hi_day = max(hi_day, today)
    days, d = {}, lo
    while d <= hi_day:
        merged = merge(iv.get(d, []))
        clipped = [(max(s, W0), min(e, W1)) for s, e in merged]
        mins = sum(e - s for s, e in clipped if e > s)
        c = day_clash.get(d, [0, 0])
        days[d.isoformat()] = [round(mins / 60, 1), n_timed.get(d, 0),
                               len(merged), n_allday.get(d, 0), c[0], c[1]]
        d += dt.timedelta(days=1)

    has = lambda r: r[0] > 0 or r[1] > 0 or r[3] > 0

    wk = collections.defaultdict(list)
    for k, v in days.items():
        dd = dt.date.fromisoformat(k)
        wk[dd - dt.timedelta(days=dd.weekday())].append(v)
    weeks = [{"w": m.isoformat(),
              "h": round(sum(r[0] for r in rs), 1), "n": sum(r[1] for r in rs),
              "b": sum(r[2] for r in rs), "a": sum(r[3] for r in rs),
              "c": sum(r[4] for r in rs), "d": sum(1 for r in rs if has(r))}
             for m, rs in sorted(wk.items())]

    active = [w for w in weeks if w["n"] or w["a"]]
    if not active:
        fail("no calendar events in the window; refusing to publish an empty page")

    # Anchor the window on today rather than on where the data happens to start:
    # a fixed run of history, then everything scheduled ahead plus one empty week.
    # Counting back from today keeps a thinly used earlier month from reading as
    # free time, and the window rolls forward on its own as the term moves.
    this_mon = today - dt.timedelta(days=today.weekday())
    first = (this_mon - dt.timedelta(weeks=HISTORY_WEEKS)).isoformat()
    cut = min(dt.date.fromisoformat(active[-1]["w"]) + dt.timedelta(days=7),
              this_mon + dt.timedelta(weeks=MAX_AHEAD_WEEKS)).isoformat()
    weeks = [w for w in weeks if first <= w["w"] <= cut]
    if not weeks:
        fail("the window came out empty; refusing to publish")

    start = dt.date.fromisoformat(weeks[0]["w"])
    end = dt.date.fromisoformat(weeks[-1]["w"]) + dt.timedelta(days=6)
    days = {k: v for k, v in days.items() if start <= dt.date.fromisoformat(k) <= end}

    active = [w for w in weeks if w["n"] or w["a"]]
    rank = sorted(active, key=lambda w: -w["h"])
    this_mon = this_mon.isoformat()
    this_week = next((w for w in weeks if w["w"] == this_mon), weeks[-1])

    stats = {
        "today": today.isoformat(),
        "from": start.isoformat(),
        "to": end.isoformat(),
        "thisWeek": this_week,
        "curRank": next((i + 1 for i, w in enumerate(rank) if w["w"] == this_mon), 0),
        "nActiveWeeks": len(active),
        "peak": rank[0],
        "totalEvents": sum(w["n"] for w in weeks),
        "totalClashes": sum(w["c"] for w in weeks),
        "clashDays": sum(1 for v in days.values() if v[4]),
        "lastEvent": max((k for k, v in days.items() if has(v)), default=today.isoformat()),
        "dupesRemoved": dupes,
    }
    return {"days": days, "weeks": weeks, "stats": stats}


def main():
    today = dt.date.today()
    lo = today - dt.timedelta(days=today.weekday()) - dt.timedelta(weeks=HISTORY_WEEKS + 2)
    hi = today + dt.timedelta(weeks=26)

    # Refuse to run on top of unrelated uncommitted work.
    dirty = git("diff", "--quiet", "--", ":!week-load/data.json", check=False).returncode
    staged = git("diff", "--cached", "--quiet", check=False).returncode
    if dirty != 0 or staged != 0:
        print("Working tree has changes other than week-load/data.json; skipping.")
        print("DIVERGED")
        sys.exit(2)

    if git("fetch", "-q", "origin", "main", check=False).returncode != 0:
        fail("fetch failed")
    if git("merge", "--ff-only", "origin/main", check=False).returncode != 0:
        print("Local branch cannot fast-forward to origin/main.")
        print("DIVERGED")
        sys.exit(2)

    payload = build(load_events(lo, hi), lo, today)

    previous = DATA.read_text() if DATA.exists() else None
    # "today" moves every run; compare everything else so a quiet day is NO_CHANGE.
    def comparable(txt):
        if txt is None:
            return None
        o = json.loads(txt)
        o.get("stats", {}).pop("today", None)
        return json.dumps(o, sort_keys=True)

    nxt = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    if previous is not None and comparable(previous) == comparable(nxt):
        print("NO_CHANGE")
        return

    DATA.write_text(nxt)

    s = payload["stats"]
    print("weeks {}  events {}  clashes {} over {} days  window {} to {}".format(
        len(payload["weeks"]), s["totalEvents"], s["totalClashes"],
        s["clashDays"], s["from"], s["to"]))

    git("add", str(DATA.relative_to(REPO)))
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        print("NO_CHANGE")
        return
    git("commit", "-q", "-m", "Update week load calendar data")
    if git("push", "-q", "origin", "main", check=False).returncode != 0:
        print("push rejected")
        print("DIVERGED")
        sys.exit(2)
    print("PUSHED")


if __name__ == "__main__":
    main()
