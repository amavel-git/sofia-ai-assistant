import json
import sys
from pathlib import Path
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = ROOT / "data" / "workspaces.json"


VALID_ACTIONS = {
    "approve": "approved_by_examiner",
    "revise": "revision_requested",
    "reject": "rejected_by_examiner"
}


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


def get_drafts_container(draft_registry):
    if isinstance(draft_registry, dict) and "drafts" in draft_registry:
        return draft_registry["drafts"]
    if isinstance(draft_registry, list):
        return draft_registry
    return []


def find_draft(draft_registry, draft_id):
    for draft in get_drafts_container(draft_registry):
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
        print("  python app/update_examiner_review.py WORKSPACE_ID DRAFT_ID approve")
        print("  python app/update_examiner_review.py WORKSPACE_ID DRAFT_ID revise \"comment\"")
        print("  python app/update_examiner_review.py WORKSPACE_ID DRAFT_ID reject \"reason\"")
        return

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]
    action = sys.argv[3].lower().strip()
    comment = " ".join(sys.argv[4:]).strip() if len(sys.argv) > 4 else ""

    if action not in VALID_ACTIONS:
        print(f"Invalid action: {action}")
        print("Allowed actions: approve, revise, reject")
        return

    if action in ["revise", "reject"] and not comment:
        print(f"Action '{action}' requires a comment.")
        return

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

    new_status = VALID_ACTIONS[action]
    timestamp = now_iso()

    review["status"] = new_status
    review["examiner_decision"] = action
    review["examiner_comments"] = comment
    review["examiner_decision_at"] = timestamp
    review["updated_at"] = timestamp

    draft["status"] = new_status
    draft["examiner_decision"] = action
    draft["examiner_comments"] = comment
    draft["updated_at"] = timestamp

    if action == "approve":
        draft["ready_for_publishing"] = True
        review["ready_for_publishing"] = True
    else:
        draft["ready_for_publishing"] = False
        review["ready_for_publishing"] = False

    save_json(review_queue_path, review_queue)
    save_json(draft_registry_path, draft_registry)

    print("Examiner review updated successfully.")
    print(f"Workspace: {workspace_id}")
    print(f"Draft: {draft_id}")
    print(f"Action: {action}")
    print(f"New status: {new_status}")


if __name__ == "__main__":
    main()