import json
from pathlib import Path
from datetime import datetime, timezone


SOFIA_ROOT = Path(__file__).resolve().parents[1]

WORKSPACE_ID = "local.ao"
LOCAL_SITE_PATH = SOFIA_ROOT / "sites" / "local_sites" / "ao"

OPPORTUNITIES_FILE = LOCAL_SITE_PATH / "external_opportunities.json"
MEMORY_FILE = LOCAL_SITE_PATH / "site_content_memory.json"
PROFILE_FILE = LOCAL_SITE_PATH / "local_intelligence_profile.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def check_cannibalization(topic: str, memory_data: dict):
    topic_lower = topic.lower()

    for item in memory_data.get("topics", []):
        existing = item.get("keyword", "").lower()
        if existing and existing in topic_lower:
            return "conflict", f"Possible overlap with existing keyword: {existing}"

    return "clear", "No conflict detected."


def check_local_topic(topic: str, profile: dict):
    topic_lower = topic.lower()

    for item in profile.get("sensitive_topics", []):
        sensitive = item.get("topic", "").lower()
        if sensitive in topic_lower:
            return "requires_review", "Sensitive topic requires examiner validation."

    return "allowed", "No local restriction detected."

def check_language_mismatch(opportunity: dict, profile: dict):
    workspace_language = profile.get("country", {}).get("primary_language", "").lower()
    opportunity_language = opportunity.get("language", "").lower()

    if not workspace_language or not opportunity_language:
        return False, "Language information missing."

    if opportunity_language != workspace_language:
        return True, f"Opportunity language '{opportunity_language}' differs from workspace language '{workspace_language}'."

    return False, "Language matches workspace."

def check_geo_relevance(topic: str, profile: dict):
    topic_lower = topic.lower()

    geo_terms = profile.get("geo_terms", {})
    local_terms = geo_terms.get("local", [])
    foreign_terms = geo_terms.get("foreign", [])

    for term in foreign_terms:
        if term in topic_lower:
            return "low", f"Foreign location detected: {term}"

    for term in local_terms:
        if term in topic_lower:
            return "high", f"Local location detected: {term}"

    return "neutral", "No geographic signal detected."

def main():
    print("=== Sofia: Pre-Validate External Opportunities ===\n")

    opportunities_data = load_json(OPPORTUNITIES_FILE)
    memory_data = load_json(MEMORY_FILE)
    profile = load_json(PROFILE_FILE)

    opportunities = opportunities_data.get("opportunities", [])

    updated = 0

    for opp in opportunities:
        if opp.get("status") != "new":
            continue

        topic = opp.get("topic", "")
        language_mismatch, language_notes = check_language_mismatch(opp, profile)
        geo_relevance, geo_notes = check_geo_relevance(topic, profile)

        cannibal_status, cannibal_notes = check_cannibalization(topic, memory_data)
        local_status, local_notes = check_local_topic(topic, profile)

        opp["cannibalization_status"] = cannibal_status
        opp["cannibalization_notes"] = cannibal_notes

        opp["local_topic_status"] = local_status
        opp["local_topic_notes"] = local_notes

        opp["language_mismatch"] = language_mismatch
        opp["language_notes"] = language_notes
        if language_mismatch:
            opp["priority"] = "low"

        opp["geo_relevance"] = geo_relevance
        opp["geo_notes"] = geo_notes
        if geo_relevance == "low":
            opp["priority"] = "low"

        opp["status"] = "validated"
        opp["review_status"] = "pending_examiner"
        opp["validated_at"] = now()

        updated += 1

        print(f"{opp['id']}: {topic}")
        print(f"  Cannibalization: {cannibal_status}")
        print(f"  Local topic: {local_status}\n")
        print(f"  Language mismatch: {language_mismatch}")
        print(f"  Geo relevance: {geo_relevance}")

    opportunities_data["opportunities"] = opportunities
    save_json(OPPORTUNITIES_FILE, opportunities_data)

    print(f"\nOpportunities pre-validated: {updated}")


if __name__ == "__main__":
    main()