"""Record an authorized native worker's lifecycle in the coordinator's private database."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
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

    if "launch_route" not in columns:
        db.execute("ALTER TABLE dispatches ADD COLUMN launch_route TEXT")

    db.execute("""CREATE TABLE IF NOT EXISTS dispatch_poll (
        key TEXT PRIMARY KEY REFERENCES dispatches(key), turn INTEGER NOT NULL)""")

    db.execute("""CREATE TABLE IF NOT EXISTS dispatch_additions (
        key TEXT PRIMARY KEY, parent TEXT NOT NULL REFERENCES dispatches(key),
        requirement TEXT NOT NULL, handoff TEXT NOT NULL DEFAULT 'pending'
            CHECK(handoff IN ('pending','sending','sent')),
        authorization TEXT, evidence TEXT, updated TEXT NOT NULL)""")
    columns = {row[1] for row in db.execute("PRAGMA table_info(dispatch_additions)")}
    if "required" not in columns:
        db.execute("ALTER TABLE dispatch_additions ADD COLUMN required INTEGER NOT NULL DEFAULT 0")
    if "acknowledgement" not in columns:
        db.execute("ALTER TABLE dispatch_additions ADD COLUMN acknowledgement TEXT")
        db.execute("ALTER TABLE dispatch_additions ADD COLUMN acknowledgement_turn TEXT")
    if "send_denial" not in columns:
        db.execute("ALTER TABLE dispatch_additions ADD COLUMN send_denial TEXT")

    db.execute("""CREATE TABLE IF NOT EXISTS dispatch_checkpoints (
        key TEXT PRIMARY KEY REFERENCES dispatches(key), expected TEXT NOT NULL,
        correction TEXT NOT NULL, drift TEXT, recovery TEXT)""")


def configure_checkpoint(db, args, record):
    if record["state"] not in {"reserved", "running"}:
        raise ValueError("Checkpoint monitoring requires an open dispatch")
    db.execute("""INSERT INTO dispatch_checkpoints(key,expected,correction) VALUES(?,?,?)
        ON CONFLICT(key) DO NOTHING""", (args.key, args.expected, args.correction))
    plan = checkpoint(db, args.key)
    if (plan["expected"], plan["correction"]) != (args.expected, args.correction):
        raise ValueError("Checkpoint already configured for this dispatch")
    return plan


def observe_checkpoint(db, args, record, stamp):
    plan = checkpoint(db, args.key)
    if (plan is None or plan["recovery"] is not None or record["state"] != "running"
            or (record["host"], record["worker"]) != (args.host, args.worker)):
        return None
    handoff_key = "drift-" + sha256(args.key.encode()).hexdigest()[:32]
    evidence = f"Codex turn {args.turn}, item {args.item}"
    if plan["drift"] is not None:
        if args.value == plan["expected"] and args.handoff == handoff_key:
            handoff_record = addition(db, handoff_key)
            if (handoff_record and handoff_record["parent"] == args.key and handoff_record["handoff"] == "sent"
                    and handoff_record["acknowledgement"]):
                db.execute("UPDATE dispatch_checkpoints SET recovery=? WHERE key=?", (evidence, args.key))
                return {"parent": args.key, "key": handoff_key, "status": "recovered", "evidence": evidence}
        return None
    if args.value == plan["expected"] or args.handoff is not None:
        return None
    if addition(db, handoff_key) is not None:
        raise ValueError("Checkpoint correction key is already in use")
    permissions = [{"id": "send-correction", "action": "Send one in-scope checkpoint correction",
                    "target": f"Codex worker {args.worker} on {args.host}", "required": True}]
    request = argparse.Namespace(key=handoff_key, reuse=args.key, requirement=plan["correction"],
                                 objective=record["objective"], scope=record["scope"],
                                 plan=json.dumps(permissions), decisions=None, required=True, launch_route=None)
    reserve(db, request, stamp)
    db.execute("UPDATE dispatch_checkpoints SET drift=? WHERE key=?", (f"{evidence}: {args.value}", args.key))
    return {"parent": args.key, "key": handoff_key, "status": "drift", "expected": plan["expected"],
            "observed": args.value, "evidence": evidence}


def checkpoint(db, key):
    row = db.execute("SELECT * FROM dispatch_checkpoints WHERE key=?", (key,)).fetchone()
    return dict(row) if row else None


def pending_handoffs(db):
    return [dict(row) for row in db.execute("""SELECT a.key,a.parent,a.handoff,d.state,d.host,d.worker
        FROM dispatch_additions a JOIN dispatches d ON d.key=a.parent
        WHERE a.handoff!='sent' OR (a.required AND a.acknowledgement IS NULL)
        ORDER BY a.updated,a.key""")]


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
    for row in rows:
        if row["state"] == "running":
            plan = checkpoint(db, row["key"])
            if plan and plan["recovery"] is None:
                row["check_checkpoint"] = True
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


def native_id(raw):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}", raw):
        raise argparse.ArgumentTypeError("Use a native identifier of up to 128 characters")
    return raw


def launch_route(raw):
    def valid_text(value):
        return isinstance(value, str) and bool(value.strip()) and len(value) <= 4096 and "\0" not in value

    try:
        route = json.loads(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Supply the approved native launch route as JSON") from exc
    if not isinstance(route, dict) or set(route) != {"projectId", "projectPath", "hostId", "environment"}:
        raise argparse.ArgumentTypeError("A launch route requires projectId, projectPath, hostId and environment")
    if not all(valid_text(route[field]) for field in ("projectId", "projectPath", "hostId")):
        raise argparse.ArgumentTypeError("Launch route identifiers and path must be nonempty text")

    environment = route["environment"]
    if environment != {"type": "local"}:
        if (not isinstance(environment, dict) or environment.get("type") != "worktree"
                or set(environment) - {"type", "startingState"}):
            raise argparse.ArgumentTypeError("Use a local or worktree environment")
        if "startingState" in environment:
            start = environment["startingState"]
            if start != {"type": "working-tree"} and (
                    not isinstance(start, dict) or start.get("type") != "branch"
                    or set(start) - {"type", "branchName", "onMissing"}
                    or not valid_text(start.get("branchName"))
                    or start.get("onMissing", "error") not in ("error", "create-branch")):
                raise argparse.ArgumentTypeError("Use a working-tree or named branch starting state")
    return json.dumps(route, sort_keys=True, separators=(",", ":"))


def commands(sub):
    actions = sub.add_parser("dispatch", help="Coordinate native worker chats").add_subparsers(
        dest="dispatch_action", required=True)
    listing = actions.add_parser("list", help="Show up to 50 jobs, active work first")
    listing.add_argument("--active", action="store_true", help="Show all running jobs with bound workers")
    for name in ("reserve", "bind", "report", "review", "abandon", "delivered", "cleaned", "show",
                 "handoff", "permissions", "monitor", "checkpoint"):
        action = actions.add_parser(name)
        action.add_argument("key", type=key_text)
        if name == "monitor":
            action.add_argument("--expected", required=True, type=key_text)
            action.add_argument("--correction", required=True, type=short_text)
        if name == "checkpoint":
            for field in ("host", "worker", "turn", "item"):
                action.add_argument("--" + field, required=True, type=native_id)
            action.add_argument("--value", required=True, type=key_text)
            action.add_argument("--handoff", type=key_text)
        if name == "reserve":
            action.add_argument("--objective", required=True, type=short_text)
            action.add_argument("--scope", required=True, type=short_text)
            action.add_argument("--reuse", type=key_text, help="Reuse this dispatch's bound worker")
            action.add_argument("--requirement", type=short_text, help="Additional work within the existing scope")
            action.add_argument("--required", action="store_true", help="Require adoption of a reused assignment")
            action.add_argument("--plan", metavar="JSON", help="Permission requests to record for this dispatch")
            action.add_argument("--prepare", action="store_true", help="Record intake without claiming a launch")
            action.add_argument("--launch-route", type=launch_route, metavar="JSON",
                                help="Approved native project, path, host and execution environment")
        if name in {"reserve", "permissions"}:
            action.add_argument("--decisions", metavar="JSON", help="Verified operator decisions and references")
        if name == "handoff":
            operation = action.add_mutually_exclusive_group(required=True)
            operation.add_argument("--claim", type=short_text, metavar="AUTHORIZATION")
            operation.add_argument("--sent", type=short_text, metavar="EVIDENCE")
            operation.add_argument("--reset", type=short_text, metavar="EVIDENCE")
            operation.add_argument("--denied", type=short_text, metavar="EVIDENCE")
            operation.add_argument("--acknowledged", type=short_text, metavar="WORKER_EVIDENCE")
            action.add_argument("--host", type=short_text)
            action.add_argument("--worker", type=short_text)
            action.add_argument("--turn", type=short_text)
        if name == "bind":
            action.add_argument("thread_id", type=short_text)
            action.add_argument("--host", type=short_text, default="local")
        if name == "report":
            action.add_argument("--covers", action="append", type=key_text, default=[], metavar="REQUIREMENT")
        if name == "review":
            action.add_argument("--verified", action="append", type=key_text, default=[], metavar="REQUIREMENT")
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
    if args.required and not args.reuse:
        raise ValueError("--required applies only to a reused dispatch")
    if args.reuse and args.launch_route is not None:
        raise ValueError("A reused dispatch keeps its bound worker")
    existing = addition(db, key)
    if existing:
        if (args.reuse, args.requirement, args.objective, args.scope, args.required) != (
                existing["parent"], existing["requirement"], existing["objective"], existing["scope"],
                bool(existing["required"])):
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
        db.execute("""INSERT INTO dispatch_additions(key,parent,requirement,updated,required)
                   VALUES(?,?,?,?,?)""", (key, args.reuse, args.requirement, stamp, args.required))
        return reserve_permissions(db, args, dict(addition(db, key), launch=False), allow_new=True)
    db.execute("""INSERT INTO dispatches(key,objective,scope,state,updated,launch_issued,launch_route)
        VALUES(?,?,?,'reserved',?,0,?) ON CONFLICT(key) DO NOTHING""",
        (key, args.objective, args.scope, stamp, args.launch_route))
    record = dict(db.execute("SELECT * FROM dispatches WHERE key=?", (key,)).fetchone())
    if (args.objective, args.scope) != (record["objective"], record["scope"]):
        raise ValueError("Dispatch key already identifies a different objective or scope")
    if (record["state"] == "reserved" and args.launch_route != record["launch_route"]
            and (args.launch_route is not None or not args.prepare)):
        blocker = "native_route_unavailable" if record["launch_route"] is None else "native_route_mismatch"
        return dict(record, launch=False, blocker=blocker)
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
    if args.acknowledged:
        return acknowledge(db, args, stamp, record)
    if args.host or args.worker or args.turn:
        raise ValueError("--host, --worker and --turn apply only to --acknowledged")
    current = record["handoff"]
    if record["send_denial"]:
        if args.claim or args.denied == record["send_denial"]:
            return dict(record, send=False)
        raise ValueError("The native send was denied")
    if args.denied:
        if current != "sending":
            raise ValueError("Record a native denial only after claiming the send")
        db.execute("UPDATE dispatch_additions SET send_denial=?, updated=? WHERE key=?",
                   (args.denied, stamp, args.key))
        return dict(record, send_denial=args.denied, updated=stamp, send=False)
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


def acknowledge(db, args, stamp, record):
    if not (args.host and args.worker and args.turn):
        raise ValueError("Supply the observed --host, --worker and --turn")
    if (args.host, args.worker) != (record["host"], record["worker"]):
        raise ValueError("Acknowledgement must come from the exact bound worker")
    if not record["required"] or record["handoff"] != "sent":
        raise ValueError("Acknowledgement requires a confirmed send for a required handoff")
    changes = {"acknowledgement": args.acknowledged, "acknowledgement_turn": args.turn}
    if all(record[field] == value for field, value in changes.items()):
        return dict(record, send=False)
    if record["acknowledgement"]:
        raise ValueError("Acknowledgement is already recorded")
    if record["state"] != "running":
        raise ValueError("The bound dispatch is no longer running")
    db.execute("""UPDATE dispatch_additions SET acknowledgement=?, acknowledgement_turn=?, updated=?
        WHERE key=?""", (args.acknowledged, args.turn, stamp, args.key))
    return dict(record, **changes, updated=stamp, send=False)


def check_required_additions(db, parent, covered):
    rows = db.execute("""SELECT key,acknowledgement FROM dispatch_additions
        WHERE parent=? AND required ORDER BY key""", (parent,)).fetchall()
    unresolved = [row["key"] for row in rows if not row["acknowledgement"]]
    if unresolved:
        raise ValueError("Required handoffs await worker acknowledgement: " + ", ".join(unresolved))
    if {row["key"] for row in rows} != set(covered):
        raise ValueError("Supply coverage for exactly these required handoffs: " +
                         (", ".join(row["key"] for row in rows) or "none"))


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
    if action == "monitor":
        return configure_checkpoint(db, args, record)
    if action == "checkpoint":
        return observe_checkpoint(db, args, record, stamp)
    if action == "show":
        plan = checkpoint(db, key)
        if plan:
            record["checkpoint"] = plan
        added = [dict(row) for row in db.execute("""SELECT key,requirement,handoff,required,acknowledgement,
            acknowledgement_turn,send_denial FROM dispatch_additions
            WHERE parent=? ORDER BY key""", (key,))]
        if added:
            record["additions"] = added
        return permission_plan.annotate(db, "dispatch", key, record)
    if action == "bind":
        if not record["launch_issued"]:
            raise ValueError("Claim the dispatch launch with reserve before binding a worker")
        if record["launch_route"] is not None and args.host != json.loads(record["launch_route"])["hostId"]:
            raise ValueError("Worker host differs from the approved launch route")
        changes = {"worker": args.thread_id, "host": args.host}
        required = ("reserved",)
        state = "running"
    elif action == "report":
        check_required_additions(db, key, args.covers)
        changes = {"report": args.evidence}
        required = ("running",)
        state = "reported"
    elif action == "review":
        if args.decision == "accept":
            check_required_additions(db, key, args.verified)
        elif args.verified:
            raise ValueError("--verified applies only to acceptance")
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
