"""Grade native coordinator and worker timing, delivery and cleanup evidence."""
import json
from pathlib import Path
import sys


def checks(e):
    intake, answer, worker, delivery = [e[name] for name in ("intake", "answer", "worker", "delivery")]
    row = e["ledger"]
    return {
        "Independent bound worker": worker["thread"] != answer["thread"] and row["worker"] == worker["thread"],
        "Intake returned while worker ran": worker["start"] <= intake["end"] < worker["end"],
        "Primary completed another turn during worker execution":
            intake["thread"] == answer["thread"] == delivery["thread"] and
            intake["end"] <= answer["start"] < answer["end"] < worker["end"] and
            e["during"]["status"] == "inProgress" and e["calibration"] in answer["reply"] and "lab-seed" in answer["reply"],
        "Coordinator verified and delivered completed work":
            delivery["start"] >= worker["end"] and row["decision"] == "accepted" and
            row["report"] and row["review"] and "42" in delivery["reply"],
        "Worker archived and artifact survived":
            e["archived_id"] == worker["thread"] and row["state"] == "cleaned" and
            row["cleanup"] and e["result_after_archive"] == 42,
    }


if __name__ == "__main__":
    results = checks(json.loads(Path(sys.argv[1]).read_text()))
    for label, passed in results.items():
        print("PASS" if passed else "FAIL", label)
    sys.exit(0 if all(results.values()) else 1)
