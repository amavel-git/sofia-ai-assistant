import json
from pathlib import Path
from datetime import datetime

from cannibalization_checker import check_workspace_cannibalization
from draft_page_plan import attach_page_plan_to_draft_record
from workspace_paths import (
    get_workspace_draft_registry_path,
    empty_draft_registry,
)


BASE_DIR = Path(__file__).resolve().parent.parent

WORKSPACES_FILE = BASE_DIR / "data" / "workspaces.json"
INTAKE_FILE = BASE_DIR / "sites" / "content_intake.json"


def load_json(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path: Path, data):
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_workspace(workspaces_data, workspace_id: str):
    for workspace in workspaces_data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def find_next_intake_item(content_ideas):
    for item in content_ideas:
        if item.get("status") == "new":
            return item
    return None


def keyword_exists_in_memory(memory_data, target_keyword: str) -> bool:
    target_keyword = target_keyword.strip().lower()

    keyword_index = memory_data.get("keyword_index", [])
    for keyword in keyword_index:
        if isinstance(keyword, str) and keyword.strip().lower() == target_keyword:
            return True

    published_content = memory_data.get("published_content", [])
    for item in published_content:
        if isinstance(item, dict):
            keyword = str(item.get("target_keyword", "")).strip().lower()
            if keyword == target_keyword:
                return True

    draft_content = memory_data.get("draft_content", [])
    for item in draft_content:
        if isinstance(item, dict):
            keyword = str(item.get("target_keyword", "")).strip().lower()
            if keyword == target_keyword:
                return True

    return False


def generate_next_draft_id(drafts):
    max_number = 0

    for draft in drafts:
        draft_id = str(draft.get("draft_id", "")).strip()
        if draft_id.startswith("DRAFT-"):
            try:
                number = int(draft_id.replace("DRAFT-", ""))
                if number > max_number:
                    max_number = number
            except ValueError:
                continue

    next_number = max_number + 1
    return f"DRAFT-{next_number:04d}"


def duplicate_draft_exists(drafts, workspace_id: str, target_keyword: str):
    target_keyword = target_keyword.strip().lower()

    for draft in drafts:
        draft_workspace = draft.get("workspace_id", "")
        draft_keyword = str(draft.get("target_keyword", "")).strip().lower()

        if draft_workspace == workspace_id and draft_keyword == target_keyword:
            return draft

    return None


def ensure_queue_structure(queue_data):
    if "review_items" not in queue_data or not isinstance(queue_data["review_items"], list):
        queue_data["review_items"] = []
    return queue_data


def review_item_exists(queue_items, draft_id: str):
    for item in queue_items:
        if item.get("draft_id") == draft_id:
            return True
    return False


def update_workspace_memory(memory_data, new_draft):
    keyword = new_draft.get("target_keyword", "").strip()
    title = new_draft.get("working_title", "")
    draft_id = new_draft.get("draft_id", "")

    if "keyword_index" not in memory_data or not isinstance(memory_data["keyword_index"], list):
        memory_data["keyword_index"] = []

    if keyword and keyword not in memory_data["keyword_index"]:
        memory_data["keyword_index"].append(keyword)

    if "draft_content" not in memory_data or not isinstance(memory_data["draft_content"], list):
        memory_data["draft_content"] = []

    memory_data["draft_content"].append({
        "draft_id": draft_id,
        "title": title,
        "target_keyword": keyword
    })

    return memory_data



def is_blocking_cannibalization(cannibalization: dict) -> bool:
    """
    Cannibalization should be advisory by default.

    Block only when the overlap is with a real content page, service page,
    landing page, post, or draft. Generic tag/category/archive matches should
    not block draft creation by themselves.
    """
    result = cannibalization.get("result")

    if result not in ["strong_overlap", "possible_overlap"]:
        return False

    matches = cannibalization.get("matches", [])

    if not matches:
        return False

    for match in matches:
        metadata = match.get("metadata", {}) or {}
        section = str(metadata.get("section", "")).lower()
        page_type = str(metadata.get("page_type", "")).lower()
        source_type = str(match.get("source_type", "")).lower()
        url = str(match.get("url", "")).lower()

        # Generic archive pages should warn, not block.
        if section in ["tag", "category", "archive", "author"]:
            continue

        if "/tag/" in url or "/category/" in url:
            continue

        # Real drafts can block.
        if source_type in ["draft", "existing_draft"]:
            return True

        # Real content pages can block.
        if page_type in [
            "service_page",
            "landing_page",
            "post",
            "page",
            "pillar_page",
            "content_page"
        ]:
            return True

        if source_type in [
            "content_memory",
            "existing_site_page",
            "content_inventory"
        ] and page_type not in ["tag", "category", "archive"]:
            return True

    return False

