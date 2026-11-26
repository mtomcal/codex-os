"""Private occurrence ledger for the desktop heartbeat."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import secrets
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import ledger


DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
LIMIT = 3
ATTEMPTS = 3
ID = re.compile(r"[0-9a-f]{32}")
THREAD = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
CLOCK = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
FULL_DAY = "24:00"


def local_time(value, *, end=False):
    if isinstance(value, str) and (CLOCK.fullmatch(value) or (end and value == FULL_DAY)):
        hour, minute = value.split(":")
        return int(hour) * 60 + int(minute)
    raise ValueError("Use local times in HH:MM format")


def window(value):
    if not isinstance(value, dict) or value.keys() != {"days", "start", "end"}:
        raise ValueError("A window needs days, start and end")
    days = value["days"]
    if not isinstance(days, list) or not days or any(day not in DAYS for day in days):
        raise ValueError("Use weekday codes mon through sun")
    if local_time(value["start"]) >= local_time(value["end"], end=True):
        raise ValueError("The window must end after it starts, within the same day")
    return dict(value, days=[day for day in DAYS if day in days])


def plan_config(value):
    if not isinstance(value, dict) or value.keys() - {"minutes", "window", "timezone", "catch_up_hours", "scope"}:
        raise ValueError("Use the delegated heartbeat fields in docs/fleet.md")
    minutes = value.get("minutes", 15)
    hours = value.get("catch_up_hours", 24)
    if type(minutes) is not int or not 1 <= minutes <= 60:
        raise ValueError("Tick cadence must be between 1 and 60 minutes")
    if type(hours) is not int or not 1 <= hours <= 168:
        raise ValueError("Catch-up must be between 1 and 168 hours")
    zone = value.get("timezone")
    try:
        ZoneInfo(zone)
    except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("Choose an IANA time zone") from exc
    scope = value.get("scope")
    if not isinstance(scope, str) or not 1 <= len(scope.strip()) <= 4096:
        raise ValueError("Describe the authorized scope for delegated execution")
    return {"minutes": minutes, "window": window(value.get("window")), "timezone": zone,
            "catch_up_hours": hours, "scope": scope.strip()}


def timing(value):
    if not isinstance(value, dict) or value.keys() != {"window", "every_minutes"}:
        raise ValueError("Scheduled work needs a window and every_minutes")
    cadence = value["every_minutes"]
    if type(cadence) is not int or not 1 <= cadence <= 1440:
        raise ValueError("Routine cadence must be between 1 and 1440 minutes")
    return {"window": window(value["window"]), "every_minutes": cadence}


def install(db):
    for ddl in (
        """CREATE TABLE IF NOT EXISTS schedule_binding (
            slot INTEGER PRIMARY KEY CHECK(slot=1), plan TEXT NOT NULL, chat TEXT NOT NULL,
            automation TEXT NOT NULL, project TEXT NOT NULL, approved_at REAL NOT NULL,
            approval TEXT NOT NULL, first_tick REAL)""",
        """CREATE TABLE IF NOT EXISTS schedule_occurrences (
            id TEXT PRIMARY KEY, plan TEXT NOT NULL, routine TEXT NOT NULL, due REAL NOT NULL,
            event TEXT, evidence TEXT, state TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
            token TEXT, worker TEXT, changed REAL NOT NULL, receipt TEXT)""",
        """CREATE INDEX IF NOT EXISTS schedule_ready ON schedule_occurrences (plan,state,due,id)""",
        """CREATE TABLE IF NOT EXISTS schedule_updates (
            revision INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, subject TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS schedule_ack (
            chat TEXT PRIMARY KEY, revision INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS schedule_seen (
            chat TEXT PRIMARY KEY, revision INTEGER NOT NULL)""",
    ):
        db.execute(ddl)
    for table, kind, subject, when in (
        ("schedule_occurrences", "occurrence", "new.id", "OLD.state IS NOT NEW.state OR OLD.receipt IS NOT NEW.receipt"),
        ("schedule_binding", "heartbeat", "new.automation", "OLD.plan IS NOT NEW.plan OR OLD.chat IS NOT NEW.chat OR OLD.first_tick IS NOT NEW.first_tick"),
        ("ledger_items", "work", "new.kind || '/' || new.id", "OLD.revision IS NOT NEW.revision"),
    ):
        for event, condition in (("INSERT", ""), ("UPDATE", "WHEN " + when)):
            db.execute(f"""CREATE TRIGGER IF NOT EXISTS revision_{table}_{event}
                AFTER {event} ON {table} {condition}
                BEGIN INSERT INTO schedule_updates (kind, subject) VALUES ('{kind}', {subject}); END""")


def plan(bot, manifest):
    setup = manifest.get("setup") or {}
    config = setup.get("delegated_heartbeat")
    if config is None:
        return None
    config = plan_config(config)
    routines = []
    manifest_entries = manifest.get("routines", [])
    for routine in setup["routines"]:
        if routine["mode"] == "manual":
            continue
        name = routine["id"]
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name) or name == "heartbeat":
            raise ValueError("Invalid delegated routine ID")
        file = f"routines/{name}.md"
        if sum(row.get("id") == name and row.get("file") == file for row in manifest_entries) != 1:
            raise ValueError(f"Restore the manifest entry for {name}")
        hashes = []
        for filename in [file, *(f".agents/skills/{skill}/SKILL.md" for skill in routine["skills"])]:
            path = bot / filename
            if path.resolve() != path or not path.is_file():
                raise ValueError(f"Restore {filename}")
            hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
        routines.append(dict(routine, file=file, files=hashes))
    if not routines:
        raise ValueError("A delegated heartbeat needs scheduled or event-driven work")
    # Include the approved sources and capabilities in the identity. An edit needs a new review.
    definition = [config, routines, manifest["approved_sources"], manifest["capabilities"],
                  manifest["max_delegation_depth"], setup["approval"]]
    revision = hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()
    return dict(config, revision=revision, routines=routines)


def commands(sub):
    queue = sub.add_parser("schedule", help="Manage delegated heartbeat occurrences")
    ops = queue.add_subparsers(dest="operation", required=True)
    approve = ops.add_parser("bind", help="Record an independently approved and reviewed native heartbeat")
    approve.add_argument("--automation", type=ledger.identifier, required=True)
    for field in ("project", "chat", "plan", "approval"):
        approve.add_argument("--" + field, required=True)
    ops.add_parser("status")
    event = ops.add_parser("ready", help="Record readiness for one stable event")
    event.add_argument("routine", type=ledger.identifier)
    event.add_argument("event", type=ledger.identifier)
    event.add_argument("--evidence", type=ledger.prose, required=True)
    tick = ops.add_parser("tick")
    tick.add_argument("--project", required=True)
    tick.add_argument("--chat", required=True)
    tick.add_argument("--automation", type=ledger.identifier, required=True)
    for action in ("bind-worker", "unconfirmed", "terminal", "start", "finish", "review"):
        step = ops.add_parser(action)
        step.add_argument("id")
        if action in ("bind-worker", "terminal"):
            step.add_argument("worker")
        if action == "terminal":
            step.add_argument("turn", type=ledger.identifier)
            step.add_argument("status", choices=("completed", "failed", "interrupted"))
        if action in ("bind-worker", "unconfirmed", "start", "finish"):
            step.add_argument("token")
        if action in ("finish", "review"):
            step.add_argument("--evidence", type=ledger.prose, required=True)
            step.add_argument("--decision", required=True, choices=(
                ("done", "review") if action == "finish" else ("done", "retry", "cancel")))
        if action == "review":
            step.add_argument("--revision", type=int, required=True)
    state = sub.add_parser("state", help="Read and acknowledge the primary chat's durable state")
    actions = state.add_subparsers(dest="operation", required=True)
    snapshot = actions.add_parser("snapshot")
    snapshot.add_argument("--chat", required=True)
    snapshot.add_argument("--after", type=int)
    ack = actions.add_parser("ack")
    ack.add_argument("--chat", required=True)
    ack.add_argument("--revision", type=int, required=True)


def current_revision(db):
    return db.execute("SELECT coalesce(max(revision),0) FROM schedule_updates").fetchone()[0]


def primary_state(db, args, manifest):
    if not THREAD.fullmatch(args.chat) or args.chat != manifest.get("primary_thread"):
        raise ValueError("Use the registered primary chat")
    current = current_revision(db)
    row = db.execute("SELECT revision FROM schedule_ack WHERE chat=?", (args.chat,)).fetchone()
    acknowledged = row["revision"] if row else 0
    if args.operation == "ack":
        seen = db.execute("SELECT revision FROM schedule_seen WHERE chat=?", (args.chat,)).fetchone()
        if args.revision != current or not seen or seen["revision"] != current:
            raise ValueError("State revision changed or was not observed. Reload the primary snapshot")
        db.execute("""INSERT INTO schedule_ack VALUES (?,?) ON CONFLICT(chat)
                   DO UPDATE SET revision=excluded.revision""", (args.chat, current))
        return {"acknowledged": current}
    after = acknowledged if args.after is None else args.after
    if not 0 <= after <= current:
        raise ValueError("Invalid state update cursor")
    db.execute("""INSERT INTO schedule_seen VALUES (?,?) ON CONFLICT(chat)
               DO UPDATE SET revision=excluded.revision""", (args.chat, current))
    changes = [dict(row) for row in db.execute(
        "SELECT * FROM schedule_updates WHERE revision>? ORDER BY revision LIMIT 20", (after,))]
    cursor = changes[-1]["revision"] if changes and changes[-1]["revision"] < current else None
    occurrences = [dict(row) for row in db.execute("""SELECT id,routine,due,event,evidence,state,attempt,worker,receipt
        FROM schedule_occurrences ORDER BY state='review' DESC,changed DESC,id LIMIT 20""")]
    return {"revision": current, "acknowledged": acknowledged, "pending": changes, "next_after": cursor,
            "occurrences": occurrences, **ledger.summary(db)}


def stamp():
    return datetime.now(timezone.utc).timestamp()


def in_window(value, local):
    minute = local.hour * 60 + local.minute
    return (DAYS[local.weekday()] in value["days"]
            and local_time(value["start"]) <= minute < local_time(value["end"], end=True))


def slots(rule, zone, start, end):
    """Use local wall time. Skip nonexistent times and choose the first fold on fallback."""
    date = datetime.fromtimestamp(start, zone).date()
    last = datetime.fromtimestamp(end, zone).date()
    bound = rule["window"]
    while date <= last:
        if DAYS[date.weekday()] in bound["days"]:
            midnight = datetime(date.year, date.month, date.day, tzinfo=zone)
            for minute in range(local_time(bound["start"]), local_time(bound["end"], end=True), rule["every_minutes"]):
                local = midnight + timedelta(minutes=minute)
                slot = local.timestamp()
                if start <= slot <= end and datetime.fromtimestamp(slot, zone) == local:
                    yield slot
        date += timedelta(days=1)


def enqueue(db, revision, routine, due, now, *, event=None, evidence=None):
    identity = json.dumps([routine, event if event is not None else due])
    occurrence = hashlib.sha256(identity.encode()).hexdigest()[:32]
    inserted = db.execute("""INSERT OR IGNORE INTO schedule_occurrences
        (id,plan,routine,due,event,evidence,state,changed) VALUES (?,?,?,?,?,?,'ready',?)""",
        (occurrence, revision, routine, due, event, evidence, now))
    return occurrence, bool(inserted.rowcount)


def tick(db, config, binding, now):
    zone = ZoneInfo(config["timezone"])
    lower = max(binding["approved_at"], now - config["catch_up_hours"] * 3600)
    revision = config["revision"]
    first_tick = db.execute("UPDATE schedule_binding SET first_tick=? WHERE slot=1 AND first_tick IS NULL",
                            (now,)).rowcount > 0
    db.execute("""UPDATE schedule_occurrences SET state='expired',changed=?
        WHERE plan<>? AND state='ready'""", (now, revision))
    db.execute("""UPDATE schedule_occurrences SET state='expired',changed=?
        WHERE plan=? AND state='ready' AND event IS NULL AND due<?""", (now, revision, lower))
    for routine in config["routines"]:
        if routine["mode"] == "scheduled":
            ready = db.execute("""SELECT count(*) FROM schedule_occurrences
                WHERE plan=? AND state='ready' AND routine=?""", (revision, routine["id"])).fetchone()[0]
            for due in slots(routine["timing"], zone, lower, now):
                if ready >= LIMIT:
                    break
                if enqueue(db, revision, routine["id"], due, now)[1]:
                    ready += 1
    unconfirmed = [row["id"] for row in db.execute("""UPDATE schedule_occurrences
        SET state='review',changed=?,receipt='Native launch outcome unconfirmed'
        WHERE state IN ('launching','started') AND worker IS NULL AND changed<? RETURNING id""",
        (now, now - 3600))]
    workers = [dict(row, host="local") for row in db.execute("""SELECT id,worker FROM schedule_occurrences
        WHERE worker IS NOT NULL AND state IN ('launching','started')
        ORDER BY changed,id LIMIT 10""")]
    work = []
    if in_window(config["window"], datetime.fromtimestamp(now, zone)):
        busy = db.execute("""SELECT count(*) FROM schedule_occurrences
            WHERE state IN ('launching','started')""").fetchone()[0]
        routines = {routine["id"]: routine for routine in config["routines"]}
        for row in db.execute("""SELECT id,routine FROM (
            SELECT id,routine,due,row_number() OVER (PARTITION BY routine ORDER BY due,id) AS position
            FROM schedule_occurrences AS ready WHERE plan=? AND state='ready' AND due<=?
            AND NOT EXISTS (SELECT 1 FROM schedule_occurrences AS other WHERE other.routine=ready.routine
                            AND other.state IN ('launching','started','review'))
            ) WHERE position=1 ORDER BY due,id LIMIT ?""", (revision, now, max(0, LIMIT - busy))).fetchall():
            token = secrets.token_hex(16)
            db.execute("""UPDATE schedule_occurrences SET token=?,state='launching',
                       attempt=attempt+1,changed=? WHERE id=?""", (token, now, row["id"]))
            work.append(dict(row, token=token, file=routines[row["routine"]]["file"]))
    return {"work": work, "workers": workers, "first_tick": first_tick, "unconfirmed": unconfirmed}


def change_occurrence(db, args, config, now):
    if not ID.fullmatch(args.id):
        raise ValueError("Invalid occurrence ID")
    row = db.execute("SELECT * FROM schedule_occurrences WHERE id=?", (args.id,)).fetchone()
    action = args.operation
    old_plan = bool(row and row["plan"] != config["revision"])
    if not row or (old_plan and action not in {"terminal", "review", "finish"}):
        raise ValueError("Occurrence is outside the active heartbeat plan")
    if old_plan and action == "review" and args.decision == "retry":
        raise ValueError("A superseded occurrence cannot retry")
    if hasattr(args, "token") and (not ID.fullmatch(args.token) or args.token != row["token"]):
        raise ValueError("Occurrence claim changed")
    if hasattr(args, "worker") and not THREAD.fullmatch(args.worker):
        raise ValueError("Invalid worker chat")
    state, worker, receipt = row["state"], row["worker"], row["receipt"]
    if action == "bind-worker" and state in {"launching", "started", "done", "review"} and worker in (None, args.worker):
        worker = args.worker
    elif action == "unconfirmed" and state == "launching" and worker is None:
        state, receipt = "review", "Native launch outcome unconfirmed"
    elif action == "terminal" and worker == args.worker and state in {"launching", "started"}:
        retry = not old_plan and state == "launching" and args.status == "interrupted" and row["attempt"] < ATTEMPTS
        state, receipt = ("ready" if retry else "review"), f"Native worker {worker} turn {args.turn} {args.status} without a receipt"
        if retry:
            worker = None
    elif action == "start":
        if state != "launching":
            return {"start": False}
        state = "started"
    elif action == "finish" and state == "started":
        state, receipt = args.decision, args.evidence
    elif action == "finish" and (state, receipt) == (args.decision, args.evidence):
        return {"state": state}
    elif action == "review" and state == "review":
        state = {"retry": "ready", "cancel": "cancelled", "done": "done"}[args.decision]
        receipt = args.evidence
        if state == "ready":
            worker = None
    else:
        return {"state": state}
    if (state, worker, receipt) != (row["state"], row["worker"], row["receipt"]):
        db.execute("""UPDATE schedule_occurrences SET state=?,worker=?,receipt=?,changed=?,
                   token=CASE WHEN ?='ready' THEN NULL ELSE token END WHERE id=?""",
                   (state, worker, receipt, now, state, args.id))
    if action == "start":
        return {"start": True, "scope": config["scope"], "routine": row["routine"], "event": row["event"],
                "evidence": row["evidence"]}
    return {"state": state}


def run(db, args, bot):
    manifest = json.loads((bot / "bot.json").read_text(encoding="utf-8"))
    if args.command == "state":
        return primary_state(db, args, manifest)
    config = plan(bot, manifest)
    action = args.operation
    if config is None:
        if action == "tick":
            return None
        raise ValueError("No delegated heartbeat plan")
    if manifest.get("lifecycle") != "active" or manifest.get("max_delegation_depth", 0) < 1:
        raise ValueError("Delegated heartbeat requires an active bot with authorized delegation")
    now = stamp()
    chat = manifest["primary_thread"]
    binding = db.execute("SELECT * FROM schedule_binding WHERE slot=1").fetchone()
    if action == "status":
        if binding and (binding["plan"], binding["chat"]) == (config["revision"], chat):
            return {key: binding[key] for key in ("automation", "project", "chat", "plan", "first_tick")}
        return {}
    if action == "bind":
        if not THREAD.fullmatch(args.chat) or args.chat != chat or args.plan != config["revision"]:
            raise ValueError("Schedule approval must match the active primary chat and plan revision")
        if binding and (binding["automation"], binding["project"]) != (args.automation, args.project):
            raise ValueError("A different native schedule or project is already bound")
        db.execute("""INSERT INTO schedule_binding VALUES (1,?,?,?,?,?,?,NULL)
            ON CONFLICT(slot) DO UPDATE SET plan=excluded.plan,chat=excluded.chat,
            approved_at=excluded.approved_at,approval=excluded.approval,first_tick=NULL
            WHERE plan IS NOT excluded.plan OR chat IS NOT excluded.chat""",
            (args.plan, chat, ledger.prose(args.automation), ledger.prose(args.project), now, ledger.prose(args.approval)))
        return {"automation": args.automation, "plan": args.plan}
    if binding is None or (binding["plan"], binding["chat"]) != (config["revision"], chat):
        if action == "tick":
            return None
        raise ValueError("Approve and verify the native heartbeat for this plan first")
    if action == "tick":
        if (args.project, args.chat, args.automation) != (binding["project"], chat, binding["automation"]):
            raise ValueError("Native schedule, project or primary chat does not match the approved binding")
        return tick(db, config, binding, now)
    if action == "ready":
        if not any(routine["id"] == args.routine and routine["mode"] == "event" for routine in config["routines"]):
            raise ValueError("Event is outside the approved routine plan")
        occurrence, _ = enqueue(db, config["revision"], args.routine, now, now, event=args.event, evidence=args.evidence)
        return {"id": occurrence}
    if action == "bind-worker" and args.worker == chat:
        raise ValueError("The primary chat cannot own an occurrence")
    if action == "review":
        seen = db.execute("SELECT revision FROM schedule_seen WHERE chat=?", (chat,)).fetchone()
        if args.revision != current_revision(db) or not seen or seen["revision"] != args.revision:
            raise ValueError("State revision changed or was not observed. Reload the primary snapshot")
    return change_occurrence(db, args, config, now)


def wakeup(db, bot, manifest):
    if manifest.get("lifecycle") != "active" or manifest.get("max_delegation_depth", 0) < 1:
        return None
    config = plan(bot, manifest)
    binding = db.execute("SELECT * FROM schedule_binding WHERE slot=1").fetchone()
    if not binding or (binding["plan"], binding["chat"]) != (config["revision"], manifest["primary_thread"]):
        return None
    return {"dispatcher": {key: binding[key] for key in ("chat", "project", "automation")}}
