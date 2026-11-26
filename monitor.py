"""Read operator-selected snapshots. The caller owns the SQLite transaction."""
import argparse
from datetime import datetime
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time

COMMANDS = {"source-add", "source-list", "source-resume", "source-disable",
            "heartbeat", "findings"}
KINDS = {
    "eval": ("metric", "run"),
    "experiment": ("metric", "run"),
    "workload": ("objective",),
    "git": ("commit",),
    "pr": ("status", "head"),
    "ci": ("status", "run"),
    "task": ("status",),
    "file": ("digest",),
}
TEXT = {"status", "objective", "completed", "next_action", "owner", "project",
        "metric", "run", "commit", "head", "digest", "direction", "unit", "milestone"}
LISTS = {"evidence", "blockers", "dependencies"}
REPORT_BYTES = 65536


def install(db):
    db.execute("""CREATE TABLE IF NOT EXISTS monitor_sources (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, filename TEXT NOT NULL UNIQUE,
        stale_hours INTEGER NOT NULL, enabled INTEGER DEFAULT 1,
        outcome TEXT DEFAULT 'pending', failures INTEGER DEFAULT 0,
        retry_at REAL DEFAULT 0, checked REAL DEFAULT 0,
        revision INTEGER, observed REAL, fingerprint TEXT, baseline TEXT, latest TEXT,
        flat_runs INTEGER DEFAULT 0)""")
    db.execute("""CREATE TABLE IF NOT EXISTS monitor_findings (
        id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, kind TEXT NOT NULL,
        priority TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL,
        revision INTEGER, evidence TEXT)""")


def bounded(low, high):
    def parse(raw):
        value = int(raw)
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f"choose an integer between {low} and {high}")
        return value
    return parse


def commands(subparsers):
    add = subparsers.add_parser("source-add", help="register an approved JSON file in the bot inbox")
    add.add_argument("id")
    add.add_argument("kind", choices=sorted(KINDS))
    add.add_argument("filename")
    add.add_argument("--stale-hours", type=bounded(1, 8760), default=24)
    for name in ("source-resume", "source-disable"):
        subparsers.add_parser(name).add_argument("id")
    subparsers.add_parser("source-list")
    pulse = subparsers.add_parser("heartbeat", help="poll a bounded set of eligible sources")
    pulse.add_argument("--limit", type=bounded(1, 32), default=8)
    recent = subparsers.add_parser("findings")
    recent.add_argument("--limit", type=bounded(1, 100), default=20)


def read_snapshot(bot_dir, filename):
    # Anchor the filename to this inbox even if a producer swaps a path during the poll.
    inbox_fd = os.open(bot_dir / "inbox", os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=inbox_fd)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise PermissionError("inbox entry is not a regular file")
            with os.fdopen(fd, "rb", closefd=False) as handle:
                data = handle.read(REPORT_BYTES + 1)
        finally:
            os.close(fd)
    finally:
        os.close(inbox_fd)
    if len(data) > REPORT_BYTES:
        raise ValueError("oversize report")
    return json.loads(data.decode("utf-8"))


