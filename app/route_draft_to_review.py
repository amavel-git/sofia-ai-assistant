import json
from pathlib import Path
from datetime import datetime


BASE_DIR = Path(__file__).resolve().parent.parent

INTAKE_FILE = BASE_DIR / "sites" / "content_intake.json"
DRAFT_REGISTRY_FILE = BASE_DIR / "sites" / "draft_registry.json"


def load_json(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path: Path, data):
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def ensure_queue_structure(queue_data):
    if "review_items" not in queue_data or not isinstance(queue_data["review_items"], list):
        queue_data["review_items"] = []
    return queue_data


def review_item_exists(queue_items, draft_id: str):
    for item in queue_items:
        if item.get("draft_id") == draft_id:
            return True
    return False


def find_intake_by_id(content_ideas, intake_id: str):
    for item in content_ideas:
        if item.get("intake_id") == intake_id:
            return item
    return None


def main():
    print("=== Sofia Phase 1: Route Draft To Review ===\n")

    if not INTAKE_FILE.exists():
        print(f"ERROR: content_intake.json not found: {INTAKE_FILE}")
        return

    if not DRAFT_REGISTRY_FILE.exists():
        print(f"ERROR: draft_registry.json not found: {DRAFT_REGISTRY_FILE}")
        return

    try:
        intake_data = load_json(INTAKE_FILE)
        draft_registry_data = load_json(DRAFT_REGISTRY_FILE)
    except Exception as e:
        print(f"ERROR: Could not read input files: {e}")
        return

    drafts = draft_registry_data.get("drafts", [])
    content_ideas = intake_data.get("content_ideas", [])

    if not drafts:
        print("No drafts found in draft_registry.json")
        return

    draft = drafts[0]

    draft_id = draft.get("draft_id", "")
    intake_id = draft.get("created_from_intake_id", "")
    workspace_type = draft.get("workspace_type", "")
    workspace_path = draft.get("workspace_path", "")
    working_title = draft.get("working_title", "")
    target_keyword = draft.get("target_keyword", "")
    draft_status = draft.get("draft_status", "")

    print(f"Processing draft: {draft_id}")
    print(f"Linked intake: {intake_id}")
    print(f"Workspace type: {workspace_type}")
    print(f"Workspace path: {workspace_path}")
    print(f"Current draft status: {draft_status}\n")

    if draft_status != "draft_created":
        print("Routing skipped: draft is not in 'draft_created' status.")
        return

    if workspace_type == "local_market":
        queue_file = BASE_DIR / workspace_path / "local_review_queue.json"
    else:
        queue_file = BASE_DIR / workspace_path / "review_queue.json"

    print(f"Target review queue: {queue_file}")

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

    if review_item_exists(queue_items, draft_id):
        print(f"Draft {draft_id} already exists in the review queue.")
        return

    today = datetime.now().strftime("%Y-%m-%d")

    new_review_item = {
        "draft_id": draft_id,
        "intake_id": intake_id,
        "added_at": today,
        "status": "pending_review",
        "working_title": working_title,
        "target_keyword": target_keyword,
        "notes": ""
    }

    queue_items.append(new_review_item)

    draft["draft_status"] = "in_review"

    intake_item = find_intake_by_id(content_ideas, intake_id)
    if intake_item:
        review_routing = intake_item.get("review_routing", {})
        review_routing["routed"] = True
        review_routing["routed_at"] = today
        intake_item["review_routing"] = review_routing

    try:
        save_json(queue_file, queue_data)
        save_json(DRAFT_REGISTRY_FILE, draft_registry_data)
        save_json(INTAKE_FILE, intake_data)
    except Exception as e:
        print(f"ERROR: Could not write updated files: {e}")
        return

    print("\nDraft routed successfully.")
    print(f"Draft status updated to: in_review")
    print(f"Review item added to: {queue_file}")


if __name__ == "__main__":
    main()