"""Local bot projects. The set of published bot manifests is the fleet registry."""

import errno
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile


CHIEF = "chief-of-staff"
SEEDS = (
    (CHIEF, "Engineering Chief of Staff",
     "Track commitments, engineering workloads, dependencies and decisions. Recommend the next intervention that evidence supports.", None),
    ("eval-monitor", "Evaluation Monitor",
     "Compare measurements from approved evaluation runs. Report regressions, repeated plateaus and improvements with the run references.", CHIEF),
)
IDENTIFIER = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
THREAD_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
CADENCE = {
    "heartbeat": "Every 30 minutes during agreed weekday working hours",
    "morning-briefing": "Start of each working day",
    "strategic": "Twice per working day",
    "end-of-day": "End of each working day",
    "reflect": "Daily after the end-of-day review",
    "weekly-review": "Friday near the end of the working day",
}
FOLDERS = (
    "memory/facts", "memory/decisions", "memory/lessons", "memory/episodic",
    "memory/archive", "inbox", "outbox", "state", "reports", "evidence",
)


def install(db):
    """Fleet records are per-project JSON manifests."""


def commands(subparsers):
    create = subparsers.add_parser("create-bot", help="Prepare an inactive specialist project")
    create.add_argument("id", help="Lowercase identifier, e.g. delivery-tracker")
    create.add_argument("--name", required=True)
    create.add_argument("--mission", required=True)
    provision = subparsers.add_parser("provision-bot", help="Record local state for desktop bot provisioning")
    provision.add_argument("id")
    operations = provision.add_mutually_exclusive_group()
    operations.add_argument("--reserve", action="store_true")
    operations.add_argument("--remember", metavar="CHAT_ID")
    operations.add_argument("--activate", metavar="VERIFIED_CHAT_ID")
    subparsers.add_parser("fleet-list", help="List local project definitions")
    mail = subparsers.add_parser("mailbox", help="Exchange bounded assignments and evidence")
    actions = mail.add_subparsers(dest="mail_action", required=True)
    listing = actions.add_parser("list")
    listing.add_argument("--offset", type=int, default=0, help="Skip older result pages in steps of 100")
    assign = actions.add_parser("assign")
    assign.add_argument("to")
    assign.add_argument("key")
    assign.add_argument("objective")
    report = actions.add_parser("report")
    report.add_argument("key")
    report.add_argument("evidence")


def _validate_id(identifier):
    if len(identifier) > 64 or not IDENTIFIER.fullmatch(identifier):
        raise ValueError("Use a bot ID of up to 64 lowercase letters, digits or internal hyphens, starting with a letter")