def validate(raw, source):
    if not isinstance(raw, dict) or raw.get("source") != source["id"] or raw.get("kind") != source["kind"]:
        raise ValueError("source or kind mismatch")
    rev = raw.get("revision")
    if type(rev) is not int or not 0 < rev < 2**63:
        raise ValueError("invalid revision")
    stamp = raw.get("observed_at")
    if not isinstance(stamp, str):
        raise ValueError("observation needs an ISO date and time")
    when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if when.utcoffset() is None:
        raise ValueError("observation needs a time zone")
    report = {}
    for field in TEXT.intersection(raw):
        value = raw[field]
        if not isinstance(value, str) or not value.strip() or len(value) > 1024:
            raise ValueError("invalid text field")
        report[field] = value
    if not all(field in report for field in KINDS[source["kind"]]):
        raise ValueError("missing required report field")
    for field in LISTS.intersection(raw):
        items = raw[field]
        if not isinstance(items, list) or len(items) > 32 or any(
            not isinstance(x, str) or not x.strip() or len(x) > 512 for x in items
        ):
            raise ValueError("invalid list field")
        report[field] = sorted(set(items))
    if not report.get("evidence"):
        raise ValueError("evidence reference required")
    if "needs_human" in raw:
        if type(raw["needs_human"]) is not bool:
            raise ValueError("invalid needs_human field")
        report["needs_human"] = raw["needs_human"]
    if source["kind"] in {"eval", "experiment"}:
        value = raw.get("value")
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("expected finite metric")
        if report.get("direction") not in {"higher", "lower"}:
            raise ValueError("invalid metric direction")
        report["value"] = value
    return rev, when.timestamp(), report


def finding(db, source, kind, priority, detail, now, rev=None, evidence=()):
    row = db.execute("""
        INSERT INTO monitor_findings(source_id,kind,priority,detail,created,revision,evidence)
        VALUES(?,?,?,?,?,?,?)""", (source["id"], kind, priority, detail, now, rev, json.dumps(evidence)))
    return {"id": row.lastrowid, "source_id": source["id"], "kind": kind,
            "priority": priority, "detail": detail, "revision": rev, "evidence": evidence}


def blocker_signature(report):
    state = report.get("status")
    return (bool(report.get("needs_human")), tuple(report.get("blockers", ())),
            state if state in {"blocked", "failed", "failure"} else None)


def classify(source, report, changed):
    previous = json.loads(source["latest"]) if source["latest"] else {}
    flat = source["flat_runs"]
    if not previous:
        return flat, []
    events = []
    blocker = blocker_signature(report)
    if any(blocker) and blocker != blocker_signature(previous):
        events.append(("attention", "attention", "Reported blocker or failure. Inspect the evidence."))
    if source["kind"] in {"eval", "experiment"}:
        comparable = all(previous.get(k) == report.get(k) for k in ("metric", "unit", "direction"))
        if not comparable:
            flat = 0
        else:
            before, after = previous["value"], report["value"]
            if previous["run"] != report["run"] and before == after:
                flat += 1
            if after != before:
                flat = 0
                better = (after > before) == (report["direction"] == "higher")
                kind = "improvement" if better else "regression"
                priority = "briefing" if better else "attention"
                events.append((kind, priority, f"{report['metric']} moved from {before} to {after}."))
            elif flat == 3 and previous["run"] != report["run"]:
                events.append(("stagnation", "attention", "Three new runs repeated the preceding metric value."))
    if changed and not events:
        events.append(("changed", "briefing", "Reported state changed. Review the snapshot and evidence."))
    return flat, events


def problem(db, source, outcome, now):
    failures = min(source["failures"] + 1, 20)
    disabled = outcome == "denied"
    delay = 21600 if failures >= 5 else 60 * 2 ** (failures - 1)
    db.execute("""UPDATE monitor_sources SET outcome=?, failures=?, retry_at=?,
                  checked=?, enabled=? WHERE id=?""",
               (outcome, failures, now + delay, now, int(not disabled), source["id"]))
    if source["outcome"] == outcome:
        return []
    messages = {
        "denied": "Source access denied. Polling stopped pending operator review.",
        "unavailable": "Source unavailable. A later heartbeat will retry.",
        "invalid": "Report failed validation. The last accepted observation is retained.",
        "stale": "Report is stale. Current workload status needs verification.",
    }
    return [finding(db, source, outcome, "attention", messages[outcome], now)]


