import json
import os
import sys
import requests
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

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


def get_drafts(registry):
    return registry["drafts"] if "drafts" in registry else registry


def find_draft(registry, draft_id):
    for d in get_drafts(registry):
        if d["draft_id"] == draft_id:
            return d
    return None


def create_wp_draft(workspace, draft):
    wp_config = workspace.get("wordpress", {})
    if not wp_config.get("enabled"):
        print("WordPress not enabled for this workspace")
        return None

    username = os.getenv(wp_config["username_env"])
    password = os.getenv(wp_config["password_env"])

    if not username or not password:
        print("Missing WordPress credentials in .env")
        return None

    endpoint = f"{workspace['domain']}/wp-json/wp/v2/{wp_config['content_endpoint']}"

    html_content = draft.get("html_content")

    if not html_content:
        print("No HTML content found. Run generate_ai_draft_content first.")
        return None

    payload = {
        "title": draft.get("title"),
        "content": html_content,
        "status": wp_config.get("default_status", "draft"),
        "slug": draft.get("slug")
    }

    response = requests.post(
        endpoint,
        auth=(username, password),
        json=payload,
        timeout=30
    )

    if response.status_code not in [200, 201]:
        print("Error creating WordPress draft:")
        print(response.text)
        return None

    return response.json()


def main():
    if len(sys.argv) < 3:
        print("Usage: python app/create_wordpress_draft.py WORKSPACE_ID DRAFT_ID")
        return

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, workspace_id)

    if not workspace:
        print("Workspace not found")
        return

    draft_registry_path = ROOT / workspace["draft_registry_path"]
    registry = load_json(draft_registry_path)

    draft = find_draft(registry, draft_id)

    if not draft:
        print("Draft not found")
        return

    if draft.get("status") != "ready_for_publishing":
        print("Draft must be ready_for_publishing")
        return

    if draft.get("wordpress_id"):
        print("Draft already pushed to WordPress")
        return

    wp_result = create_wp_draft(workspace, draft)

    if not wp_result:
        return

    draft["wordpress_id"] = wp_result.get("id")
    draft["wordpress_link"] = wp_result.get("link")
    draft["wordpress_created_at"] = now_iso()

    save_json(draft_registry_path, registry)

    print("WordPress draft created successfully.")
    print(f"ID: {draft['wordpress_id']}")
    print(f"Link: {draft['wordpress_link']}")


if __name__ == "__main__":
    main()