def _record(directory):
    if directory.is_symlink():
        raise ValueError(f"Bot project must be a local directory: {directory}")
    try:
        record = json.loads((directory / "bot.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read the bot manifest in {directory}") from exc
    if not isinstance(record, dict) or record.get("id") != directory.name:
        raise ValueError(f"Bot ID does not match the project directory: {directory}")
    return record


def _create(root, identifier, name, mission, parent, *, bootstrap=False):
    _validate_id(identifier)
    if not name.strip() or not mission.strip():
        raise ValueError("A bot needs a name and a mission")
    bots = root / "bots"
    bots.mkdir(exist_ok=True)
    if bots.is_symlink():
        raise ValueError("The fleet bots directory must not be a symlink")
    target = bots / identifier

    def existing():
        record = _record(target)
        if not bootstrap and (record["name"], record["mission"], record["parent"]) != (name, mission, parent):
            raise ValueError(f"The identifier {identifier} already belongs to a different definition")
        return record

    if target.exists() or target.is_symlink():
        return existing()
    routines = list(CADENCE) if identifier == CHIEF else ["heartbeat", "reflect"]
    manifest = {
        "version": 1, "model": "gpt-6.2-sol", "id": identifier, "name": name, "mission": mission,
        "parent": parent, "lifecycle": "proposed", "primary_thread": None,
        "completion_authorization": None,
        "memory": {"private": "memory/", "shared": "reviewed references only"},
        "approved_sources": [], "capabilities": ["read approved local evidence", "write project reports"],
        "max_delegation_depth": int(identifier == CHIEF),
        "escalation": ["access denied", "verified regression", "decision required"],
        "routines": [{"id": key, "proposed_cadence": CADENCE[key], "file": f"routines/{key}.md"} for key in routines],
    }
    with tempfile.TemporaryDirectory(dir=bots, prefix=".draft-") as scratch:
        draft = Path(scratch) / "project"
        shutil.copytree(root / "templates" / "persistent-bot", draft)
        if identifier != CHIEF:
            for skill in ("create-bot", "strategic-initiative"):
                shutil.rmtree(draft / ".agents" / "skills" / skill)
            for routine in set(CADENCE) - set(routines):
                (draft / "routines" / f"{routine}.md").unlink()
        for folder in FOLDERS:
            (draft / folder).mkdir(parents=True, exist_ok=True)
        (draft / "bot.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        try:
            draft.rename(target)
        except OSError as exc:
            if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                raise
            return existing()
    return manifest


def bootstrap(root):
    for folder in ("memory", "workloads", "tasks", "events", "reports", "state"):
        (root / "shared" / folder).mkdir(parents=True, exist_ok=True)
    seeds = [_create(root, *seed, bootstrap=True) for seed in SEEDS]
    for project in (root / "bots").iterdir():
        if project.is_symlink() or not (project / "bot.json").is_file():
            continue
        for folder in FOLDERS:
            (project / folder).mkdir(parents=True, exist_ok=True)
        for name in ("MEMORY.md", "USER.md"):
            if not (project / name).exists():
                contents = (root / "templates" / "persistent-bot" / name).read_bytes()
                try:
                    with (project / name).open("xb") as target:
                        target.write(contents)
                except FileExistsError:
                    pass
    return seeds


def run(db, args, root, bot):
    if args.command == "mailbox":
        return _mailbox(args, root, bot)
    if args.command == "fleet-list":
        return [_record(p) for p in sorted((root / "bots").iterdir())
                if p.is_dir() and IDENTIFIER.fullmatch(p.name)]
    if args.command == "create-bot":
        if bot != root / "bots" / CHIEF:
            raise ValueError("Create a specialist from the Chief of Staff project")
        return _create(root, args.id, args.name, args.mission, CHIEF)
    raise ValueError(f"Unknown fleet command: {args.command}")


def provision(db, args, root, chief):
    if chief != root / "bots" / CHIEF:
        raise ValueError("Provision specialists from the Chief of Staff project")
    _validate_id(args.id)
    project = chief.parent / args.id
    bot = _record(project)
    if bot.get("parent") != CHIEF or bot.get("lifecycle") not in {"proposed", "active"}:
        raise ValueError("Select a proposed or active specialist belonging to this chief")

    db.execute("""CREATE TABLE IF NOT EXISTS bot_provisioning (
        bot TEXT PRIMARY KEY, candidate TEXT, verified INTEGER NOT NULL DEFAULT 0)""")
    attempt = db.execute("SELECT candidate, verified FROM bot_provisioning WHERE bot=?", (args.id,)).fetchone()
    candidate = attempt["candidate"] if attempt else None
    primary = bot.get("primary_thread")
    verified = bool(primary and candidate == primary and attempt["verified"])
    thread = primary or candidate
    launch = False
    if args.reserve and not (attempt or thread) and bot["lifecycle"] == "proposed":
        db.execute("INSERT INTO bot_provisioning (bot) VALUES (?)", (args.id,))
        attempt = True
        launch = True
    if args.remember is not None:
        if not THREAD_ID.fullmatch(args.remember) or (thread and thread != args.remember):
            raise ValueError("The candidate chat ID is invalid or conflicts with the recorded chat")
        db.execute("""INSERT INTO bot_provisioning (bot, candidate) VALUES (?, ?)
            ON CONFLICT (bot) DO UPDATE SET candidate=excluded.candidate""", (args.id, args.remember))
        thread = args.remember
        attempt = True
    if args.activate is not None:
        if not THREAD_ID.fullmatch(args.activate) or args.activate != thread:
            raise ValueError("The verified chat must match the recorded candidate or binding")
        if bot["lifecycle"] == "proposed":
            bot.update(primary_thread=thread, lifecycle="active")
            with tempfile.TemporaryDirectory(dir=project, prefix=".provision-") as scratch:
                manifest = Path(scratch) / "bot.json"
                manifest.write_text(json.dumps(bot, indent=2) + "\n", encoding="utf-8")
                manifest.replace(project / "bot.json")
        db.execute("""INSERT INTO bot_provisioning (bot, candidate, verified) VALUES (?, ?, 1)
            ON CONFLICT (bot) DO UPDATE SET candidate=excluded.candidate, verified=1""", (args.id, thread))
        verified = True
    return {"project": str(project), "name": bot["name"], "lifecycle": bot["lifecycle"],
            "primary_thread": bot.get("primary_thread"), "candidate": thread, "verified": verified, "launch": launch}


def _mailbox(args, root, bot):
    sender = bot.name
    filename = root / "shared" / "state" / "mailbox.sqlite"
    if args.mail_action == "assign":
        if sender != CHIEF:
            raise ValueError("Only the Chief of Staff assigns specialist work")
        _validate_id(args.to)
        if _record(root / "bots" / args.to).get("parent") != sender:
            raise ValueError("Select a specialist belonging to this chief")
        if not args.objective.strip() or len(args.objective) > 2000:
            raise ValueError("Supply a bounded objective of up to 2000 characters")
    if args.mail_action != "list":
        _validate_id(args.key)
    if args.mail_action == "report" and (not args.evidence.strip() or len(args.evidence) > 4000):
        raise ValueError("Supply a concise evidence reference of up to 4000 characters")

    connection = sqlite3.connect(filename, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""CREATE TABLE IF NOT EXISTS assignments (
                key TEXT PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL,
                objective TEXT NOT NULL, evidence TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                reported_at TEXT)""")
            if args.mail_action == "list":
                rows = connection.execute("""SELECT * FROM assignments WHERE sender=? OR recipient=?
                    ORDER BY created_at DESC, key LIMIT 100 OFFSET ?""", (sender, sender, max(0, args.offset)))
                return [dict(row) for row in rows]

            if args.mail_action == "assign":
                connection.execute("""INSERT INTO assignments(key,sender,recipient,objective)
                    VALUES (?,?,?,?) ON CONFLICT(key) DO NOTHING""",
                                   (args.key, sender, args.to, args.objective))
            row = connection.execute("SELECT * FROM assignments WHERE key=?", (args.key,)).fetchone()
            if args.mail_action == "assign":
                if (row["sender"], row["recipient"], row["objective"]) != (sender, args.to, args.objective):
                    raise ValueError("This assignment key is already in use")
            else:
                if row is None or row["recipient"] != sender:
                    raise ValueError("No matching assignment for this specialist")
                if row["evidence"] is not None and row["evidence"] != args.evidence:
                    raise ValueError("The assignment already has a different report")
                connection.execute("""UPDATE assignments SET evidence=?, reported_at=CURRENT_TIMESTAMP
                    WHERE key=? AND evidence IS NULL""", (args.evidence, args.key))
            return dict(connection.execute("SELECT * FROM assignments WHERE key=?", (args.key,)).fetchone())
    finally:
        connection.close()


def deliveries(db, root, bot):
    """Advance a private cursor through local assignments and replies in commit order."""
    mailbox = root / "shared" / "state" / "mailbox.sqlite"
    if not mailbox.is_file():
        return []
    db.execute("""CREATE TABLE IF NOT EXISTS mailbox_seen (key TEXT PRIMARY KEY)""")
    # Attach read-only so the cursor and selected keys can be joined in one bounded query.
    db.execute("ATTACH DATABASE ? AS shared_mail", (mailbox.as_uri() + "?mode=ro",))
    rows = [dict(row) for row in db.execute("""SELECT a.key,a.sender,a.recipient,a.objective,a.evidence
        FROM shared_mail.assignments a LEFT JOIN mailbox_seen s USING(key)
        WHERE s.key IS NULL AND ((recipient=? AND evidence IS NULL) OR
              (sender=? AND evidence IS NOT NULL)) ORDER BY a.rowid LIMIT 5""", (bot.name, bot.name))]
    db.executemany("INSERT INTO mailbox_seen(key) VALUES(?)", ((r["key"],) for r in rows))
    return rows
