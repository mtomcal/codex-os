#!/usr/bin/env python3
"""Run one bounded operation inside a Codex bot project."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import time

import dispatch
import fleet
import ledger
import monitor

ROOT = Path(__file__).resolve().parent


def select_bot(root, identifier):
    if identifier is None:
        cwd = Path.cwd().resolve()
        bots = root / "bots"
        identifier = cwd.relative_to(bots).parts[0] if cwd.is_relative_to(bots) and cwd != bots else fleet.CHIEF
    if not fleet.IDENTIFIER.fullmatch(identifier):
        raise ValueError("Invalid bot identifier")
    bot = root / "bots" / identifier
    if bot.resolve() != bot or not (bot / "bot.json").is_file():
        raise ValueError("Unknown bot project. Run init to prepare the initial projects.")
    return bot


def briefing(db, period):
    since = time.time() - (7 if period == "week" else 1) * 86400
    rows = db.execute("""SELECT * FROM monitor_findings WHERE created>=?
        ORDER BY priority='attention' DESC, created DESC, id DESC LIMIT 20""", (since,))
    findings = [dict(dict(row), evidence=json.loads(row["evidence"])) for row in rows]
    outcomes = ledger.recent(db, since)
    work = ledger.summary(db)
    for workload in work["workloads"]:
        ledger.with_observation(db, workload)
    return {"period": period, "findings": findings, "verified_outcomes": outcomes, "work": work}


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bot", help="Bot project ID (defaults to the current bot, or chief-of-staff)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Prepare proposed projects and shared directories")
    sub.add_parser("status", help="Check this project's durable state")
    sub.add_parser("briefing", help="Read recent evidence and open work").add_argument(
        "--period", choices=("day", "week"), default="day")
    for module in (fleet, ledger, monitor, dispatch):
        module.commands(sub)
    args = parser.parse_args(argv)
    if args.command == "init":
        return [record["id"] for record in fleet.bootstrap(root)]
    bot = select_bot(root, args.bot)
    if args.command in {"mailbox", "create-bot", "fleet-list"}:
        return fleet.run(None, args, root, bot)
    folder = bot / "state"
    folder.mkdir(exist_ok=True)
    with closing(sqlite3.connect(folder / "agent.sqlite3", timeout=5, uri=True)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("BEGIN IMMEDIATE")
        for module in (ledger, monitor, dispatch):
            module.install(db)
        if args.command == "status":
            return {"bot": bot.name, "database": str(folder / "agent.sqlite3"),
                    "integrity": db.execute("PRAGMA quick_check").fetchone()[0],
                    "sources": db.execute("SELECT count(*) FROM monitor_sources").fetchone()[0]}
        if args.command == "dispatch":
            return dispatch.run(db, args, root, bot)
        if args.command == "provision-bot":
            return fleet.provision(db, args, root, bot)
        if args.command == "briefing":
            return briefing(db, args.period)
        if args.command == "heartbeat":
            findings = monitor.run(db, args, root, bot)
            reminders = ledger.due(db)
            messages = fleet.deliveries(db, root, bot)
            workers = dispatch.pending(db)
            cleanup = dispatch.cleanup_candidates(root, workers)
            handoffs = dispatch.pending_handoffs(db)
            if workers or findings or reminders or messages or handoffs:
                return {"findings": findings or [], "commitments": reminders or [], "mailbox": messages,
                        "workers_to_check": workers, "workers_to_archive": cleanup,
                        "pending_handoffs": handoffs}
            return None
        if args.command in monitor.COMMANDS:
            return monitor.run(db, args, root, bot)
        return ledger.run(db, args, root, bot)


if __name__ == "__main__":
    try:
        result = main()
        if result is not None:
            print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    except (OSError, ValueError, sqlite3.Error) as exc:
        sys.exit(f"codexos: {exc}")
