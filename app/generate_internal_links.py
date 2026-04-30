import json
from pathlib import Path
from datetime import datetime


BASE_DIR = Path(__file__).resolve().parent.parent

WORKSPACES_FILE = BASE_DIR / "data" / "workspaces.json"
INTERNAL_LINK_RULES_FILE = BASE_DIR / "config" / "internal_link_rules.json"


def load_json(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path: Path, data):
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def normalize(text):
    return str(text or "").strip().lower()


def get_workspace(workspaces_data, workspace_id):
    for workspace in workspaces_data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def page_text(page):
    return normalize(" ".join([
        page.get("url", ""),
        page.get("slug", ""),
        page.get("section", ""),
        page.get("page_type", "")
    ]))


def add_link(suggestions, source_page, target_page, reason, priority, link_type):
    if not source_page or not target_page:
        return

    source_url = source_page.get("url", "")
    target_url = target_page.get("url", "")

    if not source_url or not target_url or source_url == target_url:
        return

    for item in suggestions:
        if item["source_url"] == source_url and item["target_url"] == target_url:
            return

    suggestions.append({
        "source_url": source_url,
        "source_slug": source_page.get("slug", ""),
        "source_page_type": source_page.get("page_type", ""),
        "target_url": target_url,
        "target_slug": target_page.get("slug", ""),
        "target_page_type": target_page.get("page_type", ""),
        "anchor_text": "AUTO",
        "reason": reason,
        "priority": priority,
        "link_type": link_type,
        "status": "suggested"
    })


def find_pages_by_type(pages, page_type):
    return [page for page in pages if normalize(page.get("page_type")) == normalize(page_type)]


def find_first_page_by_role(pages, role):
    role = normalize(role)

    role_signals = {
        "faq": ["faq", "perguntas", "respostas", "questions", "answers"],
        "how_it_works": ["how", "works", "funcionamento", "procedimento", "procedure", "process"],
        "contact": ["contact", "contato", "contacto"],
        "main_service_page": ["polygraph", "poligrafo", "lie-detector", "detector"],
        "service_page": ["polygraph", "poligrafo", "test", "teste", "exam", "exame"]
    }

    if role == "faq":
        candidates = find_pages_by_type(pages, "faq")
        if candidates:
            return candidates[0]

    if role == "contact":
        candidates = find_pages_by_type(pages, "contact")
        if candidates:
            return candidates[0]

    if role == "main_service_page":
        candidates = find_pages_by_type(pages, "pillar")
        if candidates:
            return candidates[0]

    signals = role_signals.get(role, [])

    best_page = None
    best_score = 0

    for page in pages:
        text = page_text(page)
        score = 0

        for signal in signals:
            if normalize(signal) in text:
                score += 1

        if role == "main_service_page" and normalize(page.get("page_type")) == "pillar":
            score += 2

        if role == "service_page" and normalize(page.get("page_type")) == "service_page":
            score += 2

        if score > best_score:
            best_score = score
            best_page = page

    if best_score > 0:
        return best_page

    return None


def build_topic_page_map(content_opportunities):
    topic_page_map = {}

    all_topic_records = []
    all_topic_records.extend(content_opportunities.get("covered_topics", []))
    all_topic_records.extend(content_opportunities.get("partial_opportunities", []))
    all_topic_records.extend(content_opportunities.get("missing_opportunities", []))

    for item in all_topic_records:
        topic_id = item.get("topic_id", "")
        matched_url = item.get("matched_existing_url", "")
        matched_slug = item.get("matched_existing_slug", "")

        if topic_id and matched_url:
            topic_page_map[topic_id] = {
                "url": matched_url,
                "slug": matched_slug
            }

    return topic_page_map


def find_page_by_url(pages, url):
    for page in pages:
        if page.get("url") == url:
            return page
    return None


def get_topic_for_page(page, content_opportunities):
    page_url = page.get("url", "")

    all_topic_records = []
    all_topic_records.extend(content_opportunities.get("covered_topics", []))
    all_topic_records.extend(content_opportunities.get("partial_opportunities", []))

    for item in all_topic_records:
        if item.get("matched_existing_url") == page_url:
            return item.get("topic_id", "")

    return ""


def get_priority(priority_rules, source_type, target_role, link_type):
    key = f"{source_type}_to_{target_role}"

    if key in priority_rules:
        return priority_rules[key]

    if link_type == "conversion":
        return "high"

    if link_type == "supporting_information":
        return "high"

    return "medium"


def target_page_for_role(pages, role, source_page=None):
    role = normalize(role)

    if role == "faq":
        return find_first_page_by_role(pages, "faq")

    if role == "how_it_works":
        return find_first_page_by_role(pages, "how_it_works")

    if role == "contact":
        return find_first_page_by_role(pages, "contact")

    if role == "main_service_page":
        return find_first_page_by_role(pages, "main_service_page")

    if role == "related_service":
        if not source_page:
            return None

        source_text = page_text(source_page)
        best_page = None
        best_score = 0

        for page in pages:
            if page.get("url") == source_page.get("url"):
                continue

            if normalize(page.get("page_type")) != "service_page":
                continue

            target_text = page_text(page)
            shared = 0

            for part in source_text.replace("-", " ").split():
                if len(part) > 4 and part in target_text:
                    shared += 1

            if shared > best_score:
                best_score = shared
                best_page = page

        if best_score > 0:
            return best_page

    return None


