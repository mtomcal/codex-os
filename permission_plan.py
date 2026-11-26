"""Record bounded permission requests and references to operator decisions."""
import json
import re


def install(db):
    db.execute("""CREATE TABLE IF NOT EXISTS permission_requests (
        kind TEXT NOT NULL, job TEXT NOT NULL, id TEXT NOT NULL,
        action TEXT NOT NULL, target TEXT NOT NULL, required INTEGER NOT NULL,
        decision TEXT CHECK(decision IN ('approved','denied')), evidence TEXT,
        PRIMARY KEY(kind,job,id))""")


def valid_text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 1000


def read(db, kind, key):
    items = [dict(row, required=bool(row["required"])) for row in db.execute("""
        SELECT id,action,target,required,decision,evidence FROM permission_requests
        WHERE kind=? AND job=? ORDER BY id""", (kind, key))]
    required = {item["decision"] for item in items if item["required"]}
    status = "ready"
    if "denied" in required:
        status = "denied"
    elif None in required:
        status = "pending"
    return {"status": status, "items": items}


def annotate(db, kind, key, record):
    plan = read(db, kind, key)
    if plan["items"]:
        record["permissions"] = plan
    return record


def add(db, kind, key, raw, *, allow_new):
    plan = json.loads(raw)
    if not isinstance(plan, list):
        raise ValueError("Permission plan must be a JSON array")
    existing = {item["id"]: item for item in read(db, kind, key)["items"]}
    seen = set()
    for item in plan:
        if (not isinstance(item, dict) or item.keys() != {"id", "action", "target", "required"}
                or not isinstance(item["id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", item["id"])
                or not valid_text(item["action"]) or not valid_text(item["target"])
                or not isinstance(item["required"], bool)):
            raise ValueError("Each permission needs an id, action, target and boolean required")
        request_id = item["id"]
        if request_id in seen:
            raise ValueError(f"Duplicate permission request: {request_id}")
        seen.add(request_id)
        if request_id in existing:
            if any(existing[request_id][field] != value for field, value in item.items()):
                raise ValueError(f"Permission request already has a different scope: {request_id}")
        elif allow_new:
            db.execute("""INSERT INTO permission_requests(kind,job,id,action,target,required)
                VALUES(?,?,?,?,?,?)""", (kind, key, request_id, item["action"], item["target"], item["required"]))
        else:
            raise ValueError("Permission plan is set for this launch")


def decide(db, kind, key, raw):
    decisions = json.loads(raw)
    if not isinstance(decisions, dict):
        raise ValueError("Permission decisions must be a JSON object keyed by permission ID")
    existing = {item["id"]: item for item in read(db, kind, key)["items"]}
    for request_id, item in decisions.items():
        if request_id not in existing:
            raise ValueError(f"Unknown permission request: {request_id}")
        if (not isinstance(item, dict) or item.keys() != {"decision", "evidence"}
                or item["decision"] not in ("approved", "denied") or not valid_text(item["evidence"])):
            raise ValueError("Each permission decision needs approved or denied and an evidence reference")
        previous = existing[request_id]
        if previous["decision"] is None:
            db.execute("""UPDATE permission_requests SET decision=?,evidence=?
                WHERE kind=? AND job=? AND id=?""", (item["decision"], item["evidence"], kind, key, request_id))
        elif (previous["decision"], previous["evidence"]) != (item["decision"], item["evidence"]):
            raise ValueError(f"Permission decision is already recorded: {request_id}")
