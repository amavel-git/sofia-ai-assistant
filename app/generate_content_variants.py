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
    for w in workspaces["workspaces"]:
        if w["workspace_id"] == workspace_id:
            return w
    return None


def get_drafts(draft_registry):
    if "drafts" in draft_registry:
        return draft_registry["drafts"]
    return draft_registry


def find_draft(draft_registry, draft_id):
    for d in get_drafts(draft_registry):
        if d["draft_id"] == draft_id:
            return d
    return None


def main():
    if len(sys.argv) < 3:
        print("Usage: python app/generate_content_variants.py WORKSPACE_ID DRAFT_ID")
        return

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, workspace_id)

    if not workspace:
        print("Workspace not found")
        return

    draft_registry_path = ROOT / workspace["draft_registry_path"]
    variants_path = ROOT / workspace["folder_path"] / "content_variants.json"

    draft_registry = load_json(draft_registry_path)
    draft = find_draft(draft_registry, draft_id)

    if not draft:
        print("Draft not found")
        return

    if draft.get("status") != "ready_for_publishing":
        print("Draft must be ready_for_publishing before expansion")
        sys.exit(1)

    # 🔹 Simple content generation (placeholder logic)
    title = draft.get("title", "")
    keyword = draft.get("focus_keyphrase", "")

    mini_blog = f"{title}\n\nThis article explains {keyword} in a simple and practical way for clients."
    facebook_post = f"Did you know about {keyword}? Contact us for professional and confidential polygraph testing."
    linkedin_post = f"Polygraph testing plays an important role in professional environments. Learn more about {keyword}."

    variant_entry = {
        "draft_id": draft_id,
        "created_at": now_iso(),
        "variants": {
            "mini_blog": mini_blog,
            "facebook_post": facebook_post,
            "linkedin_post": linkedin_post,
            "image_assets": {
                "website": {
                    "type": "stock_preferred",
                    "prompt": f"Professional polygraph test setting related to {keyword}",
                    "filename": f"{keyword.replace(' ', '-')}.jpg",
                    "alt_text": f"{keyword} professional polygraph test"
                },
                "social": {
                    "type": "ai_allowed",
                    "prompt": f"Modern visual representing {keyword} in a clean and professional style",
                    "filename": f"{keyword.replace(' ', '-')}-social.jpg",
                    "alt_text": f"{keyword} concept visual"
                }
            }
        }
    }

    # Save
    if variants_path.exists():
        data = load_json(variants_path)
    else:
        data = {"variants": []}

    data["variants"].append(variant_entry)
    save_json(variants_path, data)

    print("Content variants generated successfully.")


if __name__ == "__main__":
    main()