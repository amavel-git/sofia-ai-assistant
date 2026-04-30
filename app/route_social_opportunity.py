import json
from pathlib import Path
from datetime import datetime


BASE_DIR = Path(__file__).resolve().parent.parent

WORKSPACES_FILE = BASE_DIR / "data" / "workspaces.json"
INTAKE_FILE = BASE_DIR / "sites" / "content_intake.json"
DRAFT_REGISTRY_FILE = BASE_DIR / "sites" / "draft_registry.json"


RELATED_TERMS = {
    "relacionamento": ["casais", "infidelidade", "fidelidade"],
    "casal": ["casais", "infidelidade", "fidelidade"],
    "casais": ["relacionamento", "infidelidade", "fidelidade"],
    "conflitos": ["casais", "familiares"],
    "preco": ["preco", "custo", "valor"],
    "custo": ["preco", "valor"],
    "valor": ["preco", "custo"],
    "empresa": ["empresas", "recursos-humanos"],
    "empresas": ["empresa", "recursos-humanos"],
    "advogado": ["advogados", "casos-legais", "justica"],
    "advogados": ["advogado", "casos-legais", "justica"],
    "roubo": ["furto"],
    "furto": ["roubo"]
}


def load_json(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path: Path, data):
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def normalize(text):
    return str(text or "").strip().lower()


def find_workspace(workspaces_data, workspace_id: str):
    for workspace in workspaces_data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def find_next_new_intake(content_ideas):
    for item in content_ideas:
        if item.get("status") == "new":
            return item
    return None


def ensure_social_queue_structure(queue_data):
    if "social_items" not in queue_data or not isinstance(queue_data["social_items"], list):
        queue_data["social_items"] = []
    return queue_data


def social_item_exists(social_items, intake_id: str):
    for item in social_items:
        if item.get("intake_id") == intake_id:
            return True
    return False


def generate_next_social_id(social_items):
    max_number = 0

    for item in social_items:
        social_id = str(item.get("social_id", "")).strip()
        if social_id.startswith("SOCIAL-"):
            try:
                number = int(social_id.replace("SOCIAL-", ""))
                if number > max_number:
                    max_number = number
            except ValueError:
                continue

    return f"SOCIAL-{max_number + 1:04d}"


def find_related_page(site_structure, target_keyword, suggested_slug):
    target_keyword = normalize(target_keyword)
    suggested_slug = normalize(suggested_slug)

    keyword_parts = [p for p in target_keyword.replace("-", " ").split() if len(p) > 3]
    expanded_terms = set(keyword_parts)

    for part in keyword_parts:
        related = RELATED_TERMS.get(part, [])
        for term in related:
            expanded_terms.add(term)

    best_match = None
    best_score = 0

    for page in site_structure.get("pages", []):
        slug = normalize(page.get("slug"))
        page_type = normalize(page.get("page_type"))

        if not slug:
            continue

        if suggested_slug and suggested_slug == slug:
            return page

        score = 0

        for term in expanded_terms:
            if term in slug:
                score += 2

        for part in keyword_parts:
            if part in slug:
                score += 3

        if page_type in ["service_page", "blog_post"]:
            score += 1

        if page_type in ["category", "home"]:
            score -= 1

        if score > best_score:
            best_score = score
            best_match = page

    if best_score >= 2:
        return best_match

    return None


def decide_social_channel(source_platform):
    source_platform = normalize(source_platform)

    allowed = {
        "facebook": "facebook",
        "x": "x",
        "twitter": "x",
        "linkedin": "linkedin",
        "instagram": "instagram",
        "telegram": "telegram",
        "youtube": "youtube"
    }

    if source_platform in allowed:
        return allowed[source_platform]

    return "facebook"


