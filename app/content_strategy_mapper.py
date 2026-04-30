import json
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]

WORKSPACE_ID = "local.ao"
LOCAL_SITE_PATH = SOFIA_ROOT / "sites" / "local_sites" / "ao"

OPPORTUNITIES_FILE = LOCAL_SITE_PATH / "external_opportunities.json"


# Concept → Strategy Mapping
CONCEPT_STRATEGY = {
    "does_polygraph_work_query": {
        "content_type": "blog_post",
        "page_type": "informational",
        "seo_goal": "educational_authority"
    },
    "polygraph_reliability_query": {
        "content_type": "blog_post",
        "page_type": "informational",
        "seo_goal": "trust_building"
    },
    "polygraph_test_process_query": {
        "content_type": "blog_post",
        "page_type": "informational",
        "seo_goal": "explain_service"
    },
    "price_or_cost_query": {
        "content_type": "landing_page",
        "page_type": "transactional",
        "seo_goal": "conversion"
    },
    "company_or_corporate_testing_query": {
        "content_type": "service_page",
        "page_type": "transactional",
        "seo_goal": "lead_generation"
    },
    "relationship_or_infidelity_testing_query": {
        "content_type": "service_page",
        "page_type": "transactional",
        "seo_goal": "lead_generation"
    }
}


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    print("=== Sofia: Content Strategy Mapping ===\n")

    data = load_json(OPPORTUNITIES_FILE)
    opportunities = data.get("opportunities", [])

    updated = 0

    for opp in opportunities:
        if opp.get("status") != "validated":
            continue

        concept = opp.get("cluster_concept")

        if not concept:
            continue

        strategy = CONCEPT_STRATEGY.get(concept)

        if not strategy:
            continue

        opp["strategy"] = {
            "content_type": strategy["content_type"],
            "page_type": strategy["page_type"],
            "seo_goal": strategy["seo_goal"]
        }

        # Update recommended content type
        opp["recommended_content_type"] = strategy["content_type"]

        updated += 1

        print(f"{opp['id']}: {opp.get('topic')}")
        print(f"  Concept: {concept}")
        print(f"  Strategy: {strategy}\n")

    data["opportunities"] = opportunities
    save_json(OPPORTUNITIES_FILE, data)

    print(f"\nOpportunities mapped: {updated}")


if __name__ == "__main__":
    main()