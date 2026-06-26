import argparse
import json
from pathlib import Path
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = ROOT / "data" / "workspaces.json"


IGNORE_TOPICS = {
    "general_polygraph",
    "faq",
    "pricing"
}


HIGH_VALUE_TOPICS = {
    "infidelity",
    "internal_theft",
    "human_resources",
    "legal_defense",
    "sexual_offense",
    "training",
    "procedure",
    "question_formulation",
    "countermeasures",
    "false_positives",
    "inconclusive_results",
    "anxiety_medication",
    "methodology",
    "technology",
    "science_reliability",
    "security_services"
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_workspace(workspaces, workspace_id):
    for workspace in workspaces.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def get_workspace_folder(workspace):
    return ROOT / workspace["folder_path"]


def load_our_topics(workspace_folder):
    path = workspace_folder / "site_content_memory.json"
    data = load_json(path)

    topic_counts = {}

    for item in data.get("published_content", []):
        topic = item.get("topic")
        if not topic:
            continue
        topic_counts[topic] = topic_counts.get(topic, 0) + 1

    return topic_counts


def load_competitor_inventories(workspace_folder):
    inventory_dir = workspace_folder / "competitor_inventories"

    if not inventory_dir.exists():
        return []

    inventories = []

    for path in sorted(inventory_dir.glob("*.json")):
        try:
            data = load_json(path)
            inventories.append(data)
        except Exception:
            continue

    return inventories


def aggregate_competitor_topics(inventories):
    topic_data = {}

    for inv in inventories:
        competitor = inv.get("competitor", {}) or {}
        name = competitor.get("name") or competitor.get("domain") or "unknown"
        domain = competitor.get("domain", "")

        topic_counts = inv.get("statistics", {}).get("topic_counts", {}) or {}

        for topic, count in topic_counts.items():
            if topic in IGNORE_TOPICS:
                continue

            record = topic_data.setdefault(topic, {
                "topic": topic,
                "competitor_coverage_count": 0,
                "total_pages": 0,
                "competitors_covering": []
            })

            record["competitor_coverage_count"] += 1
            record["total_pages"] += count
            record["competitors_covering"].append({
                "name": name,
                "domain": domain,
                "pages": count
            })

    return topic_data


def get_opportunity_rules(workspace_folder):
    path = workspace_folder / "market_intelligence.json"

    if not path.exists():
        return {}

    try:
        data = load_json(path)
        return data.get("opportunity_rules", {}) or {}
    except Exception:
        return {}


def recommend_action(topic, our_count, competitor_coverage_count, competitor_total_pages, opportunity_rules=None):
    opportunity_rules = opportunity_rules or {}

    out_of_scope_topics = set(opportunity_rules.get("out_of_scope_topics", []) or [])
    sensitive_topics = set(opportunity_rules.get("sensitive_topics", []) or [])
    handled_by_other_workspace = opportunity_rules.get("handled_by_other_workspace", {}) or {}

    if topic in handled_by_other_workspace:
        return "handled_by_other_workspace"

    if topic in out_of_scope_topics:
        return "out_of_scope"

    if topic in sensitive_topics:
        return "manual_review_required"

    if our_count > 0 and competitor_coverage_count >= 3:
        return "already_covered_monitor"

    if our_count > 0:
        return "already_covered"

    if topic in HIGH_VALUE_TOPICS and competitor_coverage_count >= 3:
        return "high_priority_gap"

    if competitor_coverage_count >= 2:
        return "consider_content"

    if competitor_total_pages >= 3:
        return "monitor"

    return "low_priority_monitor"


def build_market_topics(our_topics, competitor_topic_data, opportunity_rules=None):
    market_topics = []

    all_topics = sorted(set(our_topics.keys()) | set(competitor_topic_data.keys()))

    for topic in all_topics:
        if topic in IGNORE_TOPICS:
            continue

        competitor_record = competitor_topic_data.get(topic, {})
        competitor_coverage_count = competitor_record.get("competitor_coverage_count", 0)
        competitor_total_pages = competitor_record.get("total_pages", 0)
        our_count = our_topics.get(topic, 0)

        market_topics.append({
            "topic": topic,
            "our_coverage_pages": our_count,
            "competitor_coverage_count": competitor_coverage_count,
            "competitor_total_pages": competitor_total_pages,
            "competitors_covering": competitor_record.get("competitors_covering", []),
            "recommended_action": recommend_action(
                topic,
                our_count,
                competitor_coverage_count,
                competitor_total_pages,
                opportunity_rules=opportunity_rules
            )
        })

    market_topics.sort(
        key=lambda x: (
            1 if x["recommended_action"] == "high_priority_gap" else 0,
            x["competitor_coverage_count"],
            x["competitor_total_pages"]
        ),
        reverse=True
    )

    return market_topics


def summarize_market_topics(market_topics):
    summary = {}

    for topic in market_topics:
        action = topic.get("recommended_action", "unknown")
        summary[action] = summary.get(action, 0) + 1

    return summary


def update_market_intelligence(workspace_folder, workspace_id, market_topics):
    path = workspace_folder / "market_intelligence.json"
    data = load_json(path)

    data["workspace_id"] = workspace_id
    data["last_updated"] = now_iso()
    data["market_topics"] = market_topics
    data["market_topic_summary"] = summarize_market_topics(market_topics)

    save_json(path, data)

    return data


def main():
    parser = argparse.ArgumentParser(description="Build Sofia market intelligence from own-site and competitor inventories.")
    parser.add_argument("workspace_id", help="Workspace ID, e.g. local.es")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, args.workspace_id)

    if not workspace:
        print(f"Workspace not found: {args.workspace_id}")
        raise SystemExit(1)

    workspace_folder = get_workspace_folder(workspace)

    our_topics = load_our_topics(workspace_folder)
    inventories = load_competitor_inventories(workspace_folder)
    competitor_topic_data = aggregate_competitor_topics(inventories)
    opportunity_rules = get_opportunity_rules(workspace_folder)
    market_topics = build_market_topics(
        our_topics,
        competitor_topic_data,
        opportunity_rules=opportunity_rules
    )

    print("\n=== Market Intelligence Build Summary ===")
    print(f"Workspace: {args.workspace_id}")
    print(f"Our topics: {len(our_topics)}")
    print(f"Competitor inventories: {len(inventories)}")
    print(f"Market topics: {len(market_topics)}")
    print("Summary:")
    print(json.dumps(summarize_market_topics(market_topics), indent=2, ensure_ascii=False))

    print("\nTop market topics:")
    for topic in market_topics[:15]:
        print(
            f"- {topic['topic']} | "
            f"our={topic['our_coverage_pages']} | "
            f"competitors={topic['competitor_coverage_count']} | "
            f"pages={topic['competitor_total_pages']} | "
            f"action={topic['recommended_action']}"
        )

    if args.dry_run:
        print("\nDry run only. market_intelligence.json not updated.")
        return

    update_market_intelligence(workspace_folder, args.workspace_id, market_topics)
    print("\nUpdated market_intelligence.json")


if __name__ == "__main__":
    main()