def observe(db, bot, source, now):
    try:
        raw = read_snapshot(bot, source["filename"])
        if isinstance(raw, dict) and raw.get("source") == source["id"] and raw.get("kind") == source["kind"]:
            if raw.get("error") in ("denied", "unavailable"):
                return problem(db, source, raw["error"], now)
        rev, observed, report = validate(raw, source)
        canonical = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        if observed > now + 300:
            raise ValueError("future observation")
        if source["revision"] is not None:
            if rev < source["revision"] or observed < source["observed"]:
                return problem(db, source, "stale", now)
            if rev == source["revision"] and digest != source["fingerprint"]:
                raise ValueError("revision conflict")
        if now - observed > source["stale_hours"] * 3600:
            return problem(db, source, "stale", now)
    except PermissionError:
        return problem(db, source, "denied", now)
    except OSError as exc:
        denied = exc.errno in {errno.ELOOP, errno.ENOTDIR, errno.EPERM, errno.EACCES}
        return problem(db, source, "denied" if denied else "unavailable", now)
    except (ValueError, OverflowError, RecursionError):
        return problem(db, source, "invalid", now)
    changed = digest != source["fingerprint"]
    outcome = "changed" if changed else "unchanged"
    if source["revision"] is None:
        outcome = "baseline"
    flat, events = classify(source, report, changed)
    if source["outcome"] in {"invalid", "unavailable", "stale", "denied"}:
        events.append(("recovered", "briefing", "Received a valid current snapshot."))
    db.execute("""UPDATE monitor_sources SET checked=?, revision=?, observed=?, fingerprint=?,
                  latest=?, baseline=COALESCE(baseline,?), flat_runs=?, failures=0,
                  retry_at=0, outcome=? WHERE id=?""",
               (now, rev, observed, digest, canonical, canonical, flat, outcome, source["id"]))
    return [finding(db, source, *event, now, rev, report["evidence"]) for event in events]


def run(db, args, root, bot):
    cmd = args.command
    if cmd == "source-add":
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", args.id):
            raise ValueError("source ID must be a lowercase slug")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.json", args.filename):
            raise ValueError("choose a single .json filename in the bot inbox")
        current = db.execute("SELECT * FROM monitor_sources WHERE id=?", (args.id,)).fetchone()
        if current and (current["filename"], current["kind"], current["stale_hours"]) != (
                args.filename, args.kind, args.stale_hours):
            raise ValueError("source ID already has a different registration")
        db.execute("""INSERT INTO monitor_sources(id,kind,filename,stale_hours) VALUES(?,?,?,?)
                      ON CONFLICT(id) DO NOTHING""", (args.id, args.kind, args.filename, args.stale_hours))
        return {"source": args.id, "filename": args.filename}
    if cmd in {"source-disable", "source-resume"}:
        enabled = int(cmd == "source-resume")
        cursor = db.execute("UPDATE monitor_sources SET enabled=?, retry_at=0 WHERE id=?",
                            (enabled, args.id))
        if not cursor.rowcount:
            raise ValueError("unknown source ID")
        return {"source": args.id, "enabled": bool(enabled)}
    if cmd == "source-list":
        return [dict(row) for row in db.execute("""SELECT id,kind,filename,enabled,outcome,
                revision,observed,checked,retry_at,stale_hours FROM monitor_sources ORDER BY id""")]
    if cmd == "findings":
        rows = db.execute("SELECT * FROM monitor_findings ORDER BY id DESC LIMIT ?", (args.limit,))
        return [dict(dict(row), evidence=json.loads(row["evidence"])) for row in rows]
    if cmd == "heartbeat":
        now = time.time()
        folder = Path(bot)
        if not folder.is_absolute():
            folder = Path(root) / "bots" / folder
        due = db.execute("""SELECT * FROM monitor_sources WHERE enabled=1 AND retry_at<=?
                            ORDER BY checked,id LIMIT ?""", (now, args.limit)).fetchall()
        attention = []
        for source in due:
            for item in observe(db, folder, source, now):
                if item["priority"] == "attention":
                    attention.append(item)
        return attention or None
    raise ValueError("unknown monitoring command")
