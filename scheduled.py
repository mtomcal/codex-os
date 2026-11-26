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
            approval TEXT NOT NULL, first_tick REAL, first_usable_tick REAL,
            generation TEXT NOT NULL, verified_turn TEXT)""",
        """CREATE TABLE IF NOT EXISTS schedule_tick_candidates (completed_at REAL PRIMARY KEY)""",
        """CREATE TABLE IF NOT EXISTS schedule_occurrences (
            id TEXT PRIMARY KEY, plan TEXT NOT NULL, routine TEXT NOT NULL, due REAL NOT NULL,
            event TEXT, evidence TEXT, state TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
            token TEXT, worker TEXT, changed REAL NOT NULL, receipt TEXT)""",
        """CREATE INDEX IF NOT EXISTS schedule_ready ON schedule_occurrences (plan,state,due,id)""",
        """CREATE TABLE IF NOT EXISTS schedule_updates (
            revision INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, subject TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS schedule_ack (
            chat TEXT PRIMARY KEY, revision INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS schedule_observation (
            chat TEXT PRIMARY KEY, revision INTEGER NOT NULL, through_revision INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS schedule_attempts (
            id TEXT NOT NULL REFERENCES schedule_occurrences(id), attempt INTEGER NOT NULL,
            token TEXT NOT NULL, project TEXT NOT NULL, chat TEXT NOT NULL, host TEXT NOT NULL,
            worker TEXT UNIQUE, client TEXT UNIQUE, turn TEXT, terminal TEXT,
            outcome TEXT, reviewed TEXT, delivered TEXT, archived REAL, checked REAL, launch_requested REAL,
            PRIMARY KEY(id,attempt))""",
    ):
        db.execute(ddl)
    binding_columns = {row["name"] for row in db.execute("PRAGMA table_info(schedule_binding)")}
    if "first_usable_tick" not in binding_columns:
        db.execute("ALTER TABLE schedule_binding ADD COLUMN first_usable_tick REAL")
        # The previous schema retained only the current claim. Import the identity it still has.
        db.execute("""INSERT INTO schedule_attempts (id,attempt,token,project,chat,host,worker,outcome)
            SELECT o.id,o.attempt,o.token,b.project,b.chat,'local',o.worker,o.receipt
            FROM schedule_occurrences o CROSS JOIN schedule_binding b
            WHERE o.token IS NOT NULL""")
    if "generation" not in binding_columns:
        db.execute("ALTER TABLE schedule_binding ADD COLUMN generation TEXT")
        db.execute("ALTER TABLE schedule_binding ADD COLUMN verified_turn TEXT")
        db.execute("UPDATE schedule_binding SET generation=lower(hex(randomblob(16)))")
    attempt_columns = {row["name"] for row in db.execute("PRAGMA table_info(schedule_attempts)")}
    if "launch_requested" not in attempt_columns:
        db.execute("ALTER TABLE schedule_attempts ADD COLUMN launch_requested REAL")
    if "launch_requested" not in attempt_columns or "first_usable_tick" not in binding_columns:
        # A legacy claim may already have reached the native service.
        db.execute("""UPDATE schedule_attempts SET launch_requested=(
            SELECT changed FROM schedule_occurrences WHERE id=schedule_attempts.id)
            WHERE launch_requested IS NULL""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS revision_schedule_first_usable_tick
        AFTER UPDATE OF first_usable_tick ON schedule_binding
        WHEN new.first_usable_tick IS NOT NULL AND old.first_usable_tick IS NULL
        BEGIN INSERT INTO schedule_updates (kind,subject) VALUES ('heartbeat', new.automation); END""")
    for table, kind, subject, when in (
        ("schedule_occurrences", "occurrence", "new.id", "OLD.state IS NOT NEW.state OR OLD.receipt IS NOT NEW.receipt"),
        ("schedule_binding", "heartbeat", "new.automation", "OLD.plan IS NOT NEW.plan OR OLD.chat IS NOT NEW.chat OR OLD.first_tick IS NOT NEW.first_tick"),
        ("schedule_attempts", "attempt", "new.id", """OLD.worker IS NOT NEW.worker OR
            OLD.client IS NOT NEW.client OR OLD.terminal IS NOT NEW.terminal OR
            OLD.reviewed IS NOT NEW.reviewed OR OLD.delivered IS NOT NEW.delivered OR OLD.archived IS NOT NEW.archived"""),
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
    attempts = ops.add_parser("attempts", help="Inspect retained attempts for one occurrence")
    attempts.add_argument("id")
    event = ops.add_parser("ready", help="Record readiness for one stable event")
    event.add_argument("routine", type=ledger.identifier)
    event.add_argument("event", type=ledger.identifier)
    event.add_argument("--evidence", type=ledger.prose, required=True)
    for action in ("tick", "complete-tick"):
        tick = ops.add_parser(action)
        tick.add_argument("--project", required=True)
        tick.add_argument("--chat", required=True)
        tick.add_argument("--automation", type=ledger.identifier, required=True)
        if action == "complete-tick":
            tick.add_argument("--plan", required=True)
            tick.add_argument("--generation", required=True)
    confirm = ops.add_parser("confirm-tick", help="Record the native turn verified by onboarding")
    confirm.add_argument("--generation", required=True)
    confirm.add_argument("--turn", type=ledger.identifier, required=True)
    confirm.add_argument("--started", type=int, required=True)
    confirm.add_argument("--completed", type=int, required=True)
    for action in ("request-worker", "bind-worker", "queued", "launch-overdue", "terminal",
                   "start", "finish", "review", "review-attempt", "delivered-attempt", "archived-attempt"):
        step = ops.add_parser(action)
        step.add_argument("id")
        if action in ("bind-worker", "terminal", "review-attempt", "delivered-attempt", "archived-attempt"):
            step.add_argument("worker")
        if action == "queued":
            step.add_argument("--client", type=ledger.prose, required=True)
        if action in ("terminal", "review-attempt", "delivered-attempt", "archived-attempt"):
            step.add_argument("attempt", type=int)
        if action == "terminal":
            step.add_argument("turn", type=ledger.identifier)
            step.add_argument("status", choices=("completed", "failed", "interrupted"))
        if action in ("request-worker", "bind-worker", "queued", "launch-overdue", "start", "finish"):
            step.add_argument("token")
        if action in ("finish", "review", "review-attempt", "delivered-attempt"):
            step.add_argument("--evidence", type=ledger.prose, required=True)
        if action in ("finish", "review"):
            step.add_argument("--decision", required=True, choices=(
                ("done", "review") if action == "finish" else ("done", "retry", "cancel")))
        if action == "review":
            step.add_argument("--revision", type=int, required=True)
    state = sub.add_parser("state", help="Read and acknowledge the primary chat's durable state")
    actions = state.add_subparsers(dest="operation", required=True)
    snapshot = actions.add_parser("snapshot")
    snapshot.add_argument("--chat", required=True)
    snapshot.add_argument("--after", type=int)
    snapshot.add_argument("--revision", type=int)
    recovery = actions.add_parser("recover", help="Reload the current bot context at ordinary turn entry")
    recovery.add_argument("--chat", required=True)
    recovery.add_argument("--routine", type=ledger.identifier)
    recovery.set_defaults(after=None, revision=None)
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
        require_observed(db, args.chat, args.revision)
        db.execute("""INSERT INTO schedule_ack VALUES (?,?) ON CONFLICT(chat)
                   DO UPDATE SET revision=excluded.revision""", (args.chat, current))
        return {"acknowledged": current}
    after = acknowledged if args.after is None else args.after
    if args.after is not None:
        observed = observation(db, args.chat)
        if (args.revision != current or not acknowledged < after < current
                or observed is None or tuple(observed) != (current, after)):
            raise ValueError("State cursor changed or skipped a page. Reload the primary snapshot")
    elif args.revision is not None:
        raise ValueError("Use a revision only when continuing a snapshot")
    changes = [dict(row) for row in db.execute(
        "SELECT * FROM schedule_updates WHERE revision>? ORDER BY revision LIMIT 20", (after,))]
    cursor = changes[-1]["revision"] if changes and changes[-1]["revision"] < current else None
    db.execute("""INSERT INTO schedule_observation VALUES (?,?,?) ON CONFLICT(chat)
               DO UPDATE SET revision=excluded.revision,through_revision=excluded.through_revision""",
               (args.chat, current, current if cursor is None else cursor))
    occurrences = [dict(row) for row in db.execute("""SELECT id,routine,due,event,evidence,state,attempt,worker,receipt
        FROM schedule_occurrences ORDER BY state='review' DESC,changed DESC,id LIMIT 20""")]
    attempts = attempt_history(db, None)
    return {"revision": current, "acknowledged": acknowledged, "pending": changes, "next_after": cursor,
            "occurrences": occurrences, "attempts": attempts, **ledger.summary(db)}


def attempt_history(db, occurrence):
    fields = "id,attempt,worker,client,host,project,turn,terminal,outcome,reviewed,delivered,archived,launch_requested"
    if occurrence is not None:
        if not ID.fullmatch(occurrence):
            raise ValueError("Invalid occurrence ID")
        query, params = f"SELECT {fields} FROM schedule_attempts WHERE id=? ORDER BY attempt", (occurrence,)
    else:
        query, params = f"""SELECT {fields} FROM schedule_attempts WHERE archived IS NULL
            ORDER BY rowid DESC LIMIT 20""", ()
    return [dict(row) for row in db.execute(query, params)]


def observation(db, chat):
    return db.execute("SELECT revision,through_revision FROM schedule_observation WHERE chat=?", (chat,)).fetchone()


def require_observed(db, chat, revision):
    seen = observation(db, chat)
    if revision != current_revision(db) or seen is None or tuple(seen) != (revision, revision):
        raise ValueError("State revision changed or was not observed. Reload the primary snapshot")


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


def carry_events(db, config, now):
    for routine in config["routines"]:
        if routine["mode"] == "event":
            db.execute("""UPDATE schedule_occurrences SET plan=?,state='ready',changed=?
                WHERE plan<>? AND routine=? AND event IS NOT NULL AND state IN ('ready','expired')
                AND NOT EXISTS (SELECT 1 FROM schedule_attempts a
                    WHERE a.id=schedule_occurrences.id AND a.launch_requested IS NOT NULL)""",
                (config["revision"], now, config["revision"], routine["id"]))


def tick(db, config, binding, now):
    zone = ZoneInfo(config["timezone"])
    lower = max(binding["approved_at"], now - config["catch_up_hours"] * 3600)
    revision = config["revision"]
    carry_events(db, config, now)
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
    recover = [dict(row) for row in db.execute("""SELECT a.id,a.attempt,a.token,a.client,a.chat,a.project,a.host,
        o.routine,o.state='launching' AND a.launch_requested<? AS overdue
        FROM schedule_attempts a JOIN schedule_occurrences o USING(id)
        WHERE a.worker IS NULL AND a.launch_requested IS NOT NULL AND a.attempt=o.attempt
        AND o.state IN ('launching','started','review','done','cancelled')
        ORDER BY a.checked,a.id LIMIT 10""", (now - 3600,))]
    workers = [dict(row) for row in db.execute("""SELECT id,attempt,worker,host FROM schedule_attempts
        WHERE worker IS NOT NULL AND terminal IS NULL ORDER BY checked,id,attempt LIMIT 10""")]
    db.executemany("UPDATE schedule_attempts SET checked=? WHERE id=? AND attempt=?",
                   ((now, job["id"], job["attempt"]) for job in [*recover, *workers]))
    archives = [dict(row) for row in db.execute("""SELECT id,attempt,worker,host,turn,terminal FROM schedule_attempts
        WHERE delivered IS NOT NULL AND terminal IS NOT NULL AND archived IS NULL
        ORDER BY checked,id,attempt LIMIT 10""")]
    db.executemany("UPDATE schedule_attempts SET checked=? WHERE id=? AND attempt=?",
                   ((now, job["id"], job["attempt"]) for job in archives))
    work = []
    if in_window(config["window"], datetime.fromtimestamp(now, zone)):
        busy = db.execute("""SELECT count(*) FROM schedule_occurrences
            WHERE state IN ('launching','started')""").fetchone()[0]
        routines = {routine["id"]: routine for routine in config["routines"]}
        for row in db.execute("""SELECT id FROM (
            SELECT id,routine,due,row_number() OVER (PARTITION BY routine ORDER BY due,id) AS position
            FROM schedule_occurrences AS ready WHERE plan=? AND state='ready' AND due<=?
            AND NOT EXISTS (SELECT 1 FROM schedule_occurrences AS other WHERE other.routine=ready.routine
                            AND other.state IN ('launching','started','review'))
            ) WHERE position=1 ORDER BY due,id LIMIT ?""", (revision, now, max(0, LIMIT - busy))).fetchall():
            token = secrets.token_hex(16)
            db.execute("""UPDATE schedule_occurrences SET token=?,state='launching',
                       attempt=attempt+1,changed=? WHERE id=?""", (token, now, row["id"]))
            db.execute("""INSERT INTO schedule_attempts (id,attempt,token,project,chat,host)
                SELECT id,attempt,token,?,?,'local' FROM schedule_occurrences WHERE id=?""",
                (binding["project"], binding["chat"], row["id"]))
        unattempted = db.execute("""SELECT o.id,o.routine,a.attempt,a.token
            FROM schedule_attempts a JOIN schedule_occurrences o USING(id)
            WHERE o.plan=? AND a.chat=? AND o.state='launching' AND a.attempt=o.attempt
                AND a.launch_requested IS NULL ORDER BY o.due,o.id LIMIT ?""", (revision, binding["chat"], LIMIT))
        work = [dict(job, file=routines[job["routine"]]["file"]) for job in unattempted]
    return {"work": work, "workers": workers, "recover": recover, "archives": archives, "plan": revision,
            "generation": binding["generation"], "needs_first_tick": binding["verified_turn"] is None}


def attempt_record(db, args, row, old_plan, now):
    attempt = db.execute("SELECT * FROM schedule_attempts WHERE id=? AND attempt=?",
                         (args.id, args.attempt)).fetchone()
    if attempt is None or attempt["worker"] != args.worker:
        raise ValueError("Native worker does not match the recorded attempt")
    action = args.operation
    if action == "terminal":
        if attempt["terminal"]:
            return {"state": row["state"]}
        state, receipt = row["state"], row["receipt"]
        if row["attempt"] == args.attempt and state in {"launching", "started"}:
            retry = (not old_plan and state == "launching" and args.status == "interrupted"
                     and args.attempt < ATTEMPTS)
            state = "ready" if retry else "review"
            receipt = f"Native worker {args.worker} turn {args.turn} {args.status} without a receipt"
            save_occurrence(db, row, now, state, receipt, worker=None if retry else args.worker)
        db.execute("""UPDATE schedule_attempts SET turn=?,terminal=?,outcome=coalesce(outcome,?)
            WHERE id=? AND attempt=?""", (args.turn, args.status, receipt, args.id, args.attempt))
        return {"state": state}
    if not attempt["terminal"] or (row["attempt"] == args.attempt and row["state"] in {"launching", "started", "review"}):
        raise ValueError("Confirm the worker ended and resolve any occurrence under review first")
    if action == "review-attempt":
        field, value = "reviewed", args.evidence
    elif action == "delivered-attempt" and attempt["reviewed"]:
        field, value = "delivered", args.evidence
    elif action == "archived-attempt" and attempt["reviewed"] and attempt["delivered"]:
        field, value = "archived", now
    else:
        raise ValueError("Record attempt review and delivery before cleanup")
    db.execute(f"""UPDATE schedule_attempts SET {field}=? WHERE id=? AND attempt=? AND {field} IS NULL""",
               (value, args.id, args.attempt))
    return {"state": row["state"]}


def save_occurrence(db, row, now, state, receipt, *, worker):
    db.execute("""UPDATE schedule_occurrences SET state=?,worker=?,receipt=?,changed=?,
        token=CASE WHEN ?='ready' THEN NULL ELSE token END WHERE id=?""",
        (state, worker, receipt, now, state, row["id"]))


def change_occurrence(db, args, config, now):
    if not ID.fullmatch(args.id):
        raise ValueError("Invalid occurrence ID")
    row = db.execute("SELECT * FROM schedule_occurrences WHERE id=?", (args.id,)).fetchone()
    if not row:
        raise ValueError("Unknown occurrence")
    action = args.operation
    old_plan = row["plan"] != config["revision"]
    if hasattr(args, "worker") and not THREAD.fullmatch(args.worker):
        raise ValueError("Invalid worker chat")
    if hasattr(args, "attempt"):
        return attempt_record(db, args, row, old_plan, now)
    if old_plan and action not in {"bind-worker", "queued", "launch-overdue", "review", "finish"}:
        raise ValueError("Occurrence is outside the active heartbeat plan")
    if hasattr(args, "token") and (not ID.fullmatch(args.token) or args.token != row["token"]):
        raise ValueError("Occurrence claim changed")
    state, worker, receipt = row["state"], row["worker"], row["receipt"]
    if action == "request-worker":
        requested = db.execute("""UPDATE schedule_attempts SET launch_requested=?
            WHERE id=? AND attempt=? AND launch_requested IS NULL AND ?='launching'""",
            (now, args.id, row["attempt"], state))
        return {"launch": bool(requested.rowcount)}
    if action in {"bind-worker", "queued"} and state in {"launching", "started", "done", "review", "cancelled"}:
        attempt = db.execute("SELECT * FROM schedule_attempts WHERE id=? AND attempt=?",
                             (args.id, row["attempt"])).fetchone()
        if action == "queued":
            if attempt["client"] not in (None, args.client):
                raise ValueError("Native launch reference changed")
            db.execute("UPDATE schedule_attempts SET client=?,launch_requested=coalesce(launch_requested,?) "
                       "WHERE id=? AND attempt=?", (args.client, now, args.id, row["attempt"]))
        else:
            if worker not in (None, args.worker) or args.worker == attempt["chat"]:
                raise ValueError("Native worker identity changed")
            db.execute("UPDATE schedule_attempts SET worker=?,launch_requested=coalesce(launch_requested,?) "
                       "WHERE id=? AND attempt=?", (args.worker, now, args.id, row["attempt"]))
            if worker != args.worker:
                save_occurrence(db, row, now, state, receipt, worker=args.worker)
        return {"state": state}
    if action == "launch-overdue" and state == "launching" and worker is None:
        overdue = db.execute("""SELECT 1 FROM schedule_attempts
            WHERE id=? AND attempt=? AND launch_requested<?""", (args.id, row["attempt"], now - 3600)).fetchone()
        if overdue:
            save_occurrence(db, row, now, "review", "Native launch outcome unconfirmed", worker=None)
            return {"state": "review"}
    if action == "start":
        if state != "launching":
            return {"start": False}
        db.execute("""UPDATE schedule_attempts SET launch_requested=coalesce(launch_requested,?)
            WHERE id=? AND attempt=?""", (now, args.id, row["attempt"]))
        save_occurrence(db, row, now, "started", receipt, worker=worker)
        return {"start": True, "scope": config["scope"], "routine": row["routine"], "event": row["event"],
                "evidence": row["evidence"]}
    if action == "finish" and state == "started":
        state, receipt = args.decision, args.evidence
        db.execute("UPDATE schedule_attempts SET outcome=? WHERE id=? AND attempt=?",
                   (receipt, args.id, row["attempt"]))
        save_occurrence(db, row, now, state, receipt, worker=worker)
    elif action == "review" and state == "review":
        if args.decision == "retry":
            terminal = db.execute("SELECT terminal FROM schedule_attempts WHERE id=? AND attempt=?",
                                  (args.id, row["attempt"])).fetchone()
            if old_plan or not terminal or not terminal["terminal"]:
                raise ValueError("Retry requires a current plan and a confirmed terminal worker")
            worker = None
        state = {"retry": "ready", "cancel": "cancelled", "done": "done"}[args.decision]
        save_occurrence(db, row, now, state, args.evidence, worker=worker)
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
    if action == "attempts":
        return attempt_history(db, args.id)
    if action == "status":
        if binding and (binding["plan"], binding["chat"]) == (config["revision"], chat):
            return {key: binding[key] for key in ("automation", "project", "chat", "plan",
                                                   "first_tick", "first_usable_tick", "generation", "verified_turn")}
        return {}
    if action == "bind":
        if not THREAD.fullmatch(args.chat) or args.chat != chat or args.plan != config["revision"]:
            raise ValueError("Schedule approval must match the active primary chat and plan revision")
        if binding and (binding["automation"], binding["project"]) != (args.automation, args.project):
            raise ValueError("A different native schedule or project is already bound")
        saved = db.execute("""INSERT INTO schedule_binding
            (slot,plan,chat,automation,project,approved_at,approval,generation) VALUES (1,?,?,?,?,?,?,?)
            ON CONFLICT(slot) DO UPDATE SET plan=excluded.plan,chat=excluded.chat,
            approved_at=excluded.approved_at,approval=excluded.approval,generation=excluded.generation,
            first_tick=NULL,first_usable_tick=NULL,verified_turn=NULL
            WHERE plan IS NOT excluded.plan OR chat IS NOT excluded.chat""",
            (args.plan, chat, ledger.prose(args.automation), ledger.prose(args.project), now,
             ledger.prose(args.approval), secrets.token_hex(16)))
        if saved.rowcount:
            db.execute("DELETE FROM schedule_tick_candidates")
            db.execute("""UPDATE schedule_occurrences SET state='ready',token=NULL,changed=?
                WHERE state='launching' AND EXISTS (SELECT 1 FROM schedule_attempts a
                    WHERE a.id=schedule_occurrences.id AND a.attempt=schedule_occurrences.attempt
                    AND a.launch_requested IS NULL AND (schedule_occurrences.plan<>? OR a.chat<>?))""",
                (now, args.plan, chat))
        return {"automation": args.automation, "plan": args.plan}
    if binding is None or (binding["plan"], binding["chat"]) != (config["revision"], chat):
        if action == "tick":
            return None
        raise ValueError("Approve and verify the native heartbeat for this plan first")
    if action == "confirm-tick":
        if args.generation != binding["generation"] or args.started > args.completed:
            return {"verified": False}
        if binding["verified_turn"] is not None:
            return {"verified": args.turn == binding["verified_turn"]}
        # Native history reports whole seconds. Retain every candidate until one turn is verified.
        start, end = args.started, args.completed + 1
        candidate = db.execute("""SELECT 1 FROM schedule_tick_candidates
            WHERE completed_at>=? AND completed_at<? LIMIT 1""", (start, end)).fetchone()
        if not candidate and not any(
            tick is not None and start <= tick < end
            for tick in (binding["first_tick"], binding["first_usable_tick"])
        ):
            return {"verified": False}
        db.execute("UPDATE schedule_binding SET verified_turn=? WHERE slot=1", (args.turn,))
        db.execute("DELETE FROM schedule_tick_candidates")
        return {"verified": True}
    if action in {"tick", "complete-tick"}:
        if (args.project, args.chat, args.automation) != (binding["project"], chat, binding["automation"]):
            raise ValueError("Native schedule, project or primary chat does not match the approved binding")
        if action == "tick":
            return tick(db, config, binding, now)
        if (args.plan, args.generation) != (binding["plan"], binding["generation"]):
            raise ValueError("The heartbeat binding changed during this tick")
        if binding["verified_turn"] is not None:
            return {"first_tick": False}
        db.execute("INSERT OR IGNORE INTO schedule_tick_candidates VALUES (?)", (now,))
        db.execute("""UPDATE schedule_binding SET first_usable_tick=?
            WHERE slot=1 AND first_usable_tick IS NULL""", (now,))
        return {"first_tick": True}
    if action == "ready":
        if not any(routine["id"] == args.routine and routine["mode"] == "event" for routine in config["routines"]):
            raise ValueError("Event is outside the approved routine plan")
        carry_events(db, config, now)
        occurrence, _ = enqueue(db, config["revision"], args.routine, now, now, event=args.event, evidence=args.evidence)
        return {"id": occurrence}
    if action == "bind-worker" and args.worker == chat:
        raise ValueError("The primary chat cannot own an occurrence")
    if action in {"request-worker", "start"} and db.execute(
        "SELECT 1 FROM schedule_attempts WHERE id=? AND token=? AND chat<>?", (args.id, args.token, chat)
    ).fetchone():
        raise ValueError("Occurrence claim belongs to a previous primary chat")
    if action == "review":
        require_observed(db, chat, args.revision)
    return change_occurrence(db, args, config, now)


def wakeup(db, bot, manifest):
    if manifest.get("lifecycle") != "active" or manifest.get("max_delegation_depth", 0) < 1:
        return None
    config = plan(bot, manifest)
    binding = db.execute("SELECT * FROM schedule_binding WHERE slot=1").fetchone()
    if not binding or (binding["plan"], binding["chat"]) != (config["revision"], manifest["primary_thread"]):
        return None
    return {"dispatcher": {key: binding[key] for key in ("chat", "project", "automation")}}
