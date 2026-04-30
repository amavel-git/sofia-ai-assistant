import json
from pathlib import Path
from datetime import datetime, timezone


SOFIA_ROOT = Path(__file__).resolve().parents[1]

WORKSPACE_ID = "local.ao"
LOCAL_SITE_PATH = SOFIA_ROOT / "sites" / "local_sites" / "ao"

OPPORTUNITIES_FILE = LOCAL_SITE_PATH / "external_opportunities.json"


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


def build_draft_input(opp: dict) -> dict:
    seo = opp.get("seo_brief", {})
    strategy = opp.get("content_strategy_brief", {})

    return {
        "generated_at": now(),
        "source": "sofia_external_intelligence",
        "opportunity_id": opp.get("id", ""),
        "workspace_id": WORKSPACE_ID,
        "language": opp.get("language", ""),
        "country": opp.get("country", ""),
        "topic": opp.get("topic", ""),
        "content_type": opp.get("recommended_content_type", ""),
        "intent_type": opp.get("intent_type", ""),
        "priority": opp.get("priority", ""),
        "detected_concepts": opp.get("detected_concepts", []),
        "cluster_concept": opp.get("cluster_concept", ""),
        "related_keywords": opp.get("related_keywords", []),
        "seo": {
            "focus_keyphrase": seo.get("focus_keyphrase", ""),
            "page_title": seo.get("page_title", ""),
            "seo_title": seo.get("seo_title", ""),
            "slug": seo.get("slug", ""),
            "meta_description": seo.get("meta_description", ""),
            "suggested_headings": seo.get("suggested_headings", {}),
            "image_alt_text": seo.get("image_alt_text", ""),
            "image_filename": seo.get("image_filename", "")
        },
        "strategy": {
            "content_goal": strategy.get("content_goal", ""),
            "target_audience": strategy.get("target_audience", ""),
            "recommended_angle": strategy.get("recommended_angle", ""),
            "required_sections": strategy.get("required_sections", []),
            "warnings": strategy.get("warnings", []),
            "conversion_goal": strategy.get("conversion_goal", ""),
            "internal_linking_notes": strategy.get("internal_linking_notes", [])
        },
        "quality_controls": {
            "avoid_legal_guarantees": True,
            "avoid_absolute_accuracy_claims": True,
            "avoid_unverified_local_law_claims": True,
            "requires_examiner_review_before_publication": True
        }
    }


def main():
    print("=== Sofia: Generate Draft Input ===\n")

    data = load_json(OPPORTUNITIES_FILE)
    opportunities = data.get("opportunities", [])

    updated = 0

    for opp in opportunities:
        if opp.get("status") != "validated":
            continue

        if opp.get("draft_input"):
            continue

        if not opp.get("seo_brief"):
            print(f"Skipped {opp.get('id')}: missing seo_brief")
            continue

        if not opp.get("content_strategy_brief"):
            print(f"Skipped {opp.get('id')}: missing content_strategy_brief")
            continue

        opp["draft_input"] = build_draft_input(opp)
        updated += 1

        print(f"{opp.get('id')}: {opp.get('topic')}")
        print("  Draft input created\n")

    data["opportunities"] = opportunities
    save_json(OPPORTUNITIES_FILE, data)

    print(f"Draft inputs created: {updated}")


if __name__ == "__main__":
    main()