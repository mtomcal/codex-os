"""Record an authorized native worker's lifecycle in the coordinator's private database."""
import argparse
from datetime import datetime, timezone
import json
import re
from uuid import UUID

import permission_plan


def install(db):
    db.execute("""CREATE TABLE IF NOT EXISTS dispatches (
        key TEXT PRIMARY KEY, objective TEXT NOT NULL, scope TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN (
            'reserved','running','reported','accepted','rejected','abandoned','cleaned')),
        host TEXT, worker TEXT, report TEXT, decision TEXT, review TEXT, cleanup TEXT,
        updated TEXT NOT NULL, UNIQUE(host,worker))""")

    columns = {row[1] for row in db.execute("PRAGMA table_info(dispatches)")}
    if "delivery" not in columns:
        db.execute("ALTER TABLE dispatches ADD COLUMN delivery TEXT")
    if "launch_issued" not in columns:
        db.execute("ALTER TABLE dispatches ADD COLUMN launch_issued INTEGER NOT NULL DEFAULT 1")

    db.execute("""CREATE TABLE IF NOT EXISTS dispatch_poll (
        key TEXT PRIMARY KEY REFERENCES dispatches(key), turn INTEGER NOT NULL)""")

    db.execute("""CREATE TABLE IF NOT EXISTS dispatch_additions (
        key TEXT PRIMARY KEY, parent TEXT NOT NULL REFERENCES dispatches(key),
        requirement TEXT NOT NULL, handoff TEXT NOT NULL DEFAULT 'pending'
            CHECK(handoff IN ('pending','sending','sent')),
        authorization TEXT, evidence TEXT, updated TEXT NOT NULL)""")


def pending_handoffs(db):
    return [dict(row) for row in db.execute("""SELECT a.key,a.parent,a.handoff,d.state,d.host,d.worker
        FROM dispatch_additions a JOIN dispatches d ON d.key=a.parent
        WHERE a.handoff!='sent' ORDER BY a.updated,a.key""")]


def pending(db):
    rows = [dict(row) for row in db.execute("""SELECT d.key,d.state,d.host,d.worker,d.delivery
        FROM dispatches d LEFT JOIN dispatch_poll p USING(key)
        WHERE d.state!='cleaned' AND (d.launch_issued OR d.state!='reserved')
        ORDER BY COALESCE(p.turn,0),d.updated,d.key LIMIT 3""")]
    if rows:
        turn = db.execute("SELECT COALESCE(MAX(turn),0)+1 FROM dispatch_poll").fetchone()[0]
        db.executemany("""INSERT INTO dispatch_poll(key,turn) VALUES(?,?)
            ON CONFLICT(key) DO UPDATE SET turn=excluded.turn""",
            [(row["key"], turn) for row in rows])
    return rows


def cleanup_candidates(root, workers):
    ready = [row for row in workers if row["delivery"] and row["host"] == "local" and row["worker"]
             and row["state"] in {"accepted", "rejected", "abandoned"}]
    if not ready:
        return []
    protected = {json.loads(path.read_text()).get("primary_thread")
                 for path in (root / "bots").glob("*/bot.json")}
    result = []
    for row in ready:
        try:
            worker = str(UUID(row["worker"]))
        except ValueError:
            continue
        if worker == row["worker"] and worker not in protected:
            result.append({"key": row["key"], "worker": worker, "host": row["host"]})
    return result


def short_text(raw):
    value = raw.strip()
    if not value or len(value) > 4000:
        raise argparse.ArgumentTypeError("Supply 1 to 4000 characters")
    return value


def key_text(raw):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", raw):
        raise argparse.ArgumentTypeError("Use a lowercase key of up to 64 characters")
    return raw


