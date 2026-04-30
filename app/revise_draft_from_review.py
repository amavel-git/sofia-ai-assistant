import json
import sys
from pathlib import Path
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = ROOT / "data" / "workspaces.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def find_workspace(workspaces, workspace_id):
    for workspace in workspaces.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def get_drafts(draft_registry):
    if isinstance(draft_registry, dict) and "drafts" in draft_registry:
        return draft_registry["drafts"]
    if isinstance(draft_registry, list):
        return draft_registry
    return []


def find_draft(draft_registry, draft_id):
    for draft in get_drafts(draft_registry):
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def find_review(review_queue, draft_id):
    for review in review_queue.get("reviews", []):
        if review.get("draft_id") == draft_id:
            return review
    return None


def main():
    if len(sys.argv) < 4:
        print("Usage:")
        print('  python app/revise_draft_from_review.py WORKSPACE_ID DRAFT_ID "revision note"')
        print("Example:")
        print('  python app/revise_draft_from_review.py local.ao DRAFT-0001 "Updated draft to mention examiner travel outside Luanda."')
        return

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]
    revision_note = " ".join(sys.argv[3:]).strip()

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, workspace_id)

    if not workspace:
        print(f"Workspace not found: {workspace_id}")
        return

    draft_registry_path = ROOT / workspace["draft_registry_path"]
    review_queue_path = ROOT / workspace["review_queue_path"]

    draft_registry = load_json(draft_registry_path)
    review_queue = load_json(review_queue_path)

    draft = find_draft(draft_registry, draft_id)
    review = find_review(review_queue, draft_id)

    if not draft:
        print(f"Draft not found: {draft_id}")
        return

    if not review:
        print(f"Review entry not found for draft: {draft_id}")
        return

    if review.get("status") != "revision_requested":
        print("Revision loop can only run when review status is revision_requested.")
        print(f"Current review status: {review.get('status')}")
        return

    timestamp = now_iso()

    revision_entry = {
        "revision_note": revision_note,
        "based_on_examiner_comments": review.get("examiner_comments", ""),
        "created_at": timestamp
    }

    if "revision_history" not in draft:
        draft["revision_history"] = []

    draft["revision_history"].append(revision_entry)

    draft["status"] = "revised_by_sofia"
    draft["ready_for_publishing"] = False
    draft["updated_at"] = timestamp

    review["status"] = "in_examiner_review"
    review["telegram_notified"] = False
    review["telegram_notified_at"] = None
    review["examiner_decision"] = None
    review["examiner_decision_at"] = None
    review["ready_for_publishing"] = False
    review["sofia_revision_note"] = revision_note
    review["updated_at"] = timestamp

    save_json(draft_registry_path, draft_registry)
    save_json(review_queue_path, review_queue)

    print("Revision loop completed successfully.")
    print(f"Workspace: {workspace_id}")
    print(f"Draft: {draft_id}")
    print("Draft status: revised_by_sofia")
    print("Review status: in_examiner_review")
    print("Telegram notification reset: false")


if __name__ == "__main__":
    main()