import base64
import json
import os
import sys
import urllib.request
from pathlib import Path
from datetime import datetime, timezone


SOFIA_ROOT = Path(__file__).resolve().parents[1]

DRAFT_REGISTRY_FILE = SOFIA_ROOT / "sites" / "draft_registry.json"
INTAKE_FILE = SOFIA_ROOT / "sites" / "content_intake.json"


UPLOADABLE_STATUSES = [
    "content_generated",
    "internal_links_added",
    "ai_internal_links_added"
]


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def find_draft(drafts, draft_id):
    for draft in drafts:
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def find_intake(content_ideas, intake_id):
    for item in content_ideas:
        if item.get("intake_id") == intake_id:
            return item
    return None


def load_wordpress_config(workspace_path):
    config_path = SOFIA_ROOT / workspace_path / "wordpress_config.json"

    if not config_path.exists():
        raise FileNotFoundError(f"Missing WordPress config: {config_path}")

    return load_json(config_path)


def get_auth_header(username, app_password):
    raw = f"{username}:{app_password}".encode("utf-8")
    token = base64.b64encode(raw).decode("utf-8")
    return f"Basic {token}"


def build_post_payload(draft, intake, wp_config):
    draft_input = intake.get("draft_input", {})
    seo = draft_input.get("seo", {})
    generated = draft.get("generated_content", {})

    title = seo.get("page_title") or draft.get("working_title", "")
    slug = seo.get("slug") or draft.get("suggested_slug", "")

    content_type = draft_input.get("content_type", draft.get("content_type", ""))

    POST_TYPE_MAP = {
        "blog_post": "posts",
        "landing_page": "pages",
        "service_page": "pages",
        "pillar_page": "pages"
    }

    post_type = POST_TYPE_MAP.get(content_type, "posts")

    return post_type, {
        "status": wp_config.get("default_status", "draft"),
        "title": title,
        "slug": slug,
        "content": generated.get("content", ""),
        "excerpt": seo.get("meta_description", ""),

        "meta": {
            "_yoast_wpseo_title": seo.get("seo_title", ""),
            "_yoast_wpseo_metadesc": seo.get("meta_description", ""),
            "_yoast_wpseo_focuskw": seo.get("focus_keyphrase", "")
        }
    }


def upload_to_wordpress(api_base, post_type, payload, username, app_password):
    url = f"{api_base}/{post_type}"

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": get_auth_header(username, app_password)
        }
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    print("=== Sofia: Upload WordPress Draft ===\n")

    if len(sys.argv) != 2:
        print("Usage:")
        print("python app/upload_wordpress_draft.py DRAFT-0005")
        return

    draft_id = sys.argv[1]

    draft_data = load_json(DRAFT_REGISTRY_FILE)
    intake_data = load_json(INTAKE_FILE)

    drafts = draft_data.get("drafts", [])
    content_ideas = intake_data.get("content_ideas", [])

    draft = find_draft(drafts, draft_id)

    if not draft:
        print(f"ERROR: Draft not found: {draft_id}")
        return

    validation = draft.get("validation", {})
    if validation.get("status") != "passed":
        print("ERROR: Draft validation has not passed.")
        print(f"Current validation status: {validation.get('status')}")
        return

    if draft.get("draft_status") not in UPLOADABLE_STATUSES:
        print(f"ERROR: Draft status is not uploadable: {draft.get('draft_status')}")
        return

    if draft.get("wordpress_upload", {}).get("uploaded"):
        print("ERROR: Draft already uploaded to WordPress.")
        print(f"WordPress ID: {draft.get('wordpress_upload', {}).get('wordpress_id')}")
        return

    intake_id = draft.get("created_from_intake_id", "")
    intake = find_intake(content_ideas, intake_id)

    if not intake:
        print(f"ERROR: Linked intake not found: {intake_id}")
        return

    if not draft.get("generated_content", {}).get("content"):
        print("ERROR: Draft has no generated content.")
        return

    try:
        wp_config = load_wordpress_config(draft.get("workspace_path", ""))
    except Exception as e:
        print(f"ERROR: {e}")
        return

    username = os.getenv(wp_config.get("username_env", ""))
    app_password = os.getenv(wp_config.get("application_password_env", ""))

    if not username or not app_password:
        print("ERROR: WordPress credentials are missing from environment variables.")
        print(f"Username env: {wp_config.get('username_env')}")
        print(f"Password env: {wp_config.get('application_password_env')}")
        return

    post_type, payload = build_post_payload(draft, intake, wp_config)

    try:
        result = upload_to_wordpress(
            api_base=wp_config["api_base"],
            post_type=post_type,
            payload=payload,
            username=username,
            app_password=app_password
        )
    except Exception as e:
        print(f"ERROR: WordPress upload failed: {e}")
        return

    draft["wordpress_upload"] = {
        "uploaded": True,
        "uploaded_at": now_utc(),
        "wordpress_id": result.get("id"),
        "wordpress_link": result.get("link"),
        "wordpress_status": result.get("status"),
        "post_type": post_type
    }

    draft["wordpress_status"] = "uploaded_as_draft"

    save_json(DRAFT_REGISTRY_FILE, draft_data)

    print("WordPress draft uploaded successfully.")
    print(f"Draft ID: {draft_id}")
    print(f"WordPress ID: {result.get('id')}")
    print(f"Link: {result.get('link')}")


if __name__ == "__main__":
    main()