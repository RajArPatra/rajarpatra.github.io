#!/usr/bin/env python3
"""
Export Claude Code session activity as a per-day count file for the site heatmap.

Privacy: this reads ~/.claude/projects/**/*.jsonl, which contain full conversation
transcripts, but writes ONLY a date and two integers per active day. No message
content, no file paths, no project or branch names ever reach activity.json.

Usage:  python3 tools/export_claude_activity.py
"""
import json, glob, os, datetime, collections, sys

SRC = os.path.expanduser("~/.claude/projects/**/*.jsonl")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "activity.json")

def main():
    days = collections.defaultdict(lambda: {"sessions": set(), "prompts": 0})
    all_sessions = set()
    files = glob.glob(SRC, recursive=True)
    if not files:
        sys.exit("No session files found under ~/.claude/projects")

    for fp in files:
        with open(fp, errors="ignore") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                ts = rec.get("timestamp")
                if not ts:
                    continue
                try:
                    local = datetime.datetime.fromisoformat(
                        ts.replace("Z", "+00:00")).astimezone()
                except ValueError:
                    continue
                key = local.date().isoformat()
                sid = rec.get("sessionId")
                if sid:
                    days[key]["sessions"].add(sid)
                    all_sessions.add(sid)
                if rec.get("type") == "user":
                    days[key]["prompts"] += 1

    # counts only, sorted for a stable diff
    out = {
        "generated": datetime.datetime.now().astimezone().date().isoformat(),
        "days": {k: [len(v["sessions"]), v["prompts"]]
                 for k, v in sorted(days.items()) if v["prompts"] or v["sessions"]},
    }
    # a session spanning midnight lands on two days, so total it globally
    out["totals"] = {"sessions": len(all_sessions),
                     "prompts": sum(v["prompts"] for v in days.values()),
                     "active_days": len(out["days"])}
    with open(OUT, "w") as fh:
        json.dump(out, fh, separators=(",", ":"), sort_keys=True)
        fh.write("\n")

    t = out["totals"]
    print(f"{t['active_days']} active days, {t['sessions']} sessions, "
          f"{t['prompts']} prompts -> {os.path.normpath(OUT)}")

if __name__ == "__main__":
    main()
