"""Transactional work, follow-ups and private memory for one bot."""
import argparse
import json
import re
from datetime import datetime, timezone

import permission_plan
import receipt_store


WORK = {
    "proposed": {"ready", "parked", "unknown"},
    "ready": {"running", "waiting", "blocked", "parked", "unknown"},
    "running": {"completed", "failed", "waiting", "blocked", "parked", "unknown"},
    "waiting": {"running", "ready", "blocked", "parked", "unknown"},
    "blocked": {"ready", "running", "waiting", "parked", "unknown"},
    "parked": {"ready", "proposed"},
    "unknown": {"proposed", "ready", "running", "waiting", "blocked", "parked"},
    "completed": set(),
    "failed": {"ready", "parked"},
}
COMMIT = {
    "open": {"in-progress", "waiting", "blocked", "completed", "cancelled", "parked"},
    "in-progress": {"open", "waiting", "blocked", "completed", "cancelled", "parked"},
    "waiting": {"open", "in-progress", "blocked", "completed", "cancelled", "parked"},
    "blocked": {"open", "in-progress", "waiting", "completed", "cancelled", "parked"},
    "parked": {"open", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}
STATES = {"workload": WORK, "commitment": COMMIT}
INITIAL = {"workload": "proposed", "commitment": "open"}


def now():
    return int(datetime.now(timezone.utc).timestamp())


def instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError
        return int(parsed.timestamp())
    except (ValueError, OverflowError) as exc:
        raise argparse.ArgumentTypeError("use ISO 8601 with a UTC offset") from exc


def identifier(value):
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", value):
        raise argparse.ArgumentTypeError("use a lowercase ID of 1 to 80 letters, digits, dots, underscores or hyphens")
    return value


def prose(value):
    if not value.strip() or len(value) > 4096:
        raise argparse.ArgumentTypeError("enter 1 to 4096 characters")
    return value.strip()


def install(db):
    statements = [
        """CREATE TABLE IF NOT EXISTS ledger_items(
            kind TEXT, id TEXT, title TEXT NOT NULL, objective TEXT NOT NULL, owner TEXT NOT NULL,
            project TEXT, agent TEXT, source TEXT, criteria TEXT NOT NULL, state TEXT NOT NULL,
            origin TEXT, workload TEXT, dependency TEXT, blocker TEXT, milestone TEXT,
            next_action TEXT NOT NULL, human INTEGER NOT NULL DEFAULT 0,
            created INTEGER NOT NULL, updated INTEGER NOT NULL, due INTEGER, review INTEGER,
            revision INTEGER NOT NULL DEFAULT 1, reviewed INTEGER, reminded INTEGER,
            evidence TEXT, PRIMARY KEY(kind,id))""",
        """CREATE TABLE IF NOT EXISTS ledger_history(
            seq INTEGER PRIMARY KEY, kind TEXT, id TEXT, revision INTEGER, at INTEGER,
            state TEXT, evidence TEXT, UNIQUE(kind,id,revision))""",
        """CREATE TABLE IF NOT EXISTS ledger_memory(
            key TEXT, rev INTEGER, content TEXT, category TEXT, source TEXT,
            evidence TEXT, observed INTEGER, verified INTEGER, confidence TEXT,
            expires INTEGER, status TEXT, supersedes INTEGER,
            PRIMARY KEY(key,rev))""",
        """CREATE TABLE IF NOT EXISTS ledger_feedback(
            id TEXT PRIMARY KEY, subject TEXT NOT NULL, outcome TEXT NOT NULL,
            evidence TEXT NOT NULL, created INTEGER NOT NULL, reflected INTEGER)""",
    ]
    for statement in statements:
        db.execute(statement)
    permission_plan.install(db)


def commands(subparsers):
    for kind, states in STATES.items():
        actions = subparsers.add_parser(kind, help=f"Maintain the {kind} registry").add_subparsers(dest="action", required=True)
        actions.add_parser("list", help="Show up to 50 records, including parked and closed work")
        actions.add_parser("show").add_argument("id", type=identifier)
        if kind == "workload":
            permissions = actions.add_parser("permissions", help="Review or record a workload's permission plan")
            permissions.add_argument("id", type=identifier)
            permissions.add_argument("--plan", metavar="JSON")
            permissions.add_argument("--decisions", metavar="JSON")
        add = actions.add_parser("add")
        change = actions.add_parser("update")
        for op in (add, change):
            op.add_argument("id", type=identifier)
            for field in ("title", "objective", "owner", "criteria", "next-action"):
                op.add_argument("--" + field, type=prose, required=(op is add))
            for field in ("origin", "blocker", "milestone", "project", "agent"):
                op.add_argument("--" + field, type=prose)
            op.add_argument("--source", type=identifier, help="Local monitor source ID")
            op.add_argument("--workload", type=identifier, help="Associated workload ID")
            op.add_argument("--dependency", type=identifier, help="Wait until this workload completes")
            op.add_argument("--review", type=instant, help="Suppress review until this time")
            op.add_argument("--due", type=instant)
            op.add_argument("--human", choices=("yes", "no"))
        change.add_argument("--revision", type=int, required=True)
        change.add_argument("--state", choices=states)
        change.add_argument("--clear", action="append", choices=("review", "due", "dependency", "blocker", "workload", "source"), default=[])
        change.add_argument("--receipt", type=identifier, help="Verified run result filename directly under evidence/")
    subparsers.add_parser("strategic", help="Review up to three eligible items")
    evidence = subparsers.add_parser("evidence", help="Archive or retrieve accepted receipt bytes").add_subparsers(
        dest="action", required=True)
    for action in ("archive", "resolve"):
        entry = evidence.add_parser(action)
        entry.add_argument("kind", choices=STATES)
        entry.add_argument("id", type=identifier)
        entry.add_argument("revision", type=int, help="Ledger outcome revision")
        if action == "archive":
            entry.add_argument("--release-hot", action="store_true",
                               help="Release the original hot file after reviewing provenance and pins")
    memory = subparsers.add_parser("memory", help="Maintain source-attributed private knowledge").add_subparsers(dest="action", required=True)
    memory.add_parser("preferences", help="Read current operator preferences at startup")
    memory.add_parser("index", help="Print active private records with source and evidence references")
    ls = memory.add_parser("list")
    ls.add_argument("--all", action="store_true", help="Include archived history")
    ls.add_argument("--key", type=identifier)
    add = memory.add_parser("add")
    add.add_argument("key", type=identifier, help="Stable topic or fact ID")
    add.add_argument("content", type=prose)
    add.add_argument("--source", type=prose, required=True)
    add.add_argument("--evidence", type=prose, required=True)
    add.add_argument("--category", choices=("fact", "lesson", "decision", "episode", "preference"), default="fact")
    add.add_argument("--confidence", choices=("low", "medium", "high"), default="medium")
    add.add_argument("--expires", type=instant)
    resolve = memory.add_parser("resolve", help="Select the supported version of a fact after evidence review")
    resolve.add_argument("key", type=identifier)
    resolve.add_argument("rev", type=int)
    resolve.add_argument("--latest", type=int, required=True, help="Latest known revision for optimistic concurrency")
    resolve.add_argument("--source", type=prose, required=True)
    resolve.add_argument("--evidence", type=prose, required=True, help="Evidence used to resolve the contradiction")
    for operation in (add, resolve):
        operation.add_argument("--quiet", action="store_true", help="Capture during an ordinary turn with operator opt-in")
    fb = subparsers.add_parser("feedback")
    fb.add_argument("id", type=identifier)
    fb.add_argument("--subject", type=prose, required=True)
    fb.add_argument("--outcome", type=prose, required=True)
    fb.add_argument("--evidence", type=prose, required=True)
    subparsers.add_parser("reflect", help="Archive expired facts and review feedback")


def item(db, kind, key):
    row = db.execute("SELECT * FROM ledger_items WHERE kind=? AND id=?", (kind, key)).fetchone()
    if row is None:
        raise ValueError(f"unknown {kind} {key}")
    return dict(row)


def inventory(db, kind):
    return [dict(r) for r in db.execute(
        "SELECT * FROM ledger_items WHERE kind=? ORDER BY updated DESC,id LIMIT 50", (kind,))]


def with_observation(db, record):
    if record["source"]:
        row = db.execute("""SELECT revision,observed,latest,baseline,outcome FROM monitor_sources
                            WHERE id=? AND revision IS NOT NULL""", (record["source"],)).fetchone()
        if row:
            record["observation"] = dict(row)
            for key in ("latest", "baseline"):
                if row[key] is not None:
                    record["observation"][key] = json.loads(row[key])
    return record


def registry(db, args, bot):
    kind = args.command
    if args.action == "list":
        return inventory(db, kind)
    if args.action == "show":
        record = with_observation(db, item(db, kind, args.id))
        return permission_plan.annotate(db, kind, args.id, record) if kind == "workload" else record
    if args.action == "permissions":
        current = item(db, kind, args.id)
        if args.plan is not None:
            permission_plan.add(db, kind, args.id, args.plan,
                                allow_new=current["state"] not in {"running", "completed"})
        if args.decisions is not None:
            permission_plan.decide(db, kind, args.id, args.decisions)
        return permission_plan.read(db, kind, args.id)
    fields = ("title", "objective", "owner", "criteria", "origin", "project", "agent", "source", "workload",
              "dependency", "blocker", "milestone", "next_action", "due", "review", "human")
    values = {key: getattr(args, key) for key in fields if getattr(args, key) is not None}
    if "human" in values:
        values["human"] = int(values["human"] == "yes")
    if args.action == "update":
        if set(values).intersection(args.clear):
            raise ValueError("a field cannot be both set and cleared")
        values.update(dict.fromkeys(args.clear))
    if values.get("source"):
        if not db.execute("SELECT 1 FROM monitor_sources WHERE id=?", (values["source"],)).fetchone():
            raise ValueError("register the approved monitor source first")
    for field in ("workload", "dependency"):
        if values.get(field):
            item(db, "workload", values[field])
    if values.get("dependency") and kind == "workload":
        cursor = values["dependency"]
        while cursor:
            if cursor == args.id:
                raise ValueError("cyclic workload dependency")
            cursor = item(db, "workload", cursor)["dependency"]
    stamp = now()
    if args.action == "add":
        if db.execute("SELECT 1 FROM ledger_items WHERE kind=? AND id=?", (kind, args.id)).fetchone():
            raise ValueError(f"{kind} {args.id} already exists")
        values.update(kind=kind, id=args.id, state=INITIAL[kind], created=stamp, updated=stamp)
        columns = ",".join(values)
        binds = ",".join("?" for _ in values)
        db.execute(f"INSERT INTO ledger_items({columns}) VALUES({binds})", tuple(values.values()))
    else:
        current = item(db, kind, args.id)
        if current["revision"] != args.revision:
            raise ValueError(f"revision conflict; read {kind} {args.id} again")
        if args.state and args.state != current["state"]:
            if args.state not in STATES[kind][current["state"]]:
                raise ValueError(f"invalid transition from {current['state']} to {args.state}")
            if kind == "workload" and args.state == "running":
                status = permission_plan.read(db, kind, args.id)["status"]
                if status != "ready":
                    raise ValueError(f"Required workload permissions are {status}")
            values["state"] = args.state
            if args.state in ("completed", "failed"):
                if "criteria" in values and values["criteria"] != current["criteria"]:
                    raise ValueError("update criteria separately before recording an outcome")
                values["evidence"] = receipt_store.accept(bot, args.receipt, current, args.state)
        elif args.receipt:
            raise ValueError("receipt requires a transition to completed or failed")
        if current["state"] in ("completed", "failed") and "criteria" in values:
            raise ValueError("preserve the criteria used by the recorded outcome")
        if all(current[key] == value for key, value in values.items()):
            return current
        if "due" in values and current["due"] != values["due"]:
            values["reminded"] = None
        values.update(updated=stamp, revision=args.revision + 1, reviewed=None)
        columns = ",".join(f"{key}=?" for key in values)
        db.execute(f"UPDATE ledger_items SET {columns} WHERE kind=? AND id=?", (*values.values(), kind, args.id))
    result = item(db, kind, args.id)
    db.execute("INSERT INTO ledger_history(kind,id,revision,at,state,evidence) VALUES(?,?,?,?,?,?)",
               (kind, args.id, result["revision"], stamp, result["state"], result["evidence"]))
    return result


def summary(db):
    result = {}
    for kind in STATES:
        result[kind + "s"] = [dict(r) for r in db.execute("""
            SELECT id,title,owner,state,next_action,due,human,revision,dependency,blocker,source
            FROM ledger_items WHERE kind=? AND state NOT IN ('completed','parked','cancelled','failed')
            ORDER BY human DESC,due IS NULL,due,updated,id LIMIT 20""", (kind,))]
    return result


def recent(db, since):
    records = db.execute("""
        SELECT h.kind,h.id,i.title,h.at,h.state,h.evidence FROM ledger_history h
        JOIN ledger_items i USING(kind,id)
        WHERE h.state IN ('completed','failed') AND h.evidence IS NOT NULL AND h.at>=?
        AND EXISTS (SELECT 1 FROM ledger_history prev WHERE prev.kind=h.kind AND prev.id=h.id
                    AND prev.revision=h.revision-1 AND prev.state!=h.state)
        ORDER BY h.at DESC,h.seq DESC LIMIT 20""", (since,))
    return [dict(dict(row), evidence=json.loads(row["evidence"])) for row in records]


def due(db):
    stamp = now()
    rows = [dict(r) for r in db.execute("""
        SELECT id,title,due,next_action FROM ledger_items WHERE kind='commitment'
        AND state NOT IN ('completed','parked','cancelled') AND due<=?
        AND reminded IS NOT due AND (review IS NULL OR review<=?)
        AND NOT (state='waiting' AND EXISTS (SELECT 1 FROM ledger_items d
                 WHERE d.kind='workload' AND d.id=ledger_items.dependency AND d.state='completed'))
        ORDER BY due,id LIMIT 10""", (stamp, stamp))]
    for row in rows:
        db.execute("UPDATE ledger_items SET reminded=due WHERE kind='commitment' AND id=?", (row["id"],))
    return rows


def strategic(db):
    stamp = now()
    rows = [dict(r) for r in db.execute("""
        SELECT a.kind,a.id,a.title,a.state,a.next_action,a.due,a.blocker,a.revision
        FROM ledger_items a LEFT JOIN ledger_items d ON d.kind='workload' AND d.id=a.dependency
        WHERE a.state NOT IN ('parked','completed','cancelled','failed')
        AND (a.review IS NULL OR a.review<=?)
        AND (a.dependency IS NULL OR d.state='completed')
        AND (a.state!='waiting' OR a.review IS NOT NULL OR a.dependency IS NOT NULL)
        AND (a.state NOT IN ('in-progress','running') OR a.review IS NOT NULL OR a.due<=? OR a.updated<=?)
        AND (a.reviewed IS NULL OR (a.dependency IS NOT NULL AND a.reviewed<d.updated))
        ORDER BY a.human DESC,a.due IS NULL,a.due,a.updated,a.kind,a.id LIMIT 3""",
        (stamp, stamp, stamp - 86400))]
    for row in rows:
        db.execute("UPDATE ledger_items SET reviewed=? WHERE kind=? AND id=?", (stamp, row["kind"], row["id"]))
    return rows or None


def preferences(db):
    return [dict(row) for row in db.execute("""SELECT key,content,source,evidence,rev
        FROM ledger_memory WHERE category='preference' AND source='operator'
        AND status='active' AND (expires IS NULL OR expires>?)
        ORDER BY verified DESC,key LIMIT 100""", (now(),))]


def markdown_text(value):
    compact = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", " ".join(value.split()))
    return re.sub(r"([\\`*_[\]<>~&])", r"\\\1", compact)


def memory_reference(value):
    if re.fullmatch(r"(?:https?://|codex://)[a-zA-Z0-9./?=_%&+#:@~-]+", value):
        return f"<{value}>"
    if re.fullmatch(r"(?:evidence|memory|inbox|reports)(?:/[a-zA-Z0-9_.-]+)+", value):
        if not {".", ".."}.intersection(value.split("/")):
            return f"[{value}](<{value}>)"
    return markdown_text(value)


def memory_index(db=None):
    lines = ["# Active private memory"]
    if db is not None and db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger_memory'"
    ).fetchone():
        records = db.execute("""SELECT key,rev,content,source,evidence FROM ledger_memory
            WHERE status='active' AND (expires IS NULL OR expires>?) ORDER BY key,rev DESC""", (now(),))
        for key, revision, content, source, evidence in records:
            lines.extend(("", f"- `{key}` (revision {revision}) {markdown_text(content)}",
                          f"  Source {memory_reference(source)} · Evidence {memory_reference(evidence)}"))
    if len(lines) == 1:
        lines.extend(("", "No active records."))
    return "\n".join(lines)


