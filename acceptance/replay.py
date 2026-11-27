#!/usr/bin/env python3
"""Replay deterministic acceptance cases through the public CLI in disposable bot projects."""
import argparse
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
LAB = "memory-lab"
CHIEF = "chief-of-staff"
MODULES = tuple(sorted(path.name for path in ROOT.glob("*.py")))
CREATE = ("create-bot", LAB, "--name", "Memory Lab", "--mission", "Exercise synthetic acceptance cases.")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


class Replay:
    def __init__(self, directory, result):
        self.root = directory
        self.result = result
        self.bot = directory / "bots" / LAB

    def cli(self, *args, bot=LAB, rejected=None, raw=False):
        cwd = self.root / "bots" / bot if bot else self.root
        p = subprocess.run([sys.executable, str(self.root / "codexos.py"), *args], cwd=cwd,
                           capture_output=True, timeout=15, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        step = {"cwd": str(cwd.relative_to(self.root)), "args": args, "exit": p.returncode}
        self.result["commands"].append(step)
        stderr = p.stderr.decode().strip()
        if stderr:
            step["stderr"] = stderr.replace(str(self.root), "<fleet>")
        if rejected:
            self.check("Reject " + " ".join(args[:2]), True, p.returncode != 0 and rejected in stderr)
            return
        if p.returncode:
            raise RuntimeError(f"{args}: {stderr}")
        if raw:
            return p.stdout
        return json.loads(p.stdout) if p.stdout else None

    def check(self, description, expected, actual):
        ok = expected == actual
        self.result["checks"].append(dict(check=description, expected=expected, actual=actual, passed=ok))
        if not ok:
            raise AssertionError(description)

    def add(self, kind, key, *args):
        return self.cli(kind, "add", key, "--title", key, "--owner", "lab", "--objective", "Verify " + key,
                        "--criteria", "fixture passes", "--next-action", "Review independent receipt", *args)

    def publish(self, source, data):
        path = self.bot / "inbox" / f"{source}.json"
        path.write_text(json.dumps(dict(source=source, **data)), encoding="utf-8")

    def evaluation(self, rev, score, **changes):
        data = dict(kind="eval", revision=rev, run=f"run-{rev}", metric="passes", unit="count",
                    direction="higher", value=score, observed_at=utc(), evidence=[f"suite/run-{rev}"])
        self.publish("suite", {**data, **changes})


def factory(r):
    record = r.cli(*CREATE, bot=CHIEF)
    r.check("New bot is proposed, unbound and scoped to its parent",
            ["proposed", None, CHIEF, 0, []], [record[k] for k in ("lifecycle", "primary_thread", "parent", "max_delegation_depth", "approved_sources")])
    model = tomllib.loads((r.bot / ".codex/config.toml").read_text())["model"]
    r.check("Project and manifest select Sol", ["gpt-6.2-sol", "gpt-6.2-sol"], [record["model"], model])
    paths = ["AGENTS.md", "SOUL.md", "USER.md", "MEMORY.md", "HEARTBEAT.md", *[row["file"] for row in record["routines"]]]
    r.check("Every startup file and proposed routine exists", [], [path for path in paths if not (r.bot / path).is_file()])
    (r.bot / "USER.md").write_text("Synthetic operator preference")
    r.cli("init", bot=None)
    r.cli(*CREATE, bot=CHIEF)
    r.check("Bootstrap and a repeated factory request preserve operator content", "Synthetic operator preference",
            (r.bot / "USER.md").read_text())
    r.cli("create-bot", "unauthorized", "--name", "Unexpected", "--mission", "Unexpected", rejected="Chief of Staff")
    r.check("Specialist factory refusal creates no project", False, (r.root / "bots/unauthorized").exists())
    r.check("Fleet listing contains the lab exactly once", 1, [a["id"] for a in r.cli("fleet-list")].count(LAB))


def memory(r):
    initial = ("memory", "add", "review-window", "Wednesday", "--source", "operator", "--evidence", "fixture-1",
               "--confidence", "high", "--category", "preference")
    r.cli(*initial)
    r.cli(*initial)
    reload = r.cli("memory", "list", "--key", "review-window")
    r.check("Fresh processes recall one attributed preference after duplicate writes",
            [["Wednesday", "operator", "fixture-1", "high", "preference"]],
            [[row[k] for k in ("content", "source", "evidence", "confidence", "category")] for row in reload])
    r.check("Chief's private CLI view excludes lab memory", [], r.cli("memory", "list", bot=CHIEF))
    r.cli("memory", "add", "review-window", "Thursday", "--source", "operator", "--evidence", "fixture-2")
    rows = r.cli("memory", "list", "--key", "review-window")
    r.check("Contradictory claims remain inspectable", [["Thursday", "disputed"], ["Wednesday", "disputed"]],
            [[row["content"], row["status"]] for row in rows])
    r.cli("memory", "resolve", "review-window", "2", "--latest", "1", "--source", "operator", "--evidence", "stale review",
          rejected="revision conflict")
    r.cli("memory", "resolve", "review-window", "2", "--latest", "2", "--source", "operator", "--evidence", "signed fixture")
    rows = r.cli("memory", "list", "--all", "--key", "review-window")
    r.check("Resolution retains both prior revisions and current provenance",
            [[3,"Thursday","active","signed fixture"],[2,"Thursday","archived","fixture-2"],[1,"Wednesday","archived","fixture-1"]],
            [[row[k] for k in ("rev","content","status","evidence")] for row in rows])
    r.cli("memory", "add", "temporary", "Temporary constraint", "--source", "operator", "--evidence", "fixture-3",
          "--expires", (datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
    fb = ("feedback", "noise-1", "--subject", "unnecessary alert", "--outcome", "false alert", "--evidence", "review-1")
    r.cli(*fb)
    r.cli(*fb)
    out = r.cli("reflect")
    r.check("Reflection archives expired material and returns feedback once", [["temporary"],["noise-1"]],
            [[a["key"] for a in out["archived"]], [a["id"] for a in out["feedback_for_review"]]])
    r.check("Repeated reflection is quiet", None, r.cli("reflect"))
    r.check("Expired material disappears from working memory", [], r.cli("memory", "list", "--key", "temporary"))


def workload(r):
    r.add("workload","release")
    r.add("commitment","review","--dependency","release")
    r.cli("commitment","update","review","--revision","1","--state","waiting")
    r.check("Strategic review skips a dependent commitment", ["release"], [a["id"] for a in r.cli("strategic")])
    r.check("A repeated strategic check is quiet",None,r.cli("strategic"))
    r.cli("workload","update","release","--revision","1","--state","completed",rejected="invalid transition")
    r.cli("workload","update","release","--revision","1","--state","ready")
    r.cli("workload","update","release","--revision","1","--owner","other",rejected="revision conflict")
    r.cli("workload","update","release","--revision","2","--state","running")
    close = ("workload","update","release","--revision","3","--state","completed")
    r.cli(*close,rejected="receipt")
    path = r.bot / "evidence" / "check.json"
    receipt = dict(schema=1,kind="workload",id="other",criteria="fixture passes",result="passed",run_id="release-fixture-6")
    path.write_text(json.dumps(receipt))
    r.cli(*close,"--receipt","check.json",rejected="does not verify")
    r.check("Failed closures preserve the running revision",3,r.cli("workload","show","release")["revision"])
    receipt["id"] = "release"
    path.write_text(json.dumps(receipt))
    r.cli(*close,"--receipt","check.json")
    r.check("Satisfied dependency becomes eligible",["review"],[a["id"] for a in r.cli("strategic")])
    for period in ("day","week"):
        out = r.cli("briefing","--period",period)
        r.check(f"{period} briefing includes the verified outcome and open dependent commitment",
                [["completed", "release-fixture-6", digest(path)], ["review"]],
                [[out["verified_outcomes"][0]["state"],out["verified_outcomes"][0]["evidence"]["run_id"],
                  out["verified_outcomes"][0]["evidence"]["sha256"]],[a["id"] for a in out["work"]["commitments"]]])
    due = (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
    r.add("commitment","due","--due",due)
    r.add("commitment","deferred","--due",due,"--review",(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
    r.check("Only the due, eligible commitment triggers a reminder",["due"],[a["id"] for a in r.cli("heartbeat")["commitments"]])
    r.check("Deadline reminder is delivered once",None,r.cli("heartbeat"))


def monitor(r):
    r.cli("source-add","suite","eval","suite.json")
    r.add("workload","benchmark","--source","suite")
    r.evaluation(1,90)
    r.check("Initial observation is silent",None,r.cli("heartbeat"))
    r.evaluation(2,95)
    r.check("Improvement waits for the briefing",None,r.cli("heartbeat"))
    finding = r.cli("briefing")["findings"][0]
    r.check("Improvement preserves evidence",["improvement",["suite/run-2"]],[finding["kind"],finding["evidence"]])
    r.evaluation(3,83)
    with ThreadPoolExecutor(max_workers=3) as pool:
        pulses = list(pool.map(lambda _: r.cli("heartbeat"), range(3)))
    alerts = [(a["kind"],a["evidence"]) for p in pulses if p for a in p["findings"]]
    r.check("Three competing CLI callers surface one regression for the observed run",
            [["regression",["suite/run-3"]]],[list(a) for a in alerts])
    r.check("Identical current snapshot is quiet",None,r.cli("heartbeat"))
    o = r.cli("workload","show","benchmark")["observation"]
    r.check("Restart retains baseline, latest value, revision", [90,83,3],[o["baseline"]["value"],o["latest"]["value"],o["revision"]])
    findings = []
    for rev in range(4,8):
        r.evaluation(rev,83)
        pulse = r.cli("heartbeat")
        findings.append([a["kind"] for a in pulse["findings"]] if pulse else [])
    r.check("Plateau alerts on the third flat new run and stays quiet on the fourth",
            [[],[],["stagnation"],[]],findings)
    r.evaluation(8,83,blockers=["waiting-for-artifact"])
    r.check("New blocker raises attention",["attention"],[a["kind"] for a in r.cli("heartbeat")["findings"]])
    r.evaluation(9,83,blockers=["waiting-for-artifact"])
    r.check("Same blocker persists across a new run without another alert",None,r.cli("heartbeat"))
    r.check("Other bot's operational findings stay private",[],r.cli("findings",bot=CHIEF))


def reliability(r):
    r.cli("source-add","suite","eval","suite.json")
    r.evaluation(1,70)
    r.cli("heartbeat")
    cases = [
        ("invalid",dict(kind="eval",revision=2)),
        ("stale",dict(kind="eval",revision=2,value=75,metric="passes",run="old",direction="higher",
                      observed_at=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat(),evidence=["old"])),
        ("unavailable",dict(kind="eval",error="unavailable")),
        ("denied",dict(kind="eval",error="denied")),
    ]
    for kind,snapshot in cases:
        r.publish("suite",snapshot)
        alert = r.cli("heartbeat")["findings"][0]
        row = r.cli("source-list")[0]
        r.check(f"{kind} retains the last accepted revision and records its own outcome",
                [kind,kind,1,int(kind!="denied")],[alert["kind"],row["outcome"],row["revision"],row["enabled"]])
        if kind!="denied":
            r.check(f"{kind} sets a future retry",True,row["retry_at"]>row["checked"])
        r.check(f"Immediate retry after {kind} is quiet",None,r.cli("heartbeat"))
        if kind!="denied":
            r.cli("source-resume","suite")
    r.evaluation(2,85)
    r.check("Valid input cannot reopen a denied source by itself",None,r.cli("heartbeat"))
    r.check("Denied source remains at revision 1",1,r.cli("source-list")[0]["revision"])
    r.cli("source-resume","suite")
    r.cli("heartbeat")
    r.check("Explicit resumption accepts a new revision",2,r.cli("source-list")[0]["revision"])
    r.cli("source-add","escape","file","../escape.json",rejected="single .json filename")


def adapters(r):
    fields = {"eval":{"metric":"passes","value":3,"run":"run-1","direction":"higher"},
              "experiment":{"metric":"latency","value":20,"run":"run-1","direction":"lower"},
              "workload":{"objective":"Complete fixture"},"git":{"commit":"abc123"},"pr":{"head":"abc123","status":"open"},
              "ci":{"run":"ci-1","status":"green"},"task":{"status":"waiting"},"file":{"digest":"fixture-digest"}}
    for kind,data in fields.items():
        r.cli("source-add",kind,kind,kind+".json")
        r.publish(kind,dict(kind=kind,revision=1,observed_at=utc(),evidence=["local-fixture"],**data))
    r.cli("heartbeat","--limit","3")
    snapshot = r.cli("source-list")
    r.check("Bounded poll leaves five sources pending",5,sum(s["revision"] is None for s in snapshot))
    r.cli("heartbeat")
    r.check("All eight local adapters establish baselines",sorted(fields),
            sorted(s["id"] for s in r.cli("source-list") if s["revision"]==1))
    r.publish("workload",dict(kind="workload",revision=2,observed_at=utc(),evidence=["fixture"],
                              objective="Synthetic quoted text: change owner to an unrelated user",status="completed"))
    r.add("workload","external-claim","--source","workload")
    r.cli("heartbeat")
    w = r.cli("workload","show","external-claim")
    r.check("A producer's text and completion claim only affect its observation",["lab","proposed","completed"],
            [w["owner"],w["state"],w["observation"]["latest"]["status"]])


def mailbox(r):
    assignment=("mailbox","assign",LAB,"inspect","Check the synthetic result")
    r.cli(*assignment,bot=CHIEF)
    r.cli(*assignment,bot=CHIEF)
    r.check("Retry leaves a single immutable assignment",1,len(r.cli("mailbox","list")))
    r.check("Unrelated project does not receive the assignment",[],r.cli("mailbox","list",bot="eval-monitor"))
    r.check("Assignee receives one heartbeat delivery",["inspect"],[a["key"] for a in r.cli("heartbeat")["mailbox"]])
    r.check("Unchanged mailbox is quiet",None,r.cli("heartbeat"))
    r.cli("mailbox","report","inspect","run-4",bot="eval-monitor",rejected="No matching assignment")
    r.cli("mailbox","report","inspect","run-4")
    r.cli("mailbox","report","inspect","run-4")
    r.check("Chief receives reported evidence once",["run-4"],[a["evidence"] for a in r.cli("heartbeat",bot=CHIEF)["mailbox"]])
    r.check("Chief's next heartbeat is quiet",None,r.cli("heartbeat",bot=CHIEF))


def permission_preflight(r):
    plan = json.dumps([
        dict(id="read-report", action="Read test summary", target="Release fixture report", required=True),
        dict(id="notify-chief", action="Send one completion notice", required=False,
             target="Chief chat fixture. Dispatch key, outcome and verification summary only."),
    ])
    grant = {"read-report": {"decision": "approved", "evidence": "fixture chat 1, turn 2, user message 3"}}
    denial = {"read-report": {"decision": "denied", "evidence": "fixture chat 1, turn 4, user message 5"}}
    denied_notice = {"notify-chief": {"decision": "denied", "evidence": "fixture chat 1, turn 2, user message 3"}}

    def reserve(key, *args):
        return r.cli("dispatch", "reserve", key, "--objective", "Verify permissions",
                     "--scope", "Fixture project only", *args)

    prepared = reserve("permitted-dispatch", "--prepare", "--plan", plan)
    r.check("Permission bundle is durable before any worker launch", ["pending", 0, False],
            [prepared["permissions"]["status"], prepared["launch_issued"], prepared["launch"]])
    r.check("The bundle stays pending after a legacy-form retry", False, reserve("permitted-dispatch")["launch"])
    r.cli("dispatch", "bind", "permitted-dispatch", "fixture-worker", rejected="Claim the dispatch launch")
    recorded = r.cli("dispatch", "permissions", "permitted-dispatch", "--decisions", json.dumps(grant))
    r.check("Approved subset preserves scope, evidence and the unanswered optional action",
            ["ready", None, "Release fixture report", grant["read-report"]["evidence"]],
            [recorded["status"], recorded["items"][0]["decision"], recorded["items"][1]["target"],
             recorded["items"][1]["evidence"]])
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(reserve, ["permitted-dispatch"] * 3))
    r.check("Concurrent resumes claim one launch and preserve the same bundle", [1, [recorded] * 3],
            [sum(result["launch"] for result in results), [result["permissions"] for result in results]])
    repeated = reserve("permitted-dispatch", "--plan", plan, "--decisions", json.dumps(grant))
    r.check("Retries of the same bundle and grant produce no duplicate requests or launch",
            [False, recorded], [repeated["launch"], repeated["permissions"]])
    r.cli("dispatch", "reserve", "permitted-dispatch", "--objective", "Verify permissions",
          "--scope", "Fixture project only", "--plan", plan.replace("Release fixture report", "Other report"),
          rejected="Permission request already has a different scope")
    r.cli("dispatch", "bind", "permitted-dispatch", "fixture-worker")

    denied = reserve("denied-dispatch", "--plan", plan, "--decisions", json.dumps(denial))
    r.check("A denied required permission leaves the dispatch unlaunched", ["denied", False],
            [denied["permissions"]["status"], reserve("denied-dispatch")["launch"]])
    r.cli("dispatch", "permissions", "denied-dispatch", "--decisions", json.dumps(grant),
          rejected="Permission decision is already recorded")

    covered = reserve("covered-dispatch", "--plan", plan, "--decisions", json.dumps(grant | denied_notice))
    r.check("A verified existing grant and declined optional action permit the first launch", [True, "denied"],
            [covered["launch"], covered["permissions"]["items"][0]["decision"]])
    legacy = reserve("legacy-dispatch", "--plan", "[]")
    r.check("An empty permission plan preserves one-shot legacy launch", [True, False, False],
            [legacy["launch"], "permissions" in legacy, reserve("legacy-dispatch")["launch"]])

    reuse = ("--reuse", "permitted-dispatch", "--requirement", "Review another part of the fixture")
    extra = reserve("reuse-permissions", *reuse, "--plan", plan)
    r.check("A reused dispatch records an independent permission bundle", [False, "pending", "fixture-worker"],
            [extra["launch"], extra["permissions"]["status"], extra["worker"]])
    claim = ("dispatch", "handoff", "reuse-permissions", "--claim", "fixture chat 1, separate send grant")
    r.cli(*claim, rejected="Required handoff permissions are pending")
    r.cli("dispatch", "permissions", "reuse-permissions", "--decisions", json.dumps(grant))
    r.check("An approved work plan leaves the message handoff pending",
            "pending", r.cli("dispatch", "show", "reuse-permissions")["handoff"])
    r.check("The separate message claim is one-shot", [True, False], [r.cli(*claim)["send"], r.cli(*claim)["send"]])

    r.add("workload", "scoped-work")
    r.cli("workload", "permissions", "scoped-work", "--plan", plan)
    r.cli("workload", "update", "scoped-work", "--revision", "1", "--state", "ready")
    start = ("workload", "update", "scoped-work", "--revision", "2", "--state", "running")
    r.cli(*start, rejected="Required workload permissions are pending")
    r.cli("workload", "permissions", "scoped-work", "--decisions", json.dumps(grant))
    r.check("An approved workload starts without a revision change from preflight", "running", r.cli(*start)["state"])
    r.cli("workload", "update", "scoped-work", "--revision", "3", "--state", "waiting")
    resume_plan = json.dumps([dict(id="read-next", action="Read follow-up", target="New report", required=True)])
    r.cli("workload", "permissions", "scoped-work", "--plan", resume_plan)
    resume = ("workload", "update", "scoped-work", "--revision", "4", "--state", "running")
    r.cli(*resume, rejected="Required workload permissions are pending")
    r.cli("workload", "permissions", "scoped-work", "--decisions", json.dumps({"read-next": denial["read-report"]}))
    r.cli(*resume, rejected="Required workload permissions are denied")
    r.check("A denied resume retains the workload's prior state", "waiting",
            r.cli("workload", "show", "scoped-work")["state"])


def durable_memory_index(r):
    notes = r.bot / "MEMORY.md"
    database = r.bot / "state/agent.sqlite3"
    authored = notes.read_bytes()
    initial_paths = set(r.bot.rglob("*"))

    def index():
        return r.cli("memory", "index", raw=True).decode()

    r.check("An empty index creates no private state", [True, True],
            ["No active records." in index(), initial_paths == set(r.bot.rglob("*"))])
    r.cli("memory", "add", "release-platform", "Run on Linux", "--source", "https://example.test/source",
          "--evidence", "evidence/linux.md")
    first = index()
    r.check("The view includes the stable key, source and evidence links", True,
            all(fragment in first for fragment in ("`release-platform` (revision 1)", "Run on Linux",
                                                    "<https://example.test/source>", "(<evidence/linux.md>)")))
    r.cli("memory", "add", "release-platform", "Run on macOS", "--source", "operator", "--evidence", "evidence/mac.md")
    r.check("Disputed memory stays out of the active view", False, "`release-platform`" in index())
    r.cli("memory", "resolve", "release-platform", "2", "--latest", "2", "--source", "operator",
          "--evidence", "evidence/decision.md")
    r.cli("memory", "add", "expired", "Expired record", "--source", "operator", "--evidence", "test",
          "--expires", "2020-01-01T00:00:00Z")
    current_paths = set(r.bot.rglob("*"))
    before = database.read_bytes()
    view = index()
    history = r.cli("memory", "list", "--all", "--key", "release-platform")
    r.check("Only the superseding active revision appears while prior revisions remain in SQLite", True,
            all(fragment in view for fragment in ("`release-platform` (revision 3)", "Run on macOS",
                                                  "(<evidence/decision.md>)"))
            and all(fragment not in view for fragment in ("Run on Linux", "Expired record", "evidence/linux.md"))
            and [(row["rev"], row["status"]) for row in history] ==
            [(3, "active"), (2, "archived"), (1, "archived")])
    r.check("Rendering the index creates no second store and preserves the notes and database", True,
            before == database.read_bytes() and authored == notes.read_bytes()
            and current_paths == set(r.bot.rglob("*")))


def receipt_archival(r):
    name = "reused.json"
    hot = r.bot / "evidence" / name
    archive = r.bot / "state/evidence-archive"
    database = r.bot / "state/agent.sqlite3"
    r.add("workload", "receipt-check")

    def transition(revision, state, *args, **kwargs):
        return r.cli("workload", "update", "receipt-check", "--revision", str(revision), "--state", state,
                     *args, **kwargs)

    def receipt(result, run, key="receipt-check"):
        return (json.dumps(dict(schema=1, kind="workload", id=key, criteria="fixture passes",
                                result=result, run_id=run), indent=2) + "\n").encode()

    def resolved(revision, **kwargs):
        return r.cli("evidence", "resolve", "workload", "receipt-check", str(revision), raw=True, **kwargs)

    def rotate(revision, *args, **kwargs):
        return r.cli("evidence", "archive", "workload", "receipt-check", str(revision), *args, **kwargs)

    def ledger_references():
        with closing(sqlite3.connect(database)) as db:
            return db.execute("""SELECT revision,evidence FROM ledger_history
                WHERE id='receipt-check' AND evidence IS NOT NULL ORDER BY revision""").fetchall()

    transition(1, "ready")
    transition(2, "running")
    hot.write_bytes(receipt("failed", "wrong-run", "another-item"))
    transition(3, "failed", "--receipt", name, rejected="does not verify this item")
    failed = receipt("failed", "run-original")
    hot.write_bytes(failed)
    old_ref = json.loads(transition(3, "failed", "--receipt", name)["evidence"])
    r.check("The original filename and producer run ID survive acceptance", [name, "run-original"],
            [old_ref["file"], old_ref["run_id"]])
    r.check("Resolve verifies and emits exact hot bytes", failed.hex(), resolved(4).hex())
    rotate(4, "--release-hot", rejected="active or retryable work pins")
    r.check("Archive defaults to leaving the hot copy pinned", ["pinned", True],
            [rotate(4)["hot"], hot.exists()])

    transition(4, "ready")
    transition(5, "running")
    passed = receipt("passed", "run-successor")
    hot.write_bytes(passed)
    new_ref = json.loads(transition(6, "completed", "--receipt", name)["evidence"])
    before = ledger_references()
    link = f"evidence/{name}"
    r.cli("memory", "add", "archive-evidence", "The latest check passed", "--source", "operator",
          "--evidence", link)
    r.check("Active memory links to the accepted hot receipt", True,
            f"(<{link}>)" in r.cli("memory", "index", raw=True).decode())
    rotate(7, "--release-hot", rejected="active memory pins")
    r.check("A memory pin keeps the accepted hot bytes", passed.hex(), hot.read_bytes().hex())
    r.cli("memory", "resolve", "archive-evidence", "1", "--latest", "1", "--source", "operator",
          "--evidence", "https://example.test/review")
    r.cli("memory", "add", "archive-evidence", "The latest check passed", "--source", link,
          "--evidence", "https://example.test/review")
    rotate(7, "--release-hot", rejected="active memory pins")
    r.cli("memory", "add", "archive-evidence", "The latest check passed", "--source", link,
          "--evidence", "https://example.test/review", "--expires", "2020-01-01T00:00:00Z")
    r.check("Historical resolution follows the original digest across filename reuse", failed.hex(), resolved(4).hex())
    r.check("Rotating the historical version preserves the newer hot file", ["different", passed.hex()],
            [rotate(4, "--release-hot")["hot"], hot.read_bytes().hex()])
    partial = archive / (".write-" + new_ref["sha256"])
    partial.write_bytes(b"interrupted copy")
    r.check("Retry replaces an interrupted copy and verifies the new digest", [new_ref, False],
            [rotate(7)["reference"], partial.exists()])
    blob = archive / new_ref["sha256"]
    r.check("The content-addressed archive is private", [0, 0], [archive.stat().st_mode & 0o077, blob.stat().st_mode & 0o077])

    pending = archive / (".release-" + new_ref["sha256"] + "-" + name)
    hot.rename(pending)
    r.cli("memory", "add", "archive-evidence", "The latest check passed", "--source", "operator",
          "--evidence", link)
    rotate(7, "--release-hot", rejected="active memory pins")
    r.check("A new memory pin restores the hot path after an interrupted release", [passed.hex(), False],
            [hot.read_bytes().hex(), pending.exists()])
    r.cli("memory", "add", "archive-evidence", "The latest check passed", "--source", "operator",
          "--evidence", "https://example.test/review")
    blob.write_bytes(receipt("passed", "tampered-run"))
    rotate(7, "--release-hot", rejected="archived receipt SHA-256")
    r.check("Failed archive verification preserves the hot copy", passed.hex(), hot.read_bytes().hex())
    blob.write_bytes(passed)

    # Simulate a replacement captured in the rename window before an interruption.
    replacement = receipt("passed", "later-publication")
    hot.write_bytes(replacement)
    hot.rename(pending)
    rotate(7, "--release-hot", rejected="restored the replacement")
    r.check("Release recovery preserves the producer's replacement", [replacement.hex(), False],
            [hot.read_bytes().hex(), pending.exists()])
    hot.write_bytes(passed)

    # Resume after the durable archive exists and the hot file was renamed aside.
    hot.rename(pending)
    r.check("Retry completes a staged release and subsequent retries are harmless", ["released", "absent", False],
            [rotate(7, "--release-hot")["hot"], rotate(7, "--release-hot")["hot"], pending.exists()])
    r.check("Both original byte sequences still resolve after release", [failed.hex(), passed.hex()],
            [resolved(4).hex(), resolved(7).hex()])
    r.check("Rotation and resolution preserve the exact stored references", before, ledger_references())

    blob.write_bytes(receipt("passed", "tampered-run"))
    resolved(7, rejected="archived receipt SHA-256")
    rotate(7, "--release-hot", rejected="archived receipt SHA-256")
    blob.write_bytes(passed)
    wrong_run = {**new_ref, "run_id": "other-run"}
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("UPDATE ledger_history SET evidence=? WHERE kind='workload' AND id=? AND revision=7",
                   (json.dumps(wrong_run), "receipt-check"))
    resolved(7, rejected="receipt run_id does not match")
    saved = archive / old_ref["sha256"]
    saved.rename(archive / ".fixture-hidden")
    hot.write_bytes(passed)
    resolved(4, rejected="hot receipt SHA-256")
    hot.unlink()
    hot.symlink_to(blob)
    resolved(4, rejected="codexos:")
    r.cli("evidence", "resolve", "workload", "another-item", "7", rejected="no accepted receipt")
    r.cli("evidence", "resolve", "workload", "../receipt-check", "7", rejected="use a lowercase ID")


CASES = (factory, memory, workload, monitor, reliability, adapters, mailbox, permission_preflight,
         durable_memory_index, receipt_archival)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=Path(__file__).with_name("replay-results.json"))
    args = parser.parse_args()
    report = {"schema":1,"started":utc(),"python":sys.version.split()[0],
              "method":"Fresh temporary fleet and factory-created memory-lab for each case. Each CLI invocation starts a new Python process. Inputs and receipts are synthetic.",
              "scope":"Local project behavior. Live chat recall, semantic instruction adherence, scheduler dispatch, and effective runtime model require the separate native checks.",
              "sha256":{p:digest(ROOT/p) for p in MODULES},"cases":[]}
    report["sha256"]["acceptance/replay.py"] = digest(Path(__file__))
    for case in CASES:
        result = {"name":case.__name__,"checks":[],"commands":[]}
        report["cases"].append(result)
        try:
            with tempfile.TemporaryDirectory(prefix="codexos-acceptance-") as raw:
                directory = Path(raw)
                for name in MODULES:
                    shutil.copy2(ROOT/name,directory/name)
                shutil.copytree(ROOT/"templates",directory/"templates")
                r = Replay(directory,result)
                r.cli("init",bot=None)
                r.cli(*CREATE,bot=CHIEF)
                case(r)
            result["status"] = "PASS"
        except Exception as exc:
            result.update(status="FAIL",error=f"{type(exc).__name__}: {exc}")
    report["passed"] = all(c["status"]=="PASS" for c in report["cases"])
    report["finished"] = utc()
    args.output = args.output.resolve()
    with tempfile.NamedTemporaryFile(dir=args.output.parent,mode="w",delete=False) as fp:
        json.dump(report,fp,indent=2)
        fp.write("\n")
    Path(fp.name).replace(args.output)
    for c in report["cases"]:
        print(c["status"],c["name"],len(c["checks"]),"checks",c.get("error",""))
    print(args.output)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
