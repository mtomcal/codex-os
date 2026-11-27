"""Track what an end-of-day briefing has delivered."""
import json
import secrets


PAGE = 20


def install(db):
    db.execute("""CREATE TABLE IF NOT EXISTS briefing_checkpoint (
        slot INTEGER PRIMARY KEY CHECK(slot=1),
        history INTEGER NOT NULL DEFAULT 0, finding INTEGER NOT NULL DEFAULT 0,
        staged_token TEXT, staged_page TEXT, delivered_token TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS briefing_decisions (
        kind TEXT, id TEXT, revision INTEGER NOT NULL, PRIMARY KEY(kind,id))""")


def pending(db, now, limit=PAGE):
    checkpoint = db.execute("SELECT history,finding FROM briefing_checkpoint WHERE slot=1").fetchone()
    history, finding = checkpoint if checkpoint else (0, 0)
    changes = [dict(row) for row in db.execute("""
        SELECT h.seq,h.kind,h.id,h.revision,h.state,h.at,h.evidence,i.title,i.owner
        FROM ledger_history h JOIN ledger_items i USING(kind,id)
        WHERE h.seq>? ORDER BY h.seq LIMIT ?""", (history, limit))]
    findings = [dict(row) for row in db.execute("""
        SELECT * FROM monitor_findings WHERE id>? ORDER BY id LIMIT ?""", (finding, limit))]
    decisions = [dict(row) for row in db.execute("""
        SELECT i.kind,i.id,i.revision,i.title,i.owner,i.state,i.next_action,i.due,i.review,i.blocker
        FROM ledger_items i LEFT JOIN briefing_decisions seen USING(kind,id)
        WHERE i.human=1 AND i.state NOT IN ('completed','failed','parked','cancelled')
        AND (i.review IS NULL OR i.review<=?)
        AND (i.due<=? OR i.review<=?)
        AND (i.dependency IS NULL OR EXISTS (
            SELECT 1 FROM ledger_items dependency WHERE dependency.kind='workload'
            AND dependency.id=i.dependency AND dependency.state='completed'))
        AND seen.revision IS NOT i.revision
        ORDER BY coalesce(i.due,i.review),i.kind,i.id LIMIT ?""", (now, now, now, limit))]
    return changes, findings, decisions


def stage(db, now):
    changes, findings, decisions = pending(db, now)
    if not (changes or findings or decisions):
        return None
    token = secrets.token_hex(16)
    page = {
        "history": changes[-1]["seq"] if changes else 0,
        "finding": findings[-1]["id"] if findings else 0,
        "decisions": [(row["kind"], row["id"], row["revision"]) for row in decisions],
    }
    db.execute("""INSERT INTO briefing_checkpoint (slot,staged_token,staged_page) VALUES (1,?,?)
        ON CONFLICT(slot) DO UPDATE SET staged_token=excluded.staged_token, staged_page=excluded.staged_page""",
        (token, json.dumps(page)))
    for record in [*changes, *findings]:
        record["evidence"] = json.loads(record["evidence"]) if record["evidence"] else None
    return {"delivery_token": token, "work_changes": changes, "findings": findings, "due_decisions": decisions}


def delivered(db, token):
    row = db.execute("SELECT * FROM briefing_checkpoint WHERE slot=1").fetchone()
    if row and row["delivered_token"] == token:
        return {"delivered": True}
    if not row or row["staged_token"] != token:
        raise ValueError("Read the current pending briefing after the delivery token changed")
    page = json.loads(row["staged_page"])
    db.execute("""UPDATE briefing_checkpoint SET history=max(history,?),finding=max(finding,?),
                  delivered_token=staged_token,staged_token=NULL,staged_page=NULL WHERE slot=1""",
               (page["history"], page["finding"]))
    db.executemany("""INSERT INTO briefing_decisions (kind,id,revision) VALUES (?,?,?)
        ON CONFLICT(kind,id) DO UPDATE SET revision=max(briefing_decisions.revision,excluded.revision)""",
                   page["decisions"])
    return {"delivered": True}
