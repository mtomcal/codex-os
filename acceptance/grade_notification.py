"""Grade the two-snapshot live worker notification trial."""
import json
from pathlib import Path
import re
import sys


def checks(evidence):
    chief, worker = evidence["chief"], evidence["worker"]
    sends = evidence["sends"]
    trigger = evidence["trigger"]
    receipt = trigger.get("output", {}).get("text", "")
    archive = evidence["archive"]
    lookup = evidence.get("archive_lookup") or {}
    row = evidence["ledger"]
    numbers = {"17", "29", "46"}
    return {
        "Bound worker sent one completion to its Chief": (
            chief != worker and row["worker"] == worker and len(sends) == 1
            and sends[0]["tool"] == "send_message_to_thread" and sends[0]["status"] == "completed"
            and sends[0]["arguments"]["threadId"] == chief
            and row["key"] in sends[0]["arguments"]["prompt"]
        ),
        "The native worker message started the review turn": (
            trigger["type"] == "functionCallOutput" and trigger["name"] == "send_message_to_thread"
            and receipt.startswith("<codex_delegation>")
            and f"<source_thread_id>{worker}</source_thread_id>" in receipt
            and row["key"] in receipt
        ),
        "Chief read the sources and delivered the verified result": (
            any(item.get("exitCode") == 0 and item["output"]["text"].splitlines()
                == ["Restored records: 17", "Restored records: 29"] for item in evidence["source_reads"])
            and numbers <= set(re.findall(r"\b\d+\b", evidence["delivery"]))
            and row["decision"] == "accepted" and bool(row["review"])
        ),
        "Chief archived the bound worker and retained the report": (
            archive["tool"] == "set_thread_archived" and archive["status"] == "completed"
            and archive["arguments"]["archived"] is True and archive["arguments"]["threadId"] == worker
            and lookup.get("id") == worker and bool(row.get("host")) and lookup.get("hostId") == row["host"]
            and row["state"] == "cleaned" and bool(row["cleanup"])
            and numbers <= set(re.findall(r"\b\d+\b", evidence["retained_report"]))
        ),
    }


if __name__ == "__main__":
    results = checks(json.loads(Path(sys.argv[1]).read_text()))
    for name, passed in results.items():
        print("PASS" if passed else "FAIL", name)
    sys.exit(0 if all(results.values()) else 1)
