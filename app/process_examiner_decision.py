import json
import sys
from pathlib import Path
from datetime import datetime, timezone


SOFIA_ROOT = Path(__file__).resolve().parents[1]

WORKSPACE_ID = "local.ao"
LOCAL_SITE_PATH = SOFIA_ROOT / "sites" / "local_sites" / "ao"

OPPORTUNITIES_FILE = LOCAL_SITE_PATH / "external_opportunities.json"


VALID_DECISIONS = ["APPROVE", "MODIFY", "REJECT"]


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def process_decision(opportunity: dict, decision: str):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    if decision == "APPROVE":
        opportunity["status"] = "approved"
        opportunity["review_status"] = "approved_by_examiner"
        opportunity["approved_at"] = now

    elif decision == "MODIFY":
        opportunity["status"] = "needs_modification"
        opportunity["review_status"] = "modification_requested"
        opportunity["modified_at"] = now

    elif decision == "REJECT":
        opportunity["status"] = "rejected"
        opportunity["review_status"] = "rejected_by_examiner"
        opportunity["rejected_at"] = now

    return opportunity


def main():
    print("=== Sofia: Process Examiner Decision ===\n")

    if len(sys.argv) != 3:
        print("Usage:")
        print("python app/process_examiner_decision.py <OPPORTUNITY_ID> <DECISION>")
        print("Example:")
        print("python app/process_examiner_decision.py OPP-AO-001 APPROVE")
        return

    opportunity_id = sys.argv[1]
    decision = sys.argv[2].upper()

    if decision not in VALID_DECISIONS:
        print(f"Invalid decision: {decision}")
        print(f"Valid options: {VALID_DECISIONS}")
        return

    data = load_json(OPPORTUNITIES_FILE)
    opportunities = data.get("opportunities", [])

    found = False

    for i, opp in enumerate(opportunities):
        if opp.get("id") == opportunity_id:
            print(f"Found opportunity: {opportunity_id}")
            print(f"Topic: {opp.get('topic')}\n")

            updated = process_decision(opp, decision)
            opportunities[i] = updated

            found = True
            break

    if not found:
        print(f"Opportunity not found: {opportunity_id}")
        return

    data["opportunities"] = opportunities
    save_json(OPPORTUNITIES_FILE, data)

    print(f"Decision '{decision}' applied successfully.")
    print(f"Updated status: {updated.get('status')}")
    print(f"Review status: {updated.get('review_status')}")


if __name__ == "__main__":
    main()