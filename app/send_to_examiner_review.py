import json
import sys
from pathlib import Path
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = ROOT / "data" / "workspaces.json"


BLOCK_DUPLICATE_STATUSES = [
    "in_examiner_review",
    "revision_requested",
    "revised_by_sofia",
    "approved_by_examiner",
    "ready_for_publishing",
    "published"
]


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


def find_draft(draft_registry, draft_id):
    drafts = draft_registry.get("drafts", draft_registry)

    for draft in drafts:
        if draft.get("draft_id") == draft_id:
            return draft

    return None


def existing_review_for_draft(review_queue, draft_id):
    for review in review_queue.get("reviews", []):
        if review.get("draft_id") == draft_id:
            return review
    return None


def generate_review_id(review_queue):
    reviews = review_queue.get("reviews", [])
    return f"REVIEW-{len(reviews) + 1:04d}"


def main():
    if len(sys.argv) < 3:
        print("Usage: python app/send_to_examiner_review.py WORKSPACE_ID DRAFT_ID")
        print("Example: python app/send_to_examiner_review.py local.ao DRAFT-0001")
        return

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, workspace_id)

    if not workspace:
        print(f"Workspace not found: {workspace_id}")
        sys.exit(1)

    draft_registry_path = ROOT / workspace["draft_registry_path"]
    review_queue_path = ROOT / workspace["review_queue_path"]

    draft_registry = load_json(draft_registry_path)
    review_queue = load_json(review_queue_path)

    draft = find_draft(draft_registry, draft_id)

    if not draft:
        print(f"Draft not found: {draft_id}")
        sys.exit(1)

    existing_review = existing_review_for_draft(review_queue, draft_id)

    if existing_review:
        existing_status = existing_review.get("status", "")

        if existing_status in BLOCK_DUPLICATE_STATUSES:
            print("Duplicate review prevented.")
            print(f"Workspace: {workspace_id}")
            print(f"Draft: {draft_id}")
            print(f"Existing review: {existing_review.get('review_id')}")
            print(f"Existing status: {existing_status}")
            return

    review = {
        "review_id": generate_review_id(review_queue),
        "draft_id": draft_id,
        "workspace_id": workspace_id,
        "country": workspace.get("country", ""),
        "language": workspace.get("language", draft.get("language", "")),
        "title": draft.get("title", ""),
        "content_type": draft.get("content_type", "seo_page"),
        "focus_keyphrase": draft.get("focus_keyphrase", ""),
        "status": "in_examiner_review",
        "review_priority": draft.get("review_priority", "normal"),
        "telegram_group": workspace.get("telegram_group", ""),
        "telegram_group_id": workspace.get("telegram_group_id", None),
        "telegram_notified": False,
        "examiner_decision": None,
        "examiner_comments": "",
        "created_at": now_iso(),
        "updated_at": now_iso()
    }

    if "reviews" not in review_queue:
        review_queue["reviews"] = []

    review_queue["reviews"].append(review)

    draft["status"] = "in_examiner_review"
    draft["updated_at"] = now_iso()

    save_json(review_queue_path, review_queue)
    save_json(draft_registry_path, draft_registry)

    print("Draft sent to examiner review successfully.")
    print(f"Workspace: {workspace_id}")
    print(f"Draft: {draft_id}")
    print(f"Review queue: {review_queue_path}")


if __name__ == "__main__":
    main()