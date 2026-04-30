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


def draft_already_exists(drafts, intake_id: str):
    for draft in drafts:
        if draft.get("created_from_intake_id") == intake_id:
            return draft
    return None


def main():
    print("=== Sofia Phase 1: Create Draft From Intake ===\n")

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

    content_ideas = intake_data.get("content_ideas", [])
    drafts = draft_registry_data.get("drafts", [])

    if not content_ideas:
        print("No content ideas found in content_intake.json")
        return

    intake_item = content_ideas[0]

    intake_id = intake_item.get("intake_id", "")
    status = intake_item.get("status", "")
    cannibalization = intake_item.get("cannibalization_check", {})
    cannibalization_result = cannibalization.get("result", "")

    print(f"Processing intake: {intake_id}")
    print(f"Current status: {status}")
    print(f"Cannibalization result: {cannibalization_result}\n")

    if status != "checked":
        print("Draft creation skipped: intake item is not in 'checked' status.")
        return

    if cannibalization_result != "clear":
        print("Draft creation skipped: cannibalization result is not 'clear'.")
        return

    existing_draft = draft_already_exists(drafts, intake_id)
    if existing_draft:
        print(f"Draft already exists for this intake item: {existing_draft.get('draft_id')}")
        return

    new_draft_id = generate_next_draft_id(drafts)
    today = datetime.now().strftime("%Y-%m-%d")

    workspace_type = intake_item.get("workspace_type", "")
    workspace_id = intake_item.get("workspace_id", "")
    workspace_path = intake_item.get("workspace_path", "")
    language = intake_item.get("language", "")
    site_target = intake_item.get("site_target", "")
    content_type = intake_item.get("content_type", "")
    idea_title = intake_item.get("idea_title", "")
    target_keyword = intake_item.get("target_keyword", "")
    secondary_keywords = intake_item.get("secondary_keywords", [])
    search_intent = intake_item.get("search_intent", "")
    suggested_slug = intake_item.get("suggested_slug", "")
    cannibalization_notes = cannibalization.get("notes", "")

    review_target = intake_item.get("review_routing", {})
    target_queue = review_target.get("target_queue", "")

    queue_level = "local" if workspace_type == "local_market" else "workspace"

    new_draft = {
        "draft_id": new_draft_id,
        "created_at": today,
        "created_from_intake_id": intake_id,
        "workspace_type": workspace_type,
        "workspace_id": workspace_id,
        "workspace_path": workspace_path,
        "language": language,
        "site_target": site_target,
        "content_type": content_type,
        "working_title": idea_title,
        "target_keyword": target_keyword,
        "secondary_keywords": secondary_keywords,
        "search_intent": search_intent,
        "suggested_slug": suggested_slug,
        "cannibalization_result": cannibalization_result,
        "cannibalization_notes": cannibalization_notes,
        "review_target": {
            "queue_level": queue_level,
            "queue_id": target_queue
        },
        "draft_status": "draft_created",
        "wordpress_status": "not_prepared",
        "assigned_reviewer": "",
        "notes": ""
    }

    drafts.append(new_draft)

    intake_item["status"] = "converted_to_draft"
    intake_item["draft_conversion"] = {
        "converted": True,
        "draft_id": new_draft_id,
        "converted_at": today
    }

    try:
        save_json(DRAFT_REGISTRY_FILE, draft_registry_data)
        save_json(INTAKE_FILE, intake_data)
    except Exception as e:
        print(f"ERROR: Could not write updated files: {e}")
        return

    print("Draft created successfully.")
    print(f"New draft ID: {new_draft_id}")
    print("Updated draft_registry.json and content_intake.json")


if __name__ == "__main__":
    main()