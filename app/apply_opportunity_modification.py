import json
import sys
from pathlib import Path
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = ROOT / "data" / "workspaces.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def find_workspace(workspaces, workspace_id):
    for workspace in workspaces.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def find_opportunity(opportunities, opportunity_id):
    for opportunity in opportunities:
        opp_id = opportunity.get("id") or opportunity.get("opportunity_id")
        if opp_id == opportunity_id:
            return opportunity
    return None


def check_cannibalization(topic, memory_data):
    topic_lower = topic.lower()

    for item in memory_data.get("topics", []):
        existing = item.get("keyword", "").lower()
        if existing and existing in topic_lower:
            return "conflict", f"Possible overlap with existing keyword: {existing}"

    return "clear", "No conflict detected."


def check_local_topic(topic, profile):
    topic_lower = topic.lower()

    for item in profile.get("sensitive_topics", []):
        sensitive = item.get("topic", "").lower()
        if sensitive and sensitive in topic_lower:
            return "requires_review", "Sensitive topic requires examiner validation."

    return "allowed", "No local restriction detected."


def check_geo_relevance(topic, profile):
    topic_lower = topic.lower()

    geo_terms = profile.get("geo_terms", {})
    local_terms = geo_terms.get("local", [])
    foreign_terms = geo_terms.get("foreign", [])

    for term in foreign_terms:
        if term.lower() in topic_lower:
            return "low", f"Foreign location detected: {term}"

    for term in local_terms:
        if term.lower() in topic_lower:
            return "high", f"Local location detected: {term}"

    return "neutral", "No geographic signal detected."


def create_modified_topic(original_topic, examiner_comment, language):
    comment_lower = examiner_comment.lower()

    if "corporate fraud" in comment_lower or "fraude corporativa" in comment_lower:
        if str(language).startswith("pt"):
            return "teste de polígrafo para investigação de fraude corporativa"
        if str(language).startswith("es"):
            return "prueba de polígrafo para investigación de fraude corporativo"
        if str(language).startswith("fr"):
            return "test polygraphique pour enquête de fraude d’entreprise"
        return "polygraph test for corporate fraud investigation"

    if "infidelity" in comment_lower or "infidelidade" in comment_lower or "infidelidad" in comment_lower:
        if str(language).startswith("pt"):
            return "teste de polígrafo para casos de infidelidade"
        if str(language).startswith("es"):
            return "prueba de polígrafo para casos de infidelidad"
        if str(language).startswith("fr"):
            return "test polygraphique pour cas d’infidélité"
        return "polygraph test for infidelity cases"

    # Fallback: keep original topic but mark it as modified by examiner direction.
    return original_topic


def create_business_reason(topic, examiner_comment):
    return (
        "Modified after examiner feedback. "
        f"New suggested angle: {topic}. "
        f"Examiner instruction: {examiner_comment}"
    )


def main():
    if len(sys.argv) < 4:
        print("Usage:")
        print('python app/apply_opportunity_modification.py WORKSPACE_ID OPP-ID "examiner instruction"')
        return

    workspace_id = sys.argv[1]
    opportunity_id = sys.argv[2]
    examiner_comment = " ".join(sys.argv[3:]).strip()

    if not examiner_comment:
        print("Examiner modification instruction is empty.")
        return

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, workspace_id)

    if not workspace:
        print(f"Workspace not found: {workspace_id}")
        return

    folder_path = workspace.get("folder_path")
    if not folder_path:
        print(f"Workspace has no folder_path: {workspace_id}")
        return

    workspace_path = ROOT / folder_path
    opportunities_path = workspace_path / "external_opportunities.json"
    memory_path = workspace_path / "site_content_memory.json"
    profile_path = workspace_path / "local_intelligence_profile.json"

    if not opportunities_path.exists():
        print(f"external_opportunities.json not found: {opportunities_path}")
        return

    opportunities_data = load_json(opportunities_path)
    opportunities = opportunities_data.get("opportunities", [])

    opportunity = find_opportunity(opportunities, opportunity_id)

    if not opportunity:
        print(f"Opportunity not found: {opportunity_id}")
        return

    memory_data = load_json(memory_path) if memory_path.exists() else {"topics": []}
    profile = load_json(profile_path) if profile_path.exists() else {}

    timestamp = now_iso()
    language = opportunity.get("language") or workspace.get("language", "en")

    previous_snapshot = {
        "topic": opportunity.get("topic"),
        "business_reason": opportunity.get("business_reason"),
        "status": opportunity.get("status"),
        "review_status": opportunity.get("review_status"),
        "priority": opportunity.get("priority"),
        "cannibalization_status": opportunity.get("cannibalization_status"),
        "cannibalization_notes": opportunity.get("cannibalization_notes"),
    }

    original_topic = opportunity.get("topic", "")
    modified_topic = create_modified_topic(
        original_topic=original_topic,
        examiner_comment=examiner_comment,
        language=language
    )

    opportunity["topic"] = modified_topic
    opportunity["business_reason"] = create_business_reason(modified_topic, examiner_comment)
    opportunity["status"] = "validated"
    opportunity["review_status"] = "pending_examiner_review"
    opportunity["telegram_notified"] = False
    opportunity["updated_at"] = timestamp
    opportunity["modified_at"] = timestamp
    opportunity["modified_by"] = "sofia"
    opportunity["examiner_decision"] = None
    opportunity["examiner_comment"] = None
    opportunity["examiner_decision_at"] = None

    cannibal_status, cannibal_notes = check_cannibalization(modified_topic, memory_data)
    local_status, local_notes = check_local_topic(modified_topic, profile)
    geo_relevance, geo_notes = check_geo_relevance(modified_topic, profile)

    opportunity["cannibalization_status"] = cannibal_status
    opportunity["cannibalization_notes"] = cannibal_notes
    opportunity["local_topic_status"] = local_status
    opportunity["local_topic_notes"] = local_notes
    opportunity["geo_relevance"] = geo_relevance
    opportunity["geo_notes"] = geo_notes

    if cannibal_status == "conflict":
        opportunity["priority"] = "low"
        opportunity["risk_notes"] = [
            "Modified opportunity may overlap with existing content.",
            cannibal_notes
        ]

    if "modification_history" not in opportunity:
        opportunity["modification_history"] = []

    opportunity["modification_history"].append({
        "modified_at": timestamp,
        "modified_by": "sofia",
        "examiner_instruction": examiner_comment,
        "previous": previous_snapshot,
        "new_topic": modified_topic,
        "cannibalization_status": cannibal_status,
        "cannibalization_notes": cannibal_notes,
        "local_topic_status": local_status,
        "local_topic_notes": local_notes
    })

    save_json(opportunities_path, opportunities_data)

    print("Opportunity modification loop completed successfully.")
    print(f"Workspace: {workspace_id}")
    print(f"Opportunity: {opportunity_id}")
    print(f"New topic: {modified_topic}")
    print(f"Cannibalization: {cannibal_status}")
    print(f"Local topic status: {local_status}")
    print("Review status: pending_examiner_review")
    print("Telegram notification reset: false")


if __name__ == "__main__":
    main()