def commands(sub):
    actions = sub.add_parser("dispatch", help="Coordinate native worker chats").add_subparsers(
        dest="dispatch_action", required=True)
    listing = actions.add_parser("list", help="Show up to 50 jobs, active work first")
    listing.add_argument("--active", action="store_true", help="Show all running jobs with bound workers")
    for name in ("reserve", "bind", "report", "review", "abandon", "delivered", "cleaned", "show",
                 "handoff", "permissions"):
        action = actions.add_parser(name)
        action.add_argument("key", type=key_text)
        if name == "reserve":
            action.add_argument("--objective", required=True, type=short_text)
            action.add_argument("--scope", required=True, type=short_text)
            action.add_argument("--reuse", type=key_text, help="Reuse this dispatch's bound worker")
            action.add_argument("--requirement", type=short_text, help="Additional work within the existing scope")
            action.add_argument("--plan", metavar="JSON", help="Permission requests to record for this dispatch")
            action.add_argument("--prepare", action="store_true", help="Record intake without claiming a launch")
        if name in {"reserve", "permissions"}:
            action.add_argument("--decisions", metavar="JSON", help="Verified operator decisions and references")
        if name == "handoff":
            operation = action.add_mutually_exclusive_group(required=True)
            operation.add_argument("--claim", type=short_text, metavar="AUTHORIZATION")
            operation.add_argument("--sent", type=short_text, metavar="EVIDENCE")
            operation.add_argument("--reset", type=short_text, metavar="EVIDENCE")
        if name == "bind":
            action.add_argument("thread_id", type=short_text)
            action.add_argument("--host", type=short_text, default="local")
        if name == "review":
            action.add_argument("--decision", choices=("accept", "reject"), required=True)
        if name in {"report", "review", "abandon", "delivered", "cleaned"}:
            action.add_argument("--evidence", required=True, type=short_text)


def addition(db, key):
    row = db.execute("""SELECT a.*, d.objective,d.scope,d.state,d.host,d.worker
        FROM dispatch_additions a JOIN dispatches d ON d.key=a.parent WHERE a.key=?""", (key,)).fetchone()
    return dict(row) if row else None


def reserve_permissions(db, args, record, *, allow_new):
    key = args.key
    if args.plan is not None:
        permission_plan.add(db, "dispatch", key, args.plan, allow_new=allow_new)
    if args.decisions is not None:
        permission_plan.decide(db, "dispatch", key, args.decisions)
    return permission_plan.annotate(db, "dispatch", key, record)


def reserve(db, args, stamp):
    key = args.key
    if bool(args.reuse) != bool(args.requirement):
        raise ValueError("Supply --reuse and --requirement together")
    existing = addition(db, key)
    if existing:
        if (args.reuse, args.requirement, args.objective, args.scope) != (
                existing["parent"], existing["requirement"], existing["objective"], existing["scope"]):
            raise ValueError("Dispatch key already identifies a different request")
        return reserve_permissions(db, args, dict(existing, launch=False), allow_new=False)
    if args.reuse:
        if db.execute("SELECT 1 FROM dispatches WHERE key=?", (key,)).fetchone():
            raise ValueError("Dispatch key already identifies a standalone job")
        parent = db.execute("SELECT * FROM dispatches WHERE key=?", (args.reuse,)).fetchone()
        if parent is None or parent["state"] != "running" or not (parent["host"] and parent["worker"]):
            raise ValueError("Reuse requires a running dispatch with a bound worker")
        if (args.objective, args.scope) != (parent["objective"], parent["scope"]):
            raise ValueError("Reuse requires the existing dispatch's exact objective and scope")
        db.execute("INSERT INTO dispatch_additions(key,parent,requirement,updated) VALUES(?,?,?,?)",
                   (key, args.reuse, args.requirement, stamp))
        return reserve_permissions(db, args, dict(addition(db, key), launch=False), allow_new=True)
    db.execute("""INSERT INTO dispatches(key,objective,scope,state,updated,launch_issued)
        VALUES(?,?,?,'reserved',?,0) ON CONFLICT(key) DO NOTHING""",
        (key, args.objective, args.scope, stamp))
    record = dict(db.execute("SELECT * FROM dispatches WHERE key=?", (key,)).fetchone())
    if (args.objective, args.scope) != (record["objective"], record["scope"]):
        raise ValueError("Dispatch key already identifies a different objective or scope")
    unclaimed = record["state"] == "reserved" and not record["launch_issued"]
    record = reserve_permissions(db, args, record, allow_new=unclaimed)
    launch = unclaimed and not args.prepare and record.get("permissions", {}).get("status", "ready") == "ready"
    if launch:
        db.execute("UPDATE dispatches SET launch_issued=1,updated=? WHERE key=?", (stamp, key))
        record.update(launch_issued=1, updated=stamp)
    return dict(record, launch=launch)


