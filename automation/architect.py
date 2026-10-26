"""Automation architect: checks Yana's live routines against automation/registry.json.

Reads a snapshot of the live routines (the JSON that list_triggers returns, one page
or a list of pages) and writes a short markdown report. It never calls an API and
never changes a routine; changes stay a human decision.

Checks:
- Registry vs live: every live routine exists and is enabled, superseded ones are
  off, nothing enabled runs without being registered.
- Drift: the live prompt still matches the baseline in automation/prompts/<key>.md.
- Session load: routines that share one persistent session, fires per day and the
  smallest gap between two fires (a turn that is still running makes the next wait).
- Ownership: each write surface has one live writer.
- Health: failed last runs, routines that stopped firing, fresh-session routines
  with no connectors, timezones that differ from the registry.

Usage:
  python3 automation/architect.py <snapshot.json> [--out report.md] [--now ISO]
  python3 automation/architect.py <snapshot.json> --baseline   # store live prompts as the baseline
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "registry.json"
PROMPTS = ROOT / "prompts"
RED, AMBER, INFO = "RED", "AMBER", "INFO"
SEVERITY_ORDER = {RED: 0, AMBER: 1, INFO: 2}
STALE_AFTER = timedelta(days=2)
MAX_FIRES_PER_SESSION_DAY = 12


# ---------- cron ----------

def _field(spec: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/")
            step = int(step_s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-"))
        else:
            a = b = int(part)
            if step > 1:
                b = hi
        out.update(range(a, b + 1, step))
    return out


def parse_cron(expr: str, default_tz: str) -> dict:
    """Parse '[CRON_TZ=<tz> ]m h dom mon dow' into sets of allowed values."""
    tz = default_tz if not expr.startswith("CRON_TZ=") else expr.split()[0].split("=", 1)[1]
    fields = expr.split()[1:] if expr.startswith("CRON_TZ=") else expr.split()
    m, h, dom, mon, dow = fields
    dows = {d % 7 for d in _field(dow, 0, 7)}
    return {
        "tz": tz,
        "minute": _field(m, 0, 59),
        "hour": _field(h, 0, 23),
        "dom": _field(dom, 1, 31),
        "month": _field(mon, 1, 12),
        "dow": dows,
        "dom_any": dom == "*",
        "dow_any": dow == "*",
    }


def _day_matches(c: dict, d: date) -> bool:
    if d.month not in c["month"]:
        return False
    dom_ok = d.day in c["dom"]
    dow_ok = (d.weekday() + 1) % 7 in c["dow"]
    if c["dom_any"] or c["dow_any"]:
        return dom_ok and dow_ok
    return dom_ok or dow_ok  # cron: both restricted means either may match


def fire_times(expr: str, default_tz: str, start: datetime, days: int = 7) -> list[datetime]:
    """Every fire between start and start + days, as UTC datetimes, sorted."""
    c = parse_cron(expr, default_tz)
    tz = ZoneInfo(c["tz"])
    local_start = start.astimezone(tz)
    out = []
    for i in range(days + 1):
        d = local_start.date() + timedelta(days=i)
        if not _day_matches(c, d):
            continue
        for h in sorted(c["hour"]):
            for m in sorted(c["minute"]):
                t = datetime(d.year, d.month, d.day, h, m, tzinfo=tz).astimezone(timezone.utc)
                if start <= t < start + timedelta(days=days):
                    out.append(t)
    return sorted(out)


# ---------- snapshot ----------

def load_snapshot(path: Path) -> list[dict]:
    raw = json.loads(path.read_text())
    pages = raw if isinstance(raw, list) else [raw]
    triggers = []
    for page in pages:
        if isinstance(page, dict) and "data" in page:
            triggers.extend(page["data"])
        elif isinstance(page, dict) and "id" in page:
            triggers.append(page)
    return triggers


def prompt_of(trigger: dict) -> str:
    return (trigger.get("derived_state") or {}).get("prompt") or trigger.get("prompt") or ""


def sha(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()[:12]


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------- checks ----------

def audit(registry: dict, triggers: list[dict], now: datetime, prompts_dir: Path = PROMPTS) -> dict:
    findings: list[tuple[str, str, str]] = []  # (severity, routine, message)
    by_id = {t["id"]: t for t in triggers}
    tz_default = registry.get("timezone", "Europe/Madrid")
    routines = registry["routines"]
    registered = {r["trigger_id"] for r in routines if r.get("trigger_id")}
    superseded = {s["trigger_id"]: s for s in registry.get("superseded", [])}

    # Registry vs live
    for r in routines:
        tid = r.get("trigger_id")
        if r["status"] == "live":
            t = by_id.get(tid)
            if not t:
                findings.append((RED, r["key"], f"registered as live but routine {tid} was not found"))
            elif not t.get("enabled"):
                findings.append((RED, r["key"], "registered as live but the routine is off"))
        elif r["status"] == "unscheduled":
            findings.append((INFO, r["key"], "built but no routine runs it. " + r.get("note", "")))
        elif r["status"] == "proposed":
            findings.append((INFO, r["key"], "proposed, not created yet"))

    for tid, s in superseded.items():
        t = by_id.get(tid)
        if t and t.get("enabled"):
            findings.append((RED, s["name"], f"superseded by {s['replaced_by']} but still on, so both run"))
        elif t and not t["name"].lower().startswith("[superseded]"):
            findings.append((INFO, s["name"], "off but not labelled; rename to \"[superseded] ...\" so the list reads clearly"))

    for t in triggers:
        if t.get("enabled") and t["id"] not in registered and t["id"] not in superseded:
            findings.append((AMBER, t["name"], f"on but not in the registry ({t['id']})"))

    # Drift against the stored baseline prompt
    for r in routines:
        t = by_id.get(r.get("trigger_id"))
        if not t:
            continue
        base = prompts_dir / f"{r['key']}.md"
        if not base.exists():
            findings.append((INFO, r["key"], "no baseline prompt stored yet (run with --baseline)"))
        elif sha(base.read_text()) != sha(prompt_of(t)):
            findings.append((AMBER, r["key"], f"live prompt differs from automation/prompts/{base.name}; "
                                              "update the repo copy or the routine so they match"))

    # Health per enabled routine
    for t in triggers:
        if not t.get("enabled"):
            continue
        name = t["name"]
        last = t.get("last_run") or {}
        status = last.get("status", "")
        if status and status != "ROUTINE_RUN_STATUS_SUCCEEDED":
            findings.append((RED, name, f"last run {status.replace('ROUTINE_RUN_STATUS_', '').lower()}"
                                        f" ({last.get('failure_reason', '')})"))
        expr = t.get("cron_expression")
        last_fired = _parse_ts(t.get("last_fired_at"))
        created = _parse_ts(t.get("created_at"))
        if expr:
            expected = fire_times(expr, tz_default, now - STALE_AFTER, days=2)
            anchor = last_fired or created
            if expected and anchor and anchor < expected[0]:
                findings.append((AMBER, name, f"should have fired {len(expected)} times in the last 2 days, "
                                              f"last fired {t.get('last_fired_at') or 'never'}"))
            tz = parse_cron(expr, tz_default)["tz"]
            if tz != tz_default:
                findings.append((INFO, name, f"schedule in {tz}, registry uses {tz_default} (same clock today, "
                                             "but one zone keeps the plan readable)"))
        fresh = not t.get("persistent_session_id")
        if fresh and not t.get("mcp_connections"):
            findings.append((AMBER, name, "starts a fresh session each time but has no connectors attached"))

    # Session load: several routines in one persistent session queue behind each other
    sessions: dict[str, list[dict]] = defaultdict(list)
    for t in triggers:
        if t.get("enabled") and t.get("persistent_session_id") and t.get("cron_expression"):
            sessions[t["persistent_session_id"]].append(t)
    min_gap = timedelta(minutes=registry.get("min_gap_minutes_same_session", 30))
    load = []
    for sid, ts in sessions.items():
        fires = sorted((ft, t["name"]) for t in ts for ft in fire_times(t["cron_expression"], tz_default, now))
        per_day = defaultdict(int)
        for ft, _ in fires:
            per_day[ft.astimezone(ZoneInfo(tz_default)).date()] += 1
        busiest = max(per_day.values(), default=0)
        close = [(a, b) for a, b in zip(fires, fires[1:]) if b[0] - a[0] < min_gap and a[1] != b[1]]
        smallest = min((b[0] - a[0] for a, b in zip(fires, fires[1:])), default=None)
        load.append({"session": sid, "routines": sorted(t["name"] for t in ts), "busiest_day": busiest,
                     "smallest_gap_min": int(smallest.total_seconds() // 60) if smallest else None})
        if len(ts) > 1:
            findings.append((AMBER, sid, f"{len(ts)} routines share one conversation; its context grows "
                                         "every run and old instructions stay in it"))
        if busiest > MAX_FIRES_PER_SESSION_DAY:
            findings.append((AMBER, sid, f"{busiest} runs on its busiest day in one conversation"))
        seen = set()
        for a, b in close:
            pair = (a[1], b[1])
            if pair in seen:
                continue
            seen.add(pair)
            gap = int((b[0] - a[0]).total_seconds() // 60)
            local = a[0].astimezone(ZoneInfo(tz_default)).strftime("%H:%M")
            findings.append((RED, sid, f"\"{b[1]}\" fires {gap} min after \"{a[1]}\" ({local} Madrid) in the "
                                       "same conversation, so it waits for that run to finish"))

    # Ownership: one live writer per surface
    writers: dict[str, list[str]] = defaultdict(list)
    for r in routines:
        for s in r.get("writes", []):
            writers[s].append(r["key"])
    live = {r["key"] for r in routines if r["status"] == "live"}
    for surface, keys in writers.items():
        live_keys = [k for k in keys if k in live]
        if len(live_keys) > 1:
            findings.append((RED, surface, f"written by {', '.join(live_keys)}; give it one owner"))
        elif len(keys) > 1:
            findings.append((INFO, surface, f"would be written by {', '.join(keys)} if all were live"))
        if surface not in registry.get("surfaces", {}):
            findings.append((INFO, surface, "surface not described in the registry"))

    findings.sort(key=lambda f: (SEVERITY_ORDER[f[0]], f[1]))
    return {"findings": findings, "load": load, "writers": dict(writers), "live": sorted(live)}


def render(result: dict, now: datetime, tz_default: str = "Europe/Madrid") -> str:
    f = result["findings"]
    counts = {s: sum(1 for x in f if x[0] == s) for s in (RED, AMBER, INFO)}
    madrid = now.astimezone(ZoneInfo(tz_default)).strftime("%a %d %b %H:%M")
    gulf = now.astimezone(ZoneInfo("Asia/Dubai")).strftime("%H:%M")
    lines = [f"# Automation architect, {madrid} Madrid ({gulf} Gulf)", "",
             f"Red {counts[RED]}, amber {counts[AMBER]}, info {counts[INFO]}.", "", "## Findings", ""]
    lines += [f"{i}. {sev}. {who}: {msg}" for i, (sev, who, msg) in enumerate(f, 1)] or ["None"]
    lines += ["", "## Shared sessions (next 7 days)", "",
              "| Session | Routines | Busiest day | Smallest gap |", "| --- | --- | --- | --- |"]
    for row in result["load"]:
        gap = f"{row['smallest_gap_min']} min" if row["smallest_gap_min"] is not None else "-"
        lines.append(f"| {row['session']} | {'; '.join(row['routines'])} | {row['busiest_day']} runs | {gap} |")
    if not result["load"]:
        lines.append("| None | | | |")
    lines += ["", "## Who writes what", "", "| Surface | Writers |", "| --- | --- |"]
    for surface, keys in sorted(result["writers"].items()):
        marked = [k if k in result["live"] else f"{k} (not live)" for k in keys]
        lines.append(f"| {surface} | {', '.join(marked)} |")
    return "\n".join(lines) + "\n"


def baseline(registry: dict, triggers: list[dict], prompts_dir: Path = PROMPTS) -> list[str]:
    by_id = {t["id"]: t for t in triggers}
    prompts_dir.mkdir(exist_ok=True)
    written = []
    for r in registry["routines"]:
        t = by_id.get(r.get("trigger_id"))
        if t and prompt_of(t):
            (prompts_dir / f"{r['key']}.md").write_text(prompt_of(t).strip() + "\n")
            written.append(r["key"])
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot", type=Path)
    ap.add_argument("--registry", type=Path, default=REGISTRY)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--now")
    ap.add_argument("--baseline", action="store_true")
    args = ap.parse_args()
    registry = json.loads(args.registry.read_text())
    triggers = load_snapshot(args.snapshot)
    if args.baseline:
        print("baseline stored:", ", ".join(baseline(registry, triggers)) or "none")
        return 0
    now = _parse_ts(args.now) if args.now else datetime.now(timezone.utc)
    result = audit(registry, triggers, now)
    report = render(result, now, registry.get("timezone", "Europe/Madrid"))
    if args.out:
        args.out.write_text(report)
    print(report)
    return 1 if any(sev == RED for sev, _, _ in result["findings"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
