import argparse

from market_intelligence import load_market_intelligence, save_market_intelligence


ALLOWED_RULE_LISTS = {
    "preferred_content_types",
    "avoid_topics",
    "sensitive_topics"
}


def add_unique_items(existing_items, new_items):
    existing = list(existing_items or [])

    for item in new_items:
        clean_item = item.strip()
        if clean_item and clean_item not in existing:
            existing.append(clean_item)

    return existing


def update_opportunity_rules(
    workspace_id,
    preferred_content_types=None,
    avoid_topics=None,
    sensitive_topics=None,
    requires_manual_review=None,
):
    data = load_market_intelligence(workspace_id)

    rules = data.setdefault("opportunity_rules", {})
    rules.setdefault("preferred_content_types", [])
    rules.setdefault("avoid_topics", [])
    rules.setdefault("sensitive_topics", [])
    rules.setdefault("requires_manual_review", True)

    if preferred_content_types:
        rules["preferred_content_types"] = add_unique_items(
            rules["preferred_content_types"],
            preferred_content_types
        )

    if avoid_topics:
        rules["avoid_topics"] = add_unique_items(
            rules["avoid_topics"],
            avoid_topics
        )

    if sensitive_topics:
        rules["sensitive_topics"] = add_unique_items(
            rules["sensitive_topics"],
            sensitive_topics
        )

    if requires_manual_review is not None:
        rules["requires_manual_review"] = requires_manual_review

    path = save_market_intelligence(workspace_id, data)

    print("Opportunity rules updated successfully.")
    print(f"Workspace: {workspace_id}")
    print(f"Saved to: {path}")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Update market intelligence opportunity rules."
    )

    parser.add_argument("workspace_id")

    parser.add_argument(
        "--preferred-content-types",
        nargs="*",
        default=None,
        help="Preferred content types, e.g. service_page faq_page city_page"
    )

    parser.add_argument(
        "--avoid-topics",
        nargs="*",
        default=None,
        help="Topics Sofia should avoid suggesting."
    )

    parser.add_argument(
        "--sensitive-topics",
        nargs="*",
        default=None,
        help="Topics requiring special caution or examiner review."
    )

    parser.add_argument(
        "--requires-manual-review",
        choices=["true", "false"],
        default=None,
        help="Whether opportunities require manual review."
    )

    args = parser.parse_args()

    manual_review = None
    if args.requires_manual_review == "true":
        manual_review = True
    elif args.requires_manual_review == "false":
        manual_review = False

    update_opportunity_rules(
        workspace_id=args.workspace_id,
        preferred_content_types=args.preferred_content_types,
        avoid_topics=args.avoid_topics,
        sensitive_topics=args.sensitive_topics,
        requires_manual_review=manual_review,
    )


if __name__ == "__main__":
    main()