def handoff(db, args, stamp):
    record = addition(db, args.key)
    if record is None:
        raise ValueError(f"Unknown added requirement: {args.key}")
    current = record["handoff"]
    if args.claim:
        if current != "pending":
            return dict(record, send=False)
        if record["state"] != "running":
            raise ValueError("The bound dispatch is no longer running")
        status = permission_plan.read(db, "dispatch", args.key)["status"]
        if status != "ready":
            raise ValueError(f"Required handoff permissions are {status}")
        changes = {"handoff": "sending", "authorization": args.claim, "evidence": None}
    elif args.sent:
        changes = {"handoff": "sent", "evidence": args.sent}
    else:
        changes = {"handoff": "pending", "authorization": None, "evidence": args.reset}
    if all(record[field] == value for field, value in changes.items()):
        return dict(record, send=False)
    if current != ("pending" if args.claim else "sending"):
        raise ValueError(f"Cannot change a handoff in state {current}")
    changes["updated"] = stamp
    columns = ", ".join(f"{field}=?" for field in changes)
    db.execute(f"UPDATE dispatch_additions SET {columns} WHERE key=?", (*changes.values(), args.key))
    return dict(record, **changes, send=bool(args.claim))


def run(db, args, root, bot):
    action = args.dispatch_action
    if action == "list":
        if args.active:
            return [dict(row) for row in db.execute("""SELECT * FROM dispatches
                WHERE state='running' AND host IS NOT NULL AND worker IS NOT NULL
                ORDER BY updated DESC,key""")]
        return [dict(row) for row in db.execute("""SELECT * FROM dispatches
            ORDER BY (state='cleaned'), updated DESC,key LIMIT 50""")]
    key = args.key
    stamp = datetime.now(timezone.utc).isoformat()
    if action == "reserve":
        return reserve(db, args, stamp)
    if action == "handoff":
        return handoff(db, args, stamp)
    row = db.execute("SELECT * FROM dispatches WHERE key=?", (key,)).fetchone()
    if action == "permissions" and (row is not None or addition(db, key) is not None):
        if args.decisions is not None:
            permission_plan.decide(db, "dispatch", key, args.decisions)
        return permission_plan.read(db, "dispatch", key)
    if row is None:
        if action == "show" and (record := addition(db, key)):
            return permission_plan.annotate(db, "dispatch", key, record)
        raise ValueError(f"Unknown dispatch: {key}")
    record = dict(row)
    if action == "show":
        added = [dict(row) for row in db.execute("""SELECT key,requirement,handoff FROM dispatch_additions
            WHERE parent=? ORDER BY key""", (key,))]
        if added:
            record["additions"] = added
        return permission_plan.annotate(db, "dispatch", key, record)
    if action == "bind":
        if not record["launch_issued"]:
            raise ValueError("Claim the dispatch launch with reserve before binding a worker")
        changes = {"worker": args.thread_id, "host": args.host}
        required = ("reserved",)
        state = "running"
    elif action == "report":
        changes = {"report": args.evidence}
        required = ("running",)
        state = "reported"
    elif action == "review":
        state = {"accept": "accepted", "reject": "rejected"}[args.decision]
        changes = {"decision": state, "review": args.evidence}
        required = ("reported",)
    elif action == "abandon":
        state = "abandoned"
        changes = {"decision": state, "review": args.evidence}
        required = ("reserved", "running")
    elif action == "delivered":
        state = record["state"]
        changes = {"delivery": args.evidence}
        required = ("accepted", "rejected", "abandoned")
        if record["delivery"] and record["delivery"] != args.evidence:
            raise ValueError("Delivery is already recorded")
    elif action == "cleaned":
        state = "cleaned"
        changes = {"cleanup": args.evidence}
        required = ("accepted", "rejected", "abandoned")
    else:
        raise ValueError("Unknown dispatch action")
    if all(record[field] == value for field, value in changes.items()):
        return record
    if record["state"] not in required:
        raise ValueError(f"Cannot {action} a dispatch in state {record['state']}")
    changes.update(state=state, updated=stamp)
    columns = ", ".join(f"{field}=?" for field in changes)
    db.execute(f"UPDATE dispatches SET {columns} WHERE key=?", (*changes.values(), key))
    return dict(record, **changes)