def main():
    print("=== Sofia Phase 1: Process Next Intake ===\n")

    for required_file in [WORKSPACES_FILE, INTAKE_FILE]:
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

    if not content_ideas:
        print("No content ideas found in content_intake.json")
        return

    intake_item = find_next_intake_item(content_ideas)
    if not intake_item:
        print("No intake items with status 'new' found.")
        return

    intake_id = intake_item.get("intake_id", "")
    workspace_id = intake_item.get("workspace_id", "")
    target_keyword = intake_item.get("target_keyword", "")
    idea_title = intake_item.get("idea_title", "")
    workspace_type = intake_item.get("workspace_type", "")
    workspace_path = intake_item.get("workspace_path", "")

    print(f"Processing intake: {intake_id}")
    print(f"Idea title: {idea_title}")
    print(f"Workspace ID: {workspace_id}")
    print(f"Target keyword: {target_keyword}\n")

    workspace = find_workspace(workspaces_data, workspace_id)
    if not workspace:
        print(f"ERROR: Workspace '{workspace_id}' not found in workspaces.json")
        return

    draft_registry_file = get_workspace_draft_registry_path(workspace_id)

    if draft_registry_file.exists():
        try:
            draft_registry_data = load_json(draft_registry_file)
        except Exception as e:
            print(f"ERROR: Could not read workspace draft registry: {e}")
            return
    else:
        draft_registry_data = empty_draft_registry(workspace_id)

    drafts = draft_registry_data.get("drafts", [])

    folder_path = workspace.get("folder_path", "")
    review_mode = workspace.get("review_mode", "")
    domain = workspace.get("domain", "")
    memory_file = BASE_DIR / folder_path / "site_content_memory.json"

    print("Resolved Workspace:")
    print(f"  Domain: {domain}")
    print(f"  Folder Path: {folder_path}")
    print(f"  Review Mode: {review_mode}")
    print(f"  Memory File: {memory_file}\n")

    if not memory_file.exists():
        print(f"ERROR: site_content_memory.json not found: {memory_file}")
        return

    try:
        memory_data = load_json(memory_file)
    except Exception as e:
        print(f"ERROR: Could not read site_content_memory.json: {e}")
        return

    cannibalization = check_workspace_cannibalization(
        workspace=workspace,
        topic=target_keyword,
        extra_terms=[idea_title]
    )

    raw_cannibalization_result = cannibalization.get("result", "clear")
    cannibalization_warning = raw_cannibalization_result in [
        "strong_overlap",
        "possible_overlap"
    ]

    intake_item["status"] = "checked"
    intake_item["cannibalization_check"] = {
        "checked": True,
        "result": (
            "advisory_overlap"
            if cannibalization_warning
            else cannibalization.get("result", "clear")
        ),
        "original_result": raw_cannibalization_result,
        "notes": cannibalization.get("notes", ""),
        "risk_score": cannibalization.get("risk_score", 0),
        "matches": cannibalization.get("matches", []),
        "checked_sources": cannibalization.get("checked_sources", {}),
        "advisory_only": cannibalization_warning,
        "examiner_warning_required": cannibalization_warning,
        "recommended_examiner_options": [
            "continue_as_planned",
            "revise_angle",
            "merge_with_existing_page",
            "cancel_opportunity"
        ] if cannibalization_warning else []
    }

    print("Cannibalization Check Result:")
    print(f"  Result: {raw_cannibalization_result}")
    print(f"  Risk score: {cannibalization.get('risk_score', 0)}")
    print(f"  Notes: {cannibalization.get('notes', '')}")

    if cannibalization_warning:
        print("  Advisory only: true")
        print("  Draft creation will continue. Examiner warning will be attached for review.\n")
    else:
        print("  Advisory only: false\n")

    duplicate_draft = duplicate_draft_exists(drafts, workspace_id, target_keyword)

    if duplicate_draft:
        intake_item["status"] = "checked"
        intake_item["cannibalization_check"] = {
            "checked": True,
            "result": "possible_overlap",
            "notes": f"Duplicate keyword found in draft {duplicate_draft.get('draft_id')}"
        }

        try:
            save_json(INTAKE_FILE, intake_data)
        except Exception as e:
            print(f"ERROR: Could not update content_intake.json: {e}")
            return

        print("Duplicate detected in draft registry.")
        print(f"Existing draft: {duplicate_draft.get('draft_id')}")
        print("Draft creation stopped.\n")
        return

    new_draft_id = generate_next_draft_id(drafts)
    today = datetime.now().strftime("%Y-%m-%d")

    queue_level = "local" if workspace_type == "local_market" else "workspace"
    target_queue = intake_item.get("review_routing", {}).get("target_queue", "")

    new_draft = {
        "draft_id": new_draft_id,
        "created_at": today,
        "created_from_intake_id": intake_id,
        "workspace_type": workspace_type,
        "workspace_id": workspace_id,
        "workspace_path": workspace_path,
        "seo_brief": intake_item.get("seo_brief", {}),
        "content_strategy_brief": intake_item.get("content_strategy_brief", {}),
        "draft_input": intake_item.get("draft_input", {}),
        "language": intake_item.get("language", ""),
        "site_target": intake_item.get("site_target", ""),
        "content_type": intake_item.get("content_type", ""),

        "page_type": intake_item.get("page_type", ""),
        "blueprint_id": intake_item.get("blueprint_id", ""),
        "intent_type": intake_item.get("intent_type", ""),
        "page_type_classification": intake_item.get(
            "page_type_classification",
            {}
        ),

        "working_title": (
            intake_item.get("page_h1")
            or intake_item.get("idea_title")
            or idea_title
        ),
        "title": (
            intake_item.get("page_h1")
            or intake_item.get("idea_title")
            or idea_title
        ),
        "target_keyword": target_keyword,
        "focus_keyphrase": target_keyword,
        "secondary_keywords": intake_item.get("secondary_keywords", []),
        "search_intent": intake_item.get("search_intent", ""),
        "suggested_slug": intake_item.get("suggested_slug", ""),
        "slug": intake_item.get("suggested_slug", ""),

        "normalized_title": intake_item.get("normalized_title", ""),
        "page_h1": intake_item.get("page_h1", ""),
        "issue": intake_item.get("issue", ""),
        "sector": intake_item.get("sector", ""),
        "sector_id": intake_item.get("sector_id", ""),
        "service_angle": intake_item.get("service_angle", ""),
        "topic_family": intake_item.get("topic_family", ""),
        "visual_topic_family": intake_item.get("visual_topic_family", ""),
        "recommended_seo_title": intake_item.get("recommended_seo_title", ""),
        "recommended_meta_description": intake_item.get("recommended_meta_description", ""),
        "intake_intelligence": intake_item.get("intake_intelligence", {}) or {},
        "opportunity_intelligence": intake_item.get("opportunity_intelligence", {}) or {},
        "cannibalization_result": intake_item.get("cannibalization_check", {}).get("result", "clear"),
        "cannibalization_notes": intake_item.get("cannibalization_check", {}).get("notes", ""),
        "cannibalization_advisory": intake_item.get("cannibalization_check", {}),
        "review_target": {
            "queue_level": queue_level,
            "queue_id": target_queue
        },
        "draft_status": "draft_created",
        "wordpress_status": "not_prepared",
        "assigned_reviewer": "",
        "notes": ""
    }

    new_draft["seo_brief"] = intake_item.get("seo_brief", {}) or {}
    new_draft["draft_input"] = intake_item.get("draft_input", {}) or {}
    new_draft["content_strategy_brief"] = (
        intake_item.get("content_strategy_brief", {})
        or intake_item.get("strategy_brief", {})
        or {}
    )

    seo_brief = new_draft.get("seo_brief", {}) or {}
    draft_input = new_draft.get("draft_input", {}) or {}

    if seo_brief:
        new_draft["working_title"] = seo_brief.get("page_title") or new_draft.get("working_title", "")
        new_draft["title"] = seo_brief.get("page_title") or new_draft.get("title", "")
        new_draft["target_keyword"] = seo_brief.get("focus_keyphrase") or new_draft.get("target_keyword", "")
        new_draft["focus_keyphrase"] = seo_brief.get("focus_keyphrase") or new_draft.get("focus_keyphrase", "")
        new_draft["slug"] = seo_brief.get("slug") or new_draft.get("slug", "")
        new_draft["seo_title"] = seo_brief.get("seo_title") or new_draft.get("seo_title", "")
        new_draft["meta_description"] = seo_brief.get("meta_description") or new_draft.get("meta_description", "")

    if draft_input:
        new_draft["draft_input"] = draft_input

    try:
        new_draft = attach_page_plan_to_draft_record(
            draft=new_draft,
            workspace_id=workspace_id,
            overwrite=False,
        )
        print("Page plan attached:")
        print(f"  Blueprint ID: {new_draft.get('page_plan', {}).get('blueprint_id', '')}")
        print(f"  Page type: {new_draft.get('page_plan', {}).get('page_type', '')}")
        print(f"  Locked: {new_draft.get('page_plan', {}).get('locked', False)}\\n")
    except Exception as e:
        print(f"ERROR: Could not attach page plan to draft: {e}")
        return

    drafts.append(new_draft)

    try:
        memory_data = update_workspace_memory(memory_data, new_draft)
        save_json(memory_file, memory_data)
    except Exception as e:
        print(f"ERROR: Could not update site_content_memory.json: {e}")
        return

    intake_item["status"] = "converted_to_draft"
    intake_item["draft_conversion"] = {
        "converted": True,
        "draft_id": new_draft_id,
        "converted_at": today
    }

    if review_mode == "local_market_review":
        queue_file = BASE_DIR / folder_path / "local_review_queue.json"
    else:
        queue_file = BASE_DIR / folder_path / "review_queue.json"

    if not queue_file.exists():
        print(f"ERROR: Review queue file not found: {queue_file}")
        return

    try:
        queue_data = load_json(queue_file)
    except Exception as e:
        print(f"ERROR: Could not read review queue file: {e}")
        return

    queue_data = ensure_queue_structure(queue_data)
    queue_items = queue_data["review_items"]

    if not review_item_exists(queue_items, new_draft_id):
        new_review_item = {
            "draft_id": new_draft_id,
            "intake_id": intake_id,
            "added_at": today,
            "status": "pending_review",
            "working_title": idea_title,
            "target_keyword": target_keyword,
            "notes": ""
        }
        queue_items.append(new_review_item)

    new_draft["draft_status"] = "in_review"

    review_routing = intake_item.get("review_routing", {})
    review_routing["routed"] = True
    review_routing["routed_at"] = today
    intake_item["review_routing"] = review_routing

    try:
        draft_registry_data["scope"] = "workspace"
        draft_registry_data["workspace_id"] = workspace_id

        save_json(INTAKE_FILE, intake_data)
        save_json(draft_registry_file, draft_registry_data)
        save_json(queue_file, queue_data)
    except Exception as e:
        print(f"ERROR: Could not write updated files: {e}")
        return

    print("Cannibalization Check Result:")
    print(f"  Result: {cannibalization.get('result', 'clear')}")
    print(f"  Risk score: {cannibalization.get('risk_score', 0)}")
    print(f"  Notes: {cannibalization.get('notes', '')}\n")

    print(f"Draft created: {new_draft_id}")
    print(f"Draft routed to: {queue_file}")
    print(f"Workspace draft registry updated: {draft_registry_file}")
    print(f"Workspace memory updated: {memory_file}")
    print("Process completed successfully.")


if __name__ == "__main__":
    main()