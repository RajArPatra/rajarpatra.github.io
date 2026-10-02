#!/usr/bin/env python3
"""
Export Claude Code usage stats for the site dashboard.

Privacy: reads ~/.claude/projects/**/*.jsonl, which hold full conversation
transcripts, but writes ONLY dates, integers and a model name. No message
content, file paths, project names or branch names reach activity.json.

Metric definitions are matched to the Claude Code dashboard:
  sessions   distinct sessionId values
  messages   records of type user or assistant
  tokens     input_tokens + output_tokens, summed across every usage record
             without deduplicating by message id (this is what the dashboard
             reports; deduplicating gives a visibly lower number)
  peak_hour  the hour a session most often STARTS, not the busiest hour
  model      most frequently seen message.model

Usage:  python3 tools/export_claude_activity.py
"""
import json, glob, os, datetime, collections, sys

SRC = os.path.expanduser("~/.claude/projects/**/*.jsonl")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "activity.json")
MOBY_DICK_TOKENS = 280_000  # ~210k words

def pretty_model(mid):
    parts = mid.replace("claude-", "").split("-")
    if not parts:
        return mid
    fam = parts[0].capitalize()
    nums = [p for p in parts[1:] if p.isdigit()]
    return f"{fam} {'.'.join(nums)}" if nums else fam

def main():
    days = collections.defaultdict(lambda: {"sessions": set(), "prompts": 0})
    sessions, models = set(), collections.Counter()
    starts = {}
    messages = tokens = 0

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
                ts, kind, sid = rec.get("timestamp"), rec.get("type"), rec.get("sessionId")
                if kind in ("user", "assistant"):
                    messages += 1
                msg = rec.get("message")
                if isinstance(msg, dict):
                    mdl = msg.get("model")
                    if mdl and mdl != "<synthetic>":
                        models[mdl] += 1
                    use = msg.get("usage")
                    if isinstance(use, dict):
                        tokens += use.get("input_tokens", 0) + use.get("output_tokens", 0)
                if not ts:
                    continue
                try:
                    local = datetime.datetime.fromisoformat(
                        ts.replace("Z", "+00:00")).astimezone()
                except ValueError:
                    continue
                key = local.date().isoformat()
                if sid:
                    sessions.add(sid)
                    days[key]["sessions"].add(sid)
                    if sid not in starts or local < starts[sid]:
                        starts[sid] = local
                if kind == "user":
                    days[key]["prompts"] += 1

    hours = collections.Counter(s.hour for s in starts.values())
    peak = hours.most_common(1)[0][0] if hours else 0
    top_model = models.most_common(1)[0][0] if models else ""

    out = {
        "generated": datetime.datetime.now().astimezone().date().isoformat(),
        "days": {k: [len(v["sessions"]), v["prompts"]]
                 for k, v in sorted(days.items()) if v["prompts"] or v["sessions"]},
        "totals": {
            "sessions": len(sessions),
            "messages": messages,
            "tokens": tokens,
            "active_days": sum(1 for v in days.values() if v["prompts"] or v["sessions"]),
            "peak_hour": peak,
            "model": pretty_model(top_model),
            "moby_dicks": round(tokens / MOBY_DICK_TOKENS),
        },
    }
    with open(OUT, "w") as fh:
        json.dump(out, fh, separators=(",", ":"), sort_keys=True)
        fh.write("\n")

    t = out["totals"]
    print(f"  sessions {t['sessions']}   messages {t['messages']:,}   "
          f"tokens {t['tokens']/1e6:.2f}M")
    print(f"  active days {t['active_days']}   peak hour {t['peak_hour']:02d}:00   "
          f"model {t['model']}   ~{t['moby_dicks']}x Moby-Dick")

if __name__ == "__main__":
    main()
