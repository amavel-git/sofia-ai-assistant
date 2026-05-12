import argparse

from market_intelligence import (
    load_market_intelligence,
    save_market_intelligence,
    utc_now_iso,
)


def topic_exists(data, topic_id):
    for topic in data.get("market_topics", []):
        if topic.get("topic_id") == topic_id:
            return True
    return False


def build_market_topic(
    topic_id,
    topic,
    intent="general",
    priority="medium",
    local_relevance="medium",
    related_keywords=None,
    recommended_action="review"
):
    return {
        "topic_id": topic_id,
        "topic": topic,
        "intent": intent,
        "priority": priority,
        "local_relevance": local_relevance,

        "related_keywords": related_keywords or [],

        "competitor_coverage": {
            "status": "unknown",
            "competitors": []
        },

        "our_coverage": {
            "status": "unknown",
            "existing_pages": []
        },

        "market_saturation": "unknown",
        "cannibalization_risk": "unknown",

        "recommended_action": recommended_action,

        "notes": [],
        "last_reviewed": None,
        "added_at": utc_now_iso()
    }


def add_market_topic(
    workspace_id,
    topic_id,
    topic,
    intent="general",
    priority="medium",
    local_relevance="medium",
    related_keywords=None,
    recommended_action="review"
):
    data = load_market_intelligence(workspace_id)

    if topic_exists(data, topic_id):
        print("Market topic already exists.")
        print(f"Workspace: {workspace_id}")
        print(f"Topic ID: {topic_id}")
        return False

    market_topic = build_market_topic(
        topic_id=topic_id,
        topic=topic,
        intent=intent,
        priority=priority,
        local_relevance=local_relevance,
        related_keywords=related_keywords,
        recommended_action=recommended_action
    )

    data.setdefault("market_topics", []).append(market_topic)

    path = save_market_intelligence(workspace_id, data)

    print("Market topic added successfully.")
    print(f"Workspace: {workspace_id}")
    print(f"Topic ID: {topic_id}")
    print(f"Saved to: {path}")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Add a market topic to market_intelligence.json"
    )

    parser.add_argument("workspace_id")
    parser.add_argument("topic_id")
    parser.add_argument("topic")

    parser.add_argument("--intent", default="general")
    parser.add_argument("--priority", default="medium")
    parser.add_argument("--local-relevance", default="medium")
    parser.add_argument("--recommended-action", default="review")

    parser.add_argument(
        "--keywords",
        nargs="*",
        default=[]
    )

    args = parser.parse_args()

    add_market_topic(
        workspace_id=args.workspace_id,
        topic_id=args.topic_id,
        topic=args.topic,
        intent=args.intent,
        priority=args.priority,
        local_relevance=args.local_relevance,
        related_keywords=args.keywords,
        recommended_action=args.recommended_action
    )


if __name__ == "__main__":
    main()