def generate_page_role_links(pages, internal_link_rules):
    suggestions = []

    page_role_rules = internal_link_rules.get("page_role_rules", {})
    priority_rules = internal_link_rules.get("link_priority_rules", {})

    for source_page in pages:
        source_type = normalize(source_page.get("page_type", ""))
        rule = page_role_rules.get(source_type)

        if not rule:
            continue

        for target_role in rule.get("should_link_to", []):
            if target_role == "child_service_page":
                source_slug = normalize(source_page.get("slug", ""))
                for target_page in pages:
                    if normalize(target_page.get("page_type")) != "service_page":
                        continue

                    if source_slug and source_slug in normalize(target_page.get("url", "")):
                        add_link(
                            suggestions=suggestions,
                            source_page=source_page,
                            target_page=target_page,
                            reason=rule.get("reason", "Internal link suggested by page role rule."),
                            priority=get_priority(priority_rules, source_type, target_role, "navigation"),
                            link_type="navigation"
                        )
                continue

            target_page = target_page_for_role(pages, target_role, source_page)

            link_type = "supporting_information"
            if target_role == "contact":
                link_type = "conversion"
            elif target_role == "related_service":
                link_type = "topic_related"
            elif target_role == "main_service_page":
                link_type = "silo_support"

            add_link(
                suggestions=suggestions,
                source_page=source_page,
                target_page=target_page,
                reason=rule.get("reason", "Internal link suggested by page role rule."),
                priority=get_priority(priority_rules, source_type, target_role, link_type),
                link_type=link_type
            )

    return suggestions


def generate_topic_relationship_links(pages, content_opportunities, internal_link_rules):
    suggestions = []

    topic_relationships = internal_link_rules.get("topic_relationships", {})
    priority_rules = internal_link_rules.get("link_priority_rules", {})
    topic_page_map = build_topic_page_map(content_opportunities)

    for source_page in pages:
        source_topic = get_topic_for_page(source_page, content_opportunities)

        if not source_topic:
            continue

        related_topics = topic_relationships.get(source_topic, {}).get("related_topics", [])

        for related_topic in related_topics:
            target_ref = topic_page_map.get(related_topic)

            if not target_ref:
                continue

            target_page = find_page_by_url(pages, target_ref.get("url", ""))

            add_link(
                suggestions=suggestions,
                source_page=source_page,
                target_page=target_page,
                reason=f"Topic relationship: {source_topic} should connect to {related_topic}.",
                priority=priority_rules.get("related_service_to_related_service", "medium"),
                link_type="topic_related"
            )

    return suggestions


def merge_suggestions(*suggestion_lists):
    merged = []

    for suggestions in suggestion_lists:
        for suggestion in suggestions:
            exists = False

            for existing in merged:
                if (
                    existing.get("source_url") == suggestion.get("source_url")
                    and existing.get("target_url") == suggestion.get("target_url")
                ):
                    exists = True
                    break

            if not exists:
                merged.append(suggestion)

    return merged


def main():
    print("=== Sofia: Generate Internal Link Suggestions Global ===\n")

    workspace_id = "local.ao"

    for required_file in [WORKSPACES_FILE, INTERNAL_LINK_RULES_FILE]:
        if not required_file.exists():
            print(f"ERROR: Required file not found: {required_file}")
            return

    try:
        workspaces_data = load_json(WORKSPACES_FILE)
        internal_link_rules = load_json(INTERNAL_LINK_RULES_FILE)
    except Exception as e:
        print(f"ERROR: Could not read config files: {e}")
        return

    workspace = get_workspace(workspaces_data, workspace_id)

    if not workspace:
        print(f"ERROR: Workspace not found: {workspace_id}")
        return

    workspace_folder = BASE_DIR / workspace.get("folder_path", "")

    site_structure_file = workspace_folder / "site_structure.json"
    content_opportunities_file = workspace_folder / "content_opportunities.json"
    output_file = workspace_folder / "internal_link_suggestions.json"

    for required_file in [site_structure_file, content_opportunities_file]:
        if not required_file.exists():
            print(f"ERROR: Required file not found: {required_file}")
            return

    try:
        site_structure = load_json(site_structure_file)
        content_opportunities = load_json(content_opportunities_file)
    except Exception as e:
        print(f"ERROR: Could not read input files: {e}")
        return

    pages = site_structure.get("pages", [])

    role_links = generate_page_role_links(
        pages=pages,
        internal_link_rules=internal_link_rules
    )

    topic_links = generate_topic_relationship_links(
        pages=pages,
        content_opportunities=content_opportunities,
        internal_link_rules=internal_link_rules
    )

    suggestions = merge_suggestions(role_links, topic_links)

    output_data = {
        "workspace_id": workspace_id,
        "domain": workspace.get("domain", ""),
        "generated_at": datetime.now().strftime("%Y-%m-%d"),
        "version": "global-1.0",
        "suggestion_count": len(suggestions),
        "internal_link_suggestions": suggestions
    }

    try:
        save_json(output_file, output_data)
    except Exception as e:
        print(f"ERROR: Could not save output file: {e}")
        return

    print("Internal link suggestions generated successfully.")
    print(f"Workspace: {workspace_id}")
    print(f"Suggestions: {len(suggestions)}")
    print(f"Saved to: {output_file}")


if __name__ == "__main__":
    main()