def memory(db, args, bot):
    if getattr(args, "quiet", False):
        manifest = json.loads((bot / "bot.json").read_text(encoding="utf-8"))
        if manifest.get("memory", {}).get("quiet") != "approved":
            raise ValueError("Quiet memory requires explicit operator approval")
        if args.action == "add" and args.category not in {"preference", "fact", "lesson"}:
            raise ValueError("Quiet memory captures preferences, facts and lessons")
    if args.action == "preferences":
        return preferences(db)
    if args.action == "list":
        return [dict(r) for r in db.execute("""SELECT * FROM ledger_memory
            WHERE (? OR status!='archived') AND (? IS NULL OR key=?) ORDER BY key,rev DESC LIMIT 100""",
            (args.all, args.key, args.key))]
    latest = db.execute("SELECT COALESCE(MAX(rev),0) FROM ledger_memory WHERE key=?", (args.key,)).fetchone()[0]
    stamp = now()
    if args.action == "resolve":
        if args.latest != latest:
            raise ValueError("memory revision conflict; inspect current versions")
        selected = db.execute("SELECT * FROM ledger_memory WHERE key=? AND rev=? AND status!='archived'",
                              (args.key, args.rev)).fetchone()
        if not selected:
            raise ValueError("no current memory at that revision")
        if selected["expires"] is not None and selected["expires"] <= stamp:
            raise ValueError("selected memory has expired")
        db.execute("UPDATE ledger_memory SET status='archived' WHERE key=?", (args.key,))
        data = dict(selected)
        data.update(rev=latest+1, verified=stamp, status="active", supersedes=args.rev,
                    source=args.source, evidence=args.evidence)
    else:
        current = list(db.execute("SELECT * FROM ledger_memory WHERE key=? AND status!='archived'", (args.key,)))
        for row in current:
            if (row["content"], row["category"], row["source"], row["evidence"], row["confidence"], row["expires"]) == (
                    args.content, args.category, args.source, args.evidence, args.confidence, args.expires):
                return dict(row)
        matches = [row for row in current if row["content"] == args.content]
        supersedes = max((row["rev"] for row in matches), default=None)
        for match in matches:
            db.execute("UPDATE ledger_memory SET status='archived' WHERE key=? AND rev=?", (args.key, match["rev"]))
        conflict = any(row["content"] != args.content for row in current)
        if conflict:
            db.execute("UPDATE ledger_memory SET status='disputed' WHERE key=? AND status!='archived'", (args.key,))
        data = dict(key=args.key, rev=latest+1, content=args.content, category=args.category, source=args.source,
                    evidence=args.evidence, observed=stamp, verified=stamp, confidence=args.confidence,
                    expires=args.expires, status="disputed" if conflict else "active", supersedes=supersedes)
    db.execute("""INSERT INTO ledger_memory(key,rev,content,category,source,evidence,observed,verified,
               confidence,expires,status,supersedes) VALUES(:key,:rev,:content,:category,:source,:evidence,
               :observed,:verified,:confidence,:expires,:status,:supersedes)""", data)
    return data


