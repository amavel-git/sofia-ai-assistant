import json
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]

WORKSPACE_ID = "local.ao"
LOCAL_SITE_PATH = SOFIA_ROOT / "sites" / "local_sites" / "ao"

OPPORTUNITIES_FILE = LOCAL_SITE_PATH / "external_opportunities.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def format_list(items):
    if not items:
        return "None"
    return "\n".join([f"- {item}" for item in items])


def generate_message(opportunity: dict) -> str:
    country = opportunity.get("country", "N/A")
    topic = opportunity.get("topic", "N/A")
    opp_type = opportunity.get("opportunity_type", "N/A")
    content_type = opportunity.get("recommended_content_type", "N/A")
    priority = opportunity.get("priority", "N/A")

    business_reason = opportunity.get("business_reason", "")
    risk_notes = opportunity.get("risk_notes", [])

    message = f"""
[SOFIA – CONTENT OPPORTUNITY]

Country: {country}
Topic: {topic}
Type: {opp_type}
Recommended Content: {content_type}
Priority: {priority}

Reason:
{business_reason if business_reason else "No business reason provided."}

Risk Notes:
{format_list(risk_notes)}

Status:
Awaiting examiner validation before draft creation

Action Required:
Please confirm:
1. APPROVE
2. MODIFY
3. REJECT

Reply with:
APPROVE / MODIFY / REJECT
""".strip()

    return message


def main():
    print("=== Sofia: Generate Opportunity Review Messages ===\n")

    data = load_json(OPPORTUNITIES_FILE)
    opportunities = data.get("opportunities", [])

    pending = [
        opp for opp in opportunities
        if opp.get("status") == "validated"
        and opp.get("review_status") in ["pending_examiner", "pending"]
    ]

    if not pending:
        print("No opportunities pending examiner review.")
        return

    print(f"Found {len(pending)} opportunity(ies) pending review.\n")

    for opp in pending:
        print("=" * 60)
        print(generate_message(opp))
        print("=" * 60)
        print()


if __name__ == "__main__":
    main()