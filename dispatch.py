"""Record an authorized native worker's lifecycle in the coordinator's private database."""
import argparse
from datetime import datetime, timezone
import re


def install(db):
    db.execute("""CREATE TABLE IF NOT EXISTS dispatches (
        key TEXT PRIMARY KEY, objective TEXT NOT NULL, scope TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN (
            'reserved','running','reported','accepted','rejected','abandoned','cleaned')),
        host TEXT, worker TEXT, report TEXT, decision TEXT, review TEXT, cleanup TEXT,
        updated TEXT NOT NULL, UNIQUE(host,worker))""")

    db.execute("""CREATE TABLE IF NOT EXISTS dispatch_poll (
        key TEXT PRIMARY KEY REFERENCES dispatches(key), turn INTEGER NOT NULL)""")


def pending(db):
    rows = [dict(row) for row in db.execute("""SELECT d.key,d.state,d.host,d.worker
        FROM dispatches d LEFT JOIN dispatch_poll p USING(key)
        WHERE d.state!='cleaned' ORDER BY COALESCE(p.turn,0),d.updated,d.key LIMIT 3""")]
    if rows:
        turn = db.execute("SELECT COALESCE(MAX(turn),0)+1 FROM dispatch_poll").fetchone()[0]
        db.executemany("""INSERT INTO dispatch_poll(key,turn) VALUES(?,?)
            ON CONFLICT(key) DO UPDATE SET turn=excluded.turn""",
            [(row["key"], turn) for row in rows])
    return rows


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
    actions.add_parser("list", help="Show up to 50 jobs, active work first")
    for name in ("reserve", "bind", "report", "review", "abandon", "cleaned", "show"):
        action = actions.add_parser(name)
        action.add_argument("key", type=key_text)
        if name == "reserve":
            action.add_argument("--objective", required=True, type=short_text)
            action.add_argument("--scope", required=True, type=short_text)
        if name == "bind":
            action.add_argument("thread_id", type=short_text)
            action.add_argument("--host", type=short_text, default="local")
        if name == "review":
            action.add_argument("--decision", choices=("accept", "reject"), required=True)
        if name in {"report", "review", "abandon", "cleaned"}:
            action.add_argument("--evidence", required=True, type=short_text)


def run(db, args, root, bot):
    action = args.dispatch_action
    if action == "list":
        return [dict(row) for row in db.execute("""SELECT * FROM dispatches
            ORDER BY (state='cleaned'), updated DESC,key LIMIT 50""")]
    key = args.key
    stamp = datetime.now(timezone.utc).isoformat()
    if action == "reserve":
        created = db.execute("""INSERT INTO dispatches(key,objective,scope,state,updated)
            VALUES(?,?,?,'reserved',?) ON CONFLICT(key) DO NOTHING""",
            (key, args.objective, args.scope, stamp)).rowcount == 1
    row = db.execute("SELECT * FROM dispatches WHERE key=?", (key,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown dispatch: {key}")
    record = dict(row)
    if action == "show":
        return record
    if action == "reserve":
        if (args.objective, args.scope) != (record["objective"], record["scope"]):
            raise ValueError("Dispatch key already identifies a different objective or scope")
        return dict(record, launch=created)
    if action == "bind":
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
