import json
import sys
from pathlib import Path
from datetime import datetime


BASE_DIR = Path(__file__).resolve().parent.parent
DRAFT_REGISTRY_FILE = BASE_DIR / "sites" / "draft_registry.json"


APPROVABLE_STATUSES = [
    "in_review",
    "fixed",
    "validated",
    "content_generated"
]


def load_json(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path: Path, data):
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_draft_by_id(drafts, draft_id: str):
    for draft in drafts:
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def find_first_approvable_draft(drafts):
    for draft in drafts:
        if draft.get("draft_status") in APPROVABLE_STATUSES:
            return draft
    return None


def main():
    print("=== Sofia: Approve Website Draft ===\n")

    if not DRAFT_REGISTRY_FILE.exists():
        print(f"ERROR: draft_registry.json not found: {DRAFT_REGISTRY_FILE}")
        return

    try:
        draft_registry_data = load_json(DRAFT_REGISTRY_FILE)
    except Exception as e:
        print(f"ERROR: Could not read draft_registry.json: {e}")
        return

    drafts = draft_registry_data.get("drafts", [])

    # 🔥 Get CLI argument if provided
    draft_id_arg = None
    if len(sys.argv) > 1:
        draft_id_arg = sys.argv[1]

    if draft_id_arg:
        draft = find_draft_by_id(drafts, draft_id_arg)
        if not draft:
            print(f"ERROR: Draft not found: {draft_id_arg}")
            return
    else:
        draft = find_first_approvable_draft(drafts)
        if not draft:
            print("No draft found with an approvable status.")
            print(f"Approvable statuses: {', '.join(APPROVABLE_STATUSES)}")
            return

    draft_id = draft.get("draft_id", "")
    status = draft.get("draft_status", "")

    print(f"Target draft: {draft_id}")
    print(f"Current status: {status}")

    if status not in APPROVABLE_STATUSES:
        print(f"ERROR: Draft is not in an approvable status: {status}")
        return

    today = datetime.now().strftime("%Y-%m-%d")

    draft["draft_status"] = "approved"
    draft["approved_at"] = today
    draft["approval"] = {
        "approved": True,
        "approved_at": today,
        "approved_by": "manual",
        "notes": "Approved for AI generation."
    }

    draft["wordpress_status"] = "ready_for_preparation"

    try:
        save_json(DRAFT_REGISTRY_FILE, draft_registry_data)
    except Exception as e:
        print(f"ERROR: Could not save draft_registry.json: {e}")
        return

    print("\nDraft approved successfully.")
    print(f"Draft ID: {draft_id}")
    print("Draft status updated to: approved")


if __name__ == "__main__":
    main()