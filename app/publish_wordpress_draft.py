import json
import requests
import base64
from pathlib import Path
from dotenv import load_dotenv
import os


BASE_DIR = Path(__file__).resolve().parent.parent
DRAFT_REGISTRY_FILE = BASE_DIR / "sites" / "draft_registry.json"

load_dotenv(BASE_DIR / ".env")


WP_SITE_URL = os.getenv("WP_SITE_URL", "").rstrip("/")
WP_USERNAME = os.getenv("WP_USERNAME", "")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD", "")


def load_json(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path: Path, data):
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_prepared_draft(drafts):
    for draft in drafts:
        if draft.get("wordpress_status") == "prepared":
            return draft
    return None


def build_auth_headers():
    credentials = f"{WP_USERNAME}:{WP_APP_PASSWORD}"
    token = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")

    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json"
    }


def create_wordpress_draft(wp_data):
    endpoint = f"{WP_SITE_URL}/wp-json/wp/v2/pages"

    payload = {
        "title": wp_data.get("title", ""),
        "slug": wp_data.get("slug", ""),
        "content": wp_data.get("content", ""),
        "status": "draft"
    }

    response = requests.post(
        endpoint,
        headers=build_auth_headers(),
        json=payload,
        timeout=60
    )

    response.raise_for_status()
    return response.json()


def main():
    print("=== Sofia: Publish WordPress Draft ===\n")

    if not WP_SITE_URL or not WP_USERNAME or not WP_APP_PASSWORD:
        print("ERROR: Missing WordPress credentials in .env")
        return

    if not DRAFT_REGISTRY_FILE.exists():
        print(f"ERROR: draft_registry.json not found: {DRAFT_REGISTRY_FILE}")
        return

    try:
        draft_registry_data = load_json(DRAFT_REGISTRY_FILE)
    except Exception as e:
        print(f"ERROR: Could not read draft_registry.json: {e}")
        return

    drafts = draft_registry_data.get("drafts", [])
    draft = find_prepared_draft(drafts)

    if not draft:
        print("No prepared WordPress draft found.")
        return

    draft_id = draft.get("draft_id", "")
    export_file = draft.get("wordpress_export_file", "")

    if not export_file:
        print(f"ERROR: Draft {draft_id} has no wordpress_export_file.")
        return

    export_path = Path(export_file)

    if not export_path.exists():
        print(f"ERROR: Export file not found: {export_path}")
        return

    try:
        wp_data = load_json(export_path)
    except Exception as e:
        print(f"ERROR: Could not read WordPress export file: {e}")
        return

    print(f"Creating WordPress draft for: {draft_id}")
    print(f"Site: {WP_SITE_URL}")
    print(f"Title: {wp_data.get('title', '')}")

    try:
        result = create_wordpress_draft(wp_data)
    except requests.exceptions.HTTPError as e:
        print(f"ERROR: WordPress draft creation failed: {e}")
        if e.response is not None:
            print("Response:")
            print(e.response.text)
        return
    except Exception as e:
        print(f"ERROR: WordPress draft creation failed: {e}")
        return

    wp_id = result.get("id")
    wp_link = result.get("link")

    draft["wordpress_status"] = "draft_created"
    draft["wordpress_draft"] = {
        "wp_id": wp_id,
        "link": wp_link,
        "status": "draft"
    }

    try:
        save_json(DRAFT_REGISTRY_FILE, draft_registry_data)
    except Exception as e:
        print(f"ERROR: Could not update draft_registry.json: {e}")
        return

    print("\nWordPress draft created successfully.")
    print(f"WordPress ID: {wp_id}")
    print(f"Draft link: {wp_link}")


if __name__ == "__main__":
    main()