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
    for workspace in workspaces.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def get_drafts(registry):
    if isinstance(registry, dict) and "drafts" in registry:
        return registry["drafts"]
    if isinstance(registry, list):
        return registry
    return []


def find_draft(registry, draft_id):
    for draft in get_drafts(registry):
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def get_wp_credentials(workspace):
    wp_config = workspace.get("wordpress", {})

    if not wp_config.get("enabled"):
        raise RuntimeError("WordPress is not enabled for this workspace.")

    username = os.getenv(wp_config["username_env"])
    password = os.getenv(wp_config["password_env"])

    if not username or not password:
        raise RuntimeError("Missing WordPress credentials in .env.")

    return username, password, wp_config


def build_payload(draft, wp_config):
    html_content = draft.get("html_content")

    if not html_content:
        raise RuntimeError("No html_content found. Run generate_ai_draft_content.py first.")

    payload = {
        "title": draft.get("title", ""),
        "content": html_content,
        "status": wp_config.get("default_status", "draft")
    }

    if draft.get("slug"):
        payload["slug"] = draft.get("slug")

    if draft.get("meta_description"):
        payload["excerpt"] = draft.get("meta_description")

    return payload


def send_to_wordpress(workspace, draft, username, password, wp_config):
    endpoint_base = f"{workspace['domain']}/wp-json/wp/v2/{wp_config['content_endpoint']}"
    payload = build_payload(draft, wp_config)

    if draft.get("wordpress_id"):
        endpoint = f"{endpoint_base}/{draft['wordpress_id']}"
        action = "updated"
    else:
        endpoint = endpoint_base
        action = "created"

    response = requests.post(
        endpoint,
        auth=(username, password),
        json=payload,
        timeout=30
    )

    if response.status_code not in [200, 201]:
        raise RuntimeError(f"WordPress error {response.status_code}: {response.text}")

    return action, response.json()


def main():
    if len(sys.argv) < 3:
        print("Usage: python app/publish_to_wordpress.py WORKSPACE_ID DRAFT_ID")
        print("Example: python app/publish_to_wordpress.py local.ao DRAFT-0001")
        return

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, workspace_id)

    if not workspace:
        print(f"Workspace not found: {workspace_id}")
        sys.exit(1)

    draft_registry_path = ROOT / workspace["draft_registry_path"]
    registry = load_json(draft_registry_path)

    draft = find_draft(registry, draft_id)

    if not draft:
        print(f"Draft not found: {draft_id}")
        sys.exit(1)

    if draft.get("status") != "ready_for_publishing":
        print("Draft must be ready_for_publishing.")
        sys.exit(1)

    validation = draft.get("validation", {})

    if validation.get("status") != "passed":
        print("Draft validation has not passed.")
        print(f"Current validation status: {validation.get('status')}")
        sys.exit(1)

    try:
        username, password, wp_config = get_wp_credentials(workspace)
        action, wp_result = send_to_wordpress(workspace, draft, username, password, wp_config)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    draft["wordpress_id"] = wp_result.get("id")
    draft["wordpress_link"] = wp_result.get("link")
    draft["wordpress_status"] = wp_result.get("status")
    draft["wordpress_last_action"] = action
    draft["wordpress_last_sync_at"] = now_iso()
    draft["updated_at"] = now_iso()

    if action == "created":
        draft["wordpress_created_at"] = draft.get("wordpress_created_at") or now_iso()
    else:
        draft["wordpress_updated_at"] = now_iso()

    save_json(draft_registry_path, registry)

    print(f"WordPress draft {action} successfully.")
    print(f"Workspace: {workspace_id}")
    print(f"Draft: {draft_id}")
    print(f"WordPress ID: {draft['wordpress_id']}")
    print(f"Link: {draft['wordpress_link']}")


if __name__ == "__main__":
    main()