def reflect(db):
    stamp = now()
    expired = [dict(r) for r in db.execute("""SELECT key,rev FROM ledger_memory WHERE status!='archived'
                           AND expires<=? ORDER BY expires,key,rev LIMIT 20""", (stamp,))]
    for r in expired:
        db.execute("UPDATE ledger_memory SET status='archived' WHERE key=? AND rev=?", (r["key"], r["rev"]))
    feedback = [dict(r) for r in db.execute("""SELECT id,subject,outcome,evidence FROM ledger_feedback
                               WHERE reflected IS NULL ORDER BY created,id LIMIT 10""")]
    for r in feedback:
        db.execute("UPDATE ledger_feedback SET reflected=? WHERE id=?", (stamp, r["id"]))
    if expired or feedback:
        return {"archived": expired, "feedback_for_review": feedback}
    return None


def run(db, args, root, bot):
    if args.command in STATES:
        return registry(db, args, bot)
    if args.command == "strategic":
        return strategic(db)
    if args.command == "evidence":
        return receipt_store.run(db, args, bot)
    if args.command == "memory":
        return memory(db, args, bot)
    if args.command == "feedback":
        old = db.execute("SELECT * FROM ledger_feedback WHERE id=?", (args.id,)).fetchone()
        if old:
            if (old["subject"], old["outcome"], old["evidence"]) != (args.subject, args.outcome, args.evidence):
                raise ValueError("feedback ID already used")
        else:
            db.execute("INSERT INTO ledger_feedback VALUES(?,?,?,?,?,NULL)",
                       (args.id, args.subject, args.outcome, args.evidence, now()))
        return {"id": args.id}
    if args.command == "reflect":
        return reflect(db)
    raise ValueError("unknown ledger command")
