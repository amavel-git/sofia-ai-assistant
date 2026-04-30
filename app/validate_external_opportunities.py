import json
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]

GLOBAL_SOURCES_FILE = SOFIA_ROOT / "data" / "opportunity_sources.json"
GLOBAL_TYPES_FILE = SOFIA_ROOT / "data" / "opportunity_types.json"

# Test workspace for now
WORKSPACE_ID = "local.ao"
LOCAL_SITE_PATH = SOFIA_ROOT / "sites" / "local_sites" / "ao"

LOCAL_PROFILE_FILE = LOCAL_SITE_PATH / "local_intelligence_profile.json"
LOCAL_OPPORTUNITIES_FILE = LOCAL_SITE_PATH / "external_opportunities.json"


REQUIRED_OPPORTUNITY_FIELDS = [
    "id",
    "created_at",
    "country",
    "language",
    "source",
    "topic",
    "opportunity_type",
    "recommended_content_type",
    "intent_type",
    "priority",
    "confidence",
    "status",
    "cannibalization_status",
    "local_topic_status",
    "review_status"
]


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}") from e


def validate_workspace_id(data: dict, expected_workspace_id: str, file_label: str) -> list:
    errors = []

    found_workspace_id = data.get("workspace_id")
    if found_workspace_id != expected_workspace_id:
        errors.append(
            f"{file_label}: workspace_id mismatch. "
            f"Expected '{expected_workspace_id}', found '{found_workspace_id}'."
        )

    return errors


def validate_opportunity(
    opportunity: dict,
    valid_sources: set,
    valid_types: set,
    sensitive_topics: list
) -> list:
    errors = []
    warnings = []

    opp_id = opportunity.get("id", "UNKNOWN")

    for field in REQUIRED_OPPORTUNITY_FIELDS:
        if field not in opportunity:
            errors.append(f"{opp_id}: missing required field '{field}'.")

    source = opportunity.get("source")
    if source and source not in valid_sources:
        errors.append(f"{opp_id}: invalid source '{source}'.")

    opportunity_type = opportunity.get("opportunity_type")
    if opportunity_type and opportunity_type not in valid_types:
        errors.append(f"{opp_id}: invalid opportunity_type '{opportunity_type}'.")

    topic = opportunity.get("topic", "").strip().lower()

    for sensitive in sensitive_topics:
        sensitive_topic = sensitive.get("topic", "").strip().lower()
        sensitive_status = sensitive.get("status", "")

        if topic == sensitive_topic:
            if sensitive_status == "requires_examiner_review":
                if opportunity.get("local_topic_status") != "requires_review":
                    warnings.append(
                        f"{opp_id}: topic is sensitive and should have "
                        f"local_topic_status='requires_review'."
                    )

                if opportunity.get("review_status") not in [
                    "pending_examiner",
                    "pending",
                    "pending_review"
                ]:
                    warnings.append(
                        f"{opp_id}: sensitive topic should remain pending examiner review."
                    )

    if opportunity.get("cannibalization_status") == "unchecked":
        warnings.append(f"{opp_id}: cannibalization_status is still unchecked.")

    if opportunity.get("local_topic_status") == "unchecked":
        warnings.append(f"{opp_id}: local_topic_status is still unchecked.")

    return errors, warnings


def main():
    print("=== Sofia: Validate External Opportunities ===\n")

    all_errors = []
    all_warnings = []

    sources_data = load_json(GLOBAL_SOURCES_FILE)
    types_data = load_json(GLOBAL_TYPES_FILE)
    local_profile = load_json(LOCAL_PROFILE_FILE)
    opportunities_data = load_json(LOCAL_OPPORTUNITIES_FILE)

    all_errors.extend(
        validate_workspace_id(local_profile, WORKSPACE_ID, "local_intelligence_profile.json")
    )
    all_errors.extend(
        validate_workspace_id(opportunities_data, WORKSPACE_ID, "external_opportunities.json")
    )

    valid_sources = set(sources_data.get("sources", {}).keys())
    valid_types = set(types_data.get("opportunity_types", {}).keys())
    sensitive_topics = local_profile.get("sensitive_topics", [])

    opportunities = opportunities_data.get("opportunities", [])

    if not opportunities:
        all_warnings.append("No opportunities found.")

    print(f"Workspace: {WORKSPACE_ID}")
    print(f"Local path: {LOCAL_SITE_PATH}")
    print(f"Opportunities found: {len(opportunities)}\n")

    for opportunity in opportunities:
        opp_id = opportunity.get("id", "UNKNOWN")
        topic = opportunity.get("topic", "NO TOPIC")
        status = opportunity.get("status", "NO STATUS")
        review_status = opportunity.get("review_status", "NO REVIEW STATUS")

        errors, warnings = validate_opportunity(
            opportunity=opportunity,
            valid_sources=valid_sources,
            valid_types=valid_types,
            sensitive_topics=sensitive_topics
        )

        all_errors.extend(errors)
        all_warnings.extend(warnings)

        print(f"- {opp_id}")
        print(f"  Topic: {topic}")
        print(f"  Status: {status}")
        print(f"  Review: {review_status}")

        if errors:
            print("  Result: ERROR")
        elif warnings:
            print("  Result: WARNING")
        else:
            print("  Result: OK")

        print()

    print("=== Validation Summary ===")

    if all_errors:
        print("\nErrors:")
        for error in all_errors:
            print(f"- {error}")
    else:
        print("\nErrors: none")

    if all_warnings:
        print("\nWarnings:")
        for warning in all_warnings:
            print(f"- {warning}")
    else:
        print("\nWarnings: none")

    if not all_errors:
        print("\nValidation completed successfully.")
    else:
        print("\nValidation completed with errors.")


if __name__ == "__main__":
    main()