def main():
    print("=== Sofia Chapter 3: Route Social Opportunity ===\n")

    for required_file in [WORKSPACES_FILE, INTAKE_FILE, DRAFT_REGISTRY_FILE]:
        if not required_file.exists():
            print(f"ERROR: Required file not found: {required_file}")
            return

    try:
        workspaces_data = load_json(WORKSPACES_FILE)
        intake_data = load_json(INTAKE_FILE)
    except Exception as e:
        print(f"ERROR: Could not read required files: {e}")
        return

    content_ideas = intake_data.get("content_ideas", [])
    intake_item = find_next_new_intake(content_ideas)

    if not intake_item:
        print("No intake items with status 'new' found.")
        return

    content_type = normalize(intake_item.get("content_type", ""))

    if content_type != "social_post":
        print("This intake item is not marked as social_post.")
        print("No social routing performed.")
        return

    workspace_id = intake_item.get("workspace_id", "")
    workspace = find_workspace(workspaces_data, workspace_id)

    if not workspace:
        print(f"ERROR: Workspace not found: {workspace_id}")
        return

    folder_path = workspace.get("folder_path", "")
    site_structure_file = BASE_DIR / folder_path / "site_structure.json"
    social_queue_file = BASE_DIR / folder_path / "social_review_queue.json"

    if not site_structure_file.exists():
        print(f"ERROR: site_structure.json not found: {site_structure_file}")
        return

    if not social_queue_file.exists():
        print(f"ERROR: social_review_queue.json not found: {social_queue_file}")
        print("Create it with this content:")
        print('{ "social_items": [] }')
        return

    try:
        site_structure = load_json(site_structure_file)
        social_queue_data = load_json(social_queue_file)
    except Exception as e:
        print(f"ERROR: Could not read workspace files: {e}")
        return

    social_queue_data = ensure_social_queue_structure(social_queue_data)
    social_items = social_queue_data["social_items"]

    intake_id = intake_item.get("intake_id", "")

    if social_item_exists(social_items, intake_id):
        print(f"Social item already exists for intake: {intake_id}")
        return

    today = datetime.now().strftime("%Y-%m-%d")

    target_keyword = intake_item.get("target_keyword", "")
    suggested_slug = intake_item.get("suggested_slug", "")
    source_platform = intake_item.get("source_platform", "")
    channel = decide_social_channel(source_platform)

    related_page = find_related_page(
        site_structure=site_structure,
        target_keyword=target_keyword,
        suggested_slug=suggested_slug
    )

    social_id = generate_next_social_id(social_items)

    link_target_url = related_page.get("url", "") if related_page else ""
    link_back_recommended = bool(link_target_url)

    new_social_item = {
        "social_id": social_id,
        "intake_id": intake_id,
        "created_at": today,
        "workspace_id": workspace_id,
        "workspace_path": folder_path,
        "language": intake_item.get("language", ""),
        "site_target": intake_item.get("site_target", ""),
        "platform": channel,
        "source_platform": source_platform,
        "status": "pending_review",
        "idea_title": intake_item.get("idea_title", ""),
        "idea_summary": intake_item.get("idea_summary", ""),
        "target_keyword": target_keyword,
        "secondary_keywords": intake_item.get("secondary_keywords", []),
        "recommended_action": "create_social_post",
        "link_back": {
            "recommended": link_back_recommended,
            "target_url": link_target_url,
            "reason": "Related page found in site structure." if link_back_recommended else "No related page confidently found."
        },
        "draft_text": "",
        "review_notes": ""
    }

    social_items.append(new_social_item)

    intake_item["status"] = "routed_to_social_review"
    intake_item["social_routing"] = {
        "routed": True,
        "social_id": social_id,
        "platform": channel,
        "routed_at": today,
        "queue_file": str(social_queue_file)
    }

    try:
        save_json(social_queue_file, social_queue_data)
        save_json(INTAKE_FILE, intake_data)
    except Exception as e:
        print(f"ERROR: Could not write updated files: {e}")
        return

    print("Social opportunity routed successfully.")
    print(f"Social ID: {social_id}")
    print(f"Platform: {channel}")
    print(f"Queue file: {social_queue_file}")
    print(f"Link-back recommended: {link_back_recommended}")
    print(f"Link target: {link_target_url}")


if __name__ == "__main__":
    main()