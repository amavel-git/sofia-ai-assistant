import json
from pathlib import Path
from datetime import datetime, timezone


SOFIA_ROOT = Path(__file__).resolve().parents[1]

WORKSPACE_ID = "local.ao"
WORKSPACE_TYPE = "local_market"
WORKSPACE_PATH = "sites/local_sites/ao"

LOCAL_SITE_PATH = SOFIA_ROOT / WORKSPACE_PATH
OPPORTUNITIES_FILE = LOCAL_SITE_PATH / "external_opportunities.json"
INTAKE_FILE = SOFIA_ROOT / "sites" / "content_intake.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def get_next_intake_id(content_ideas: list) -> str:
    max_num = 0

    for item in content_ideas:
        intake_id = item.get("intake_id", "")
        if intake_id.startswith("INTAKE-"):
            try:
                num = int(intake_id.replace("INTAKE-", ""))
                max_num = max(max_num, num)
            except ValueError:
                continue

    return f"INTAKE-{max_num + 1:04d}"


def already_converted(content_ideas: list, opportunity_id: str) -> bool:
    for item in content_ideas:
        if item.get("source_opportunity_id") == opportunity_id:
            return True
    return False


def build_intake_from_opportunity(opportunity: dict, intake_id: str) -> dict:
    related_keywords = opportunity.get("related_keywords", [])
    target_keyword = related_keywords[0] if related_keywords else opportunity.get("topic", "")

    return {
        "intake_id": intake_id,
        "created_at": today(),
        "created_by": "sofia_external_intelligence",
        "workspace_type": WORKSPACE_TYPE,
        "workspace_id": WORKSPACE_ID,
        "workspace_path": WORKSPACE_PATH,
        "language": opportunity.get("language", "pt"),
        "site_target": "https://poligrafoangola.com",
        "content_type": opportunity.get("recommended_content_type", "service_page"),
        "idea_title": opportunity.get("topic", ""),
        "idea_summary": opportunity.get("business_reason", ""),
        "target_keyword": target_keyword,
        "secondary_keywords": related_keywords[1:],
        "search_intent": opportunity.get("intent_type", "informational_transactional"),
        "suggested_slug": "",
        "source": "external_intelligence",
        "source_platform": opportunity.get("source", ""),
        "source_opportunity_id": opportunity.get("id", ""),
        "priority": opportunity.get("priority", "normal"),
        "status": "new",
        "cannibalization_check": {
            "checked": False,
            "result": "not_checked",
            "notes": ""
        },
        "draft_conversion": {
            "converted": False,
            "draft_id": "",
            "converted_at": ""
        },
        "review_routing": {
            "target_queue": "ao_local_review_queue",
            "routed": False,
            "routed_at": ""
        },
        "notes": "Created automatically from approved Sofia external opportunity.",

        "seo_brief": opportunity.get("seo_brief", {}),
        "content_strategy_brief": opportunity.get("content_strategy_brief", {}),
        "draft_input": opportunity.get("draft_input", {})
    }


def main():
    print("=== Sofia: Convert Approved Opportunities to Intake ===\n")

    opportunities_data = load_json(OPPORTUNITIES_FILE)
    intake_data = load_json(INTAKE_FILE)

    opportunities = opportunities_data.get("opportunities", [])
    content_ideas = intake_data.get("content_ideas", [])

    approved = [
        opp for opp in opportunities
        if opp.get("status") == "approved"
        and opp.get("review_status") == "approved_by_examiner"
    ]

    if not approved:
        print("No approved opportunities ready for intake conversion.")
        return

    created_count = 0

    for opp in approved:
        opportunity_id = opp.get("id", "")

        if already_converted(content_ideas, opportunity_id):
            print(f"Skipped {opportunity_id}: already exists in content_intake.json")
            continue

        intake_id = get_next_intake_id(content_ideas)
        intake_entry = build_intake_from_opportunity(opp, intake_id)

        content_ideas.append(intake_entry)

        opp["status"] = "converted_to_intake"
        opp["review_status"] = "intake_created"
        opp["intake_id"] = intake_id
        opp["converted_to_intake_at"] = now_utc()

        print(f"Created {intake_id} from {opportunity_id}")
        created_count += 1

    intake_data["content_ideas"] = content_ideas
    opportunities_data["opportunities"] = opportunities

    save_json(INTAKE_FILE, intake_data)
    save_json(OPPORTUNITIES_FILE, opportunities_data)

    print(f"\nConversion completed.")
    print(f"New intake entries created: {created_count}")


if __name__ == "__main__":
    main()