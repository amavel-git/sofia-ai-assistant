import json
import sys
from pathlib import Path
from datetime import datetime, timezone


SOFIA_ROOT = Path(__file__).resolve().parents[1]

DRAFT_REGISTRY_FILE = SOFIA_ROOT / "sites" / "draft_registry.json"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def find_draft_by_id(drafts, draft_id: str):
    for draft in drafts:
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def main():
    print("=== Sofia: Regenerate Draft Content ===\n")

    if len(sys.argv) != 2:
        print("Usage:")
        print("python app/regenerate_draft_content.py DRAFT-0005")
        return

    draft_id = sys.argv[1]

    if not DRAFT_REGISTRY_FILE.exists():
        print(f"ERROR: draft_registry.json not found: {DRAFT_REGISTRY_FILE}")
        return

    draft_data = load_json(DRAFT_REGISTRY_FILE)
    drafts = draft_data.get("drafts", [])

    draft = find_draft_by_id(drafts, draft_id)

    if not draft:
        print(f"ERROR: Draft not found: {draft_id}")
        return

    previous_status = draft.get("draft_status", "")

    if previous_status not in ["content_generated", "internal_links_added", "ai_internal_links_added"]:
        print(f"ERROR: Draft is not in content_generated status: {previous_status}")
        print("Only generated drafts should be reset for regeneration.")
        return

    if draft.get("generated_content"):
        draft["previous_generated_content"] = draft.get("generated_content")

    draft.pop("generated_content", None)

    draft["draft_status"] = "approved"
    draft["regeneration"] = {
        "requested": True,
        "requested_at": now_utc(),
        "previous_status": previous_status,
        "notes": "Reset to approved for AI regeneration."
    }

    save_json(DRAFT_REGISTRY_FILE, draft_data)

    print("Draft reset for regeneration.")
    print(f"Draft ID: {draft_id}")
    print("Draft status updated to: approved")
    print("\nNow run:")
    print("python app/generate_draft_content.py")


if __name__ == "__main__":
    main()