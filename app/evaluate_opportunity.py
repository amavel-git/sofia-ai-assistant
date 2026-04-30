import json
from pathlib import Path


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


def normalize(text):
    return str(text or "").strip().lower()


def slug_exists(site_structure, suggested_slug):
    suggested_slug = normalize(suggested_slug)

    # Empty slug means no proposed webpage slug.
    # Do not compare it with the homepage.
    if not suggested_slug:
        return None

    for page in site_structure.get("pages", []):
        existing_slug = normalize(page.get("slug", ""))

        if existing_slug and existing_slug == suggested_slug:
            return page

    return None


def keyword_exists_in_memory(memory_data, target_keyword):
    target_keyword = normalize(target_keyword)

    for keyword in memory_data.get("keyword_index", []):
        if normalize(keyword) == target_keyword:
            return True

    for item in memory_data.get("draft_content", []):
        if isinstance(item, dict) and normalize(item.get("target_keyword")) == target_keyword:
            return True

    for item in memory_data.get("published_content", []):
        if isinstance(item, dict) and normalize(item.get("target_keyword")) == target_keyword:
            return True

    return False


def duplicate_draft_exists(drafts, workspace_id, target_keyword):
    workspace_id = normalize(workspace_id)
    target_keyword = normalize(target_keyword)

    for draft in drafts:
        if (
            normalize(draft.get("workspace_id")) == workspace_id
            and normalize(draft.get("target_keyword")) == target_keyword
        ):
            return draft

    return None


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
        url = page.get("url", "")

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


def evaluate_opportunity(intake_item, workspace, site_structure, memory_data, drafts):
    workspace_id = intake_item.get("workspace_id", "")
    target_keyword = intake_item.get("target_keyword", "")
    suggested_slug = intake_item.get("suggested_slug", "")
    search_intent = normalize(intake_item.get("search_intent", ""))
    source_platform = intake_item.get("source_platform", "")
    content_type = normalize(intake_item.get("content_type", ""))

    existing_page_by_slug = slug_exists(site_structure, suggested_slug)
    if existing_page_by_slug:
        return {
            "recommended_action": "update_existing_page",
            "recommended_channel": "none",
            "confidence": "high",
            "reason": "Suggested slug already exists in site_structure.json.",
            "related_existing_url": existing_page_by_slug.get("url", ""),
            "related_existing_draft_id": "",
            "should_enter_workflow_engine": False,
            "link_back_strategy": {
                "link_back_recommended": False,
                "link_target_url": existing_page_by_slug.get("url", ""),
                "notes": "Update the existing page instead of creating a new page."
            }
        }

    if keyword_exists_in_memory(memory_data, target_keyword):
        related_page = find_related_page(site_structure, target_keyword, suggested_slug)

        return {
            "recommended_action": "review_existing_content",
            "recommended_channel": "none",
            "confidence": "high",
            "reason": "Target keyword already exists in workspace memory.",
            "related_existing_url": related_page.get("url", "") if related_page else "",
            "related_existing_draft_id": "",
            "should_enter_workflow_engine": False,
            "link_back_strategy": {
                "link_back_recommended": bool(related_page),
                "link_target_url": related_page.get("url", "") if related_page else "",
                "notes": "Existing content should be reviewed before creating anything new."
            }
        }

    duplicate_draft = duplicate_draft_exists(drafts, workspace_id, target_keyword)
    if duplicate_draft:
        return {
            "recommended_action": "no_action",
            "recommended_channel": "none",
            "confidence": "high",
            "reason": "A draft with this keyword already exists in the same workspace.",
            "related_existing_url": "",
            "related_existing_draft_id": duplicate_draft.get("draft_id", ""),
            "should_enter_workflow_engine": False,
            "link_back_strategy": {
                "link_back_recommended": False,
                "link_target_url": "",
                "notes": "No new action because the topic is already in the draft pipeline."
            }
        }

    related_page = find_related_page(site_structure, target_keyword, suggested_slug)

    if content_type == "social_post":
        channel = decide_social_channel(source_platform)

        return {
            "recommended_action": "create_social_post",
            "recommended_channel": channel,
            "confidence": "medium",
            "reason": "The idea is marked as social content.",
            "related_existing_url": related_page.get("url", "") if related_page else "",
            "related_existing_draft_id": "",
            "should_enter_workflow_engine": False,
            "link_back_strategy": {
                "link_back_recommended": bool(related_page),
                "link_target_url": related_page.get("url", "") if related_page else "",
                "notes": "Link back to the related page if relevant."
            }
        }

    if search_intent in ["service", "commercial", "local"]:
        return {
            "recommended_action": "create_new_page",
            "recommended_channel": "none",
            "confidence": "medium",
            "reason": "Commercial, service, or local topic is missing from the current site structure.",
            "related_existing_url": "",
            "related_existing_draft_id": "",
            "should_enter_workflow_engine": True,
            "link_back_strategy": {
                "link_back_recommended": True,
                "link_target_url": "future_page",
                "notes": "Create the page first, then promote it with a social post linking back to the new page."
            }
        }

    if search_intent == "informational":
        return {
            "recommended_action": "create_blog_post",
            "recommended_channel": "none",
            "confidence": "medium",
            "reason": "Informational topic is better suited for a blog post.",
            "related_existing_url": "",
            "related_existing_draft_id": "",
            "should_enter_workflow_engine": True,
            "link_back_strategy": {
                "link_back_recommended": True,
                "link_target_url": "future_blog_post",
                "notes": "Create the blog post first, then optionally promote it on social media."
            }
        }

    channel = decide_social_channel(source_platform)

    return {
        "recommended_action": "create_social_post",
        "recommended_channel": channel,
        "confidence": "low",
        "reason": "The topic does not clearly justify a webpage but may be useful for social media.",
        "related_existing_url": related_page.get("url", "") if related_page else "",
        "related_existing_draft_id": "",
        "should_enter_workflow_engine": False,
        "link_back_strategy": {
            "link_back_recommended": bool(related_page),
            "link_target_url": related_page.get("url", "") if related_page else "",
            "notes": "Use a social post and link back if a relevant page exists."
        }
    }


def main():
    print("=== Sofia Chapter 3: Evaluate Opportunity ===\n")

    for required_file in [WORKSPACES_FILE, INTAKE_FILE, DRAFT_REGISTRY_FILE]:
        if not required_file.exists():
            print(f"ERROR: Required file not found: {required_file}")
            return

    try:
        workspaces_data = load_json(WORKSPACES_FILE)
        intake_data = load_json(INTAKE_FILE)
        draft_registry_data = load_json(DRAFT_REGISTRY_FILE)
    except Exception as e:
        print(f"ERROR: Could not read required files: {e}")
        return

    intake_item = find_next_new_intake(intake_data.get("content_ideas", []))
    if not intake_item:
        print("No intake items with status 'new' found.")
        return

    workspace_id = intake_item.get("workspace_id", "")
    workspace = find_workspace(workspaces_data, workspace_id)

    if not workspace:
        print(f"ERROR: Workspace not found: {workspace_id}")
        return

    folder_path = workspace.get("folder_path", "")
    site_structure_file = BASE_DIR / folder_path / "site_structure.json"
    memory_file = BASE_DIR / folder_path / "site_content_memory.json"

    if not site_structure_file.exists():
        print(f"ERROR: site_structure.json not found: {site_structure_file}")
        return

    if not memory_file.exists():
        print(f"ERROR: site_content_memory.json not found: {memory_file}")
        return

    try:
        site_structure = load_json(site_structure_file)
        memory_data = load_json(memory_file)
    except Exception as e:
        print(f"ERROR: Could not read workspace files: {e}")
        return

    result = evaluate_opportunity(
        intake_item=intake_item,
        workspace=workspace,
        site_structure=site_structure,
        memory_data=memory_data,
        drafts=draft_registry_data.get("drafts", [])
    )

    print(f"Intake ID: {intake_item.get('intake_id', '')}")
    print(f"Idea Title: {intake_item.get('idea_title', '')}")
    print(f"Workspace: {workspace_id}")
    print(f"Target Keyword: {intake_item.get('target_keyword', '')}")
    print("")

    print("Recommendation:")
    print(f"  Action: {result['recommended_action']}")
    print(f"  Channel: {result['recommended_channel']}")
    print(f"  Confidence: {result['confidence']}")
    print(f"  Reason: {result['reason']}")
    print(f"  Related URL: {result['related_existing_url']}")
    print(f"  Related Draft: {result['related_existing_draft_id']}")
    print(f"  Send to workflow engine: {result['should_enter_workflow_engine']}")
    print("")

    print("Link-back strategy:")
    print(f"  Recommended: {result['link_back_strategy']['link_back_recommended']}")
    print(f"  Target URL: {result['link_back_strategy']['link_target_url']}")
    print(f"  Notes: {result['link_back_strategy']['notes']}")


if __name__ == "__main__":
    main()