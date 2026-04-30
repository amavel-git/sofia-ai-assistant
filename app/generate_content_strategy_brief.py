import json
import sys
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]

WORKSPACE_ID = sys.argv[1] if len(sys.argv) > 1 else "local.ao"

WORKSPACE_MAP = {
    "local.ao": "sites/local_sites/ao",
    "local.es": "sites/local_sites/es",
    "global.polar": "sites/global_sites/polar"
}

if WORKSPACE_ID not in WORKSPACE_MAP:
    raise ValueError(f"Unknown workspace: {WORKSPACE_ID}")

LOCAL_SITE_PATH = SOFIA_ROOT / WORKSPACE_MAP[WORKSPACE_ID]

OPPORTUNITIES_FILE = LOCAL_SITE_PATH / "external_opportunities.json"
LANGUAGE_PROFILE_FILE = LOCAL_SITE_PATH / "language_profile.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_template_type(content_type: str) -> str:
    if content_type in ["landing_page", "service_page"]:
        return "service"
    return "blog"


def build_strategy_brief(opp: dict, language_profile: dict) -> dict:
    content_type = opp.get("recommended_content_type", "blog_post")
    concept = opp.get("cluster_concept", "")
    geo_relevance = opp.get("geo_relevance", "neutral")
    language_mismatch = opp.get("language_mismatch", False)

    templates = language_profile.get("content_strategy_templates", {})
    template_type = get_template_type(content_type)
    base_template = templates.get(template_type, {})

    warnings = []

    if geo_relevance == "low":
        warnings.append("This topic may refer to a foreign location and should be reviewed before drafting.")

    if language_mismatch:
        warnings.append("The detected language may not match the workspace language.")

    concept_warnings = templates.get("warnings_by_concept", {}).get(concept, [])
    warnings.extend(concept_warnings)

    recommended_angle = templates.get("recommended_angles_by_concept", {}).get(
        concept,
        base_template.get("recommended_angle", "")
    )

    faq_templates = language_profile.get("faq_templates", {})

    return {
        "content_goal": base_template.get("content_goal", ""),
        "target_audience": base_template.get("target_audience", ""),
        "recommended_angle": recommended_angle,
        "required_sections": base_template.get("required_sections", []),
        "warnings": warnings,
        "conversion_goal": base_template.get("conversion_goal", ""),
        "internal_linking_notes": templates.get("internal_linking_notes", []),

        # FAQ rules from site language profile
        "faq_required": faq_templates.get("required", True),
        "faq_guidelines": faq_templates,

        "source_topic": opp.get("topic", "")
    }


def main():
    print("=== Sofia: Generate Content Strategy Brief ===\n")

    opportunities_data = load_json(OPPORTUNITIES_FILE)
    language_profile = load_json(LANGUAGE_PROFILE_FILE)

    opportunities = opportunities_data.get("opportunities", [])
    updated = 0

    for opp in opportunities:
        if opp.get("status") != "validated":
            continue

        if opp.get("content_strategy_brief"):
            continue

        opp["content_strategy_brief"] = build_strategy_brief(opp, language_profile)
        updated += 1

        print(f"{opp.get('id')}: {opp.get('topic')}")
        print(f"  Content type: {opp.get('recommended_content_type')}")
        print("  Strategy brief created\n")

    opportunities_data["opportunities"] = opportunities
    save_json(OPPORTUNITIES_FILE, opportunities_data)

    print(f"Content strategy briefs created: {updated}")


if __name__ == "__main__":
    main()