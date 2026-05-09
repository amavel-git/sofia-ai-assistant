import base64
import json
import os
import sys
import urllib.request
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from seo_field_rules import normalize_seo_fields

from workspace_paths import (
    find_draft_any_workspace,
    get_workspace_draft_registry_path,
)

SOFIA_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(SOFIA_ROOT / ".env", override=True)

DRAFT_REGISTRY_FILE = SOFIA_ROOT / "sites" / "draft_registry.json"
INTAKE_FILE = SOFIA_ROOT / "sites" / "content_intake.json"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_draft_registry_for_draft(draft_id):
    """
    Load the workspace-level draft registry and return the draft object
    from that loaded registry data.

    Important:
    find_draft_any_workspace() identifies the workspace, but we must then
    re-find the draft inside registry_data so modifications are saved back
    into the same object that will be written to disk.
    """

    workspace_id, found_draft = find_draft_any_workspace(draft_id)

    if not workspace_id or not found_draft:
        raise RuntimeError(f"Draft not found in any workspace registry: {draft_id}")

    registry_path = get_workspace_draft_registry_path(workspace_id)
    registry_data = load_json(registry_path)

    for draft in registry_data.get("drafts", []):
        if draft.get("draft_id") == draft_id:
            return workspace_id, registry_path, registry_data, draft

    raise RuntimeError(
        f"Draft {draft_id} was found in workspace lookup, but not found again "
        f"in loaded registry: {registry_path}"
    )


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


def build_update_payload(draft, intake):
    draft_input = intake.get("draft_input", {})
    seo = draft_input.get("seo", {})
    generated = draft.get("generated_content", {})

    title = (
        seo.get("page_title")
        or draft.get("title")
        or draft.get("working_title", "")
    )

    slug = (
        seo.get("slug")
        or draft.get("slug")
        or draft.get("suggested_slug", "")
    )

    seo_title = (
        seo.get("seo_title")
        or draft.get("seo_title")
        or draft.get("title")
        or title
    )

    meta_description = (
        seo.get("meta_description")
        or draft.get("meta_description")
        or ""
    )

    focus_keyphrase = (
        seo.get("focus_keyphrase")
        or draft.get("focus_keyphrase")
        or draft.get("target_keyword")
        or ""
    )

    seo_fields = normalize_seo_fields(
        title=title,
        focus_keyphrase=focus_keyphrase,
        slug=slug,
        meta_description=meta_description,
        seo_title=seo_title,
        fallback_topic=draft.get("target_keyword") or title,
        language=draft.get("language", "")
    )

    slug = seo_fields["slug"]
    seo_title = seo_fields["seo_title"]
    meta_description = seo_fields["meta_description"]
    focus_keyphrase = seo_fields["focus_keyphrase"]

    return {
        "title": title,
        "slug": slug,
        "content": generated.get("content", ""),
        "excerpt": meta_description,
        "meta": {
            "_yoast_wpseo_title": seo_title,
            "_yoast_wpseo_metadesc": meta_description,
            "_yoast_wpseo_focuskw": focus_keyphrase
        }
    }


def update_wordpress_post(api_base, post_type, wordpress_id, payload, username, app_password):
    url = f"{api_base}/{post_type}/{wordpress_id}"

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
    print("=== Sofia: Update WordPress Draft ===\n")

    if len(sys.argv) != 2:
        print("Usage:")
        print("python app/update_wordpress_draft.py DRAFT-0005")
        return

    draft_id = sys.argv[1]

    try:
        workspace_id, draft_registry_file, draft_data, draft = load_draft_registry_for_draft(draft_id)
    except Exception as e:
        print(f"ERROR: {e}")
        return

    intake_data = load_json(INTAKE_FILE)
    content_ideas = intake_data.get("content_ideas", [])

    if not draft:
        print(f"ERROR: Draft not found: {draft_id}")
        return

    validation = draft.get("validation", {})
    if validation.get("status") != "passed":
        print("ERROR: Draft validation has not passed.")
        print(f"Current validation status: {validation.get('status')}")
        return

    upload_info = draft.get("wordpress_upload", {}) or {}
    update_info = draft.get("wordpress_update", {}) or {}

    wordpress_id = (
        update_info.get("wordpress_id")
        or upload_info.get("wordpress_id")
        or draft.get("wordpress_id")
    )

    post_type = (
        update_info.get("post_type")
        or upload_info.get("post_type")
        or draft.get("wordpress_post_type")
    )

    if not wordpress_id or not post_type:
        print("ERROR: Draft has not been uploaded to WordPress yet.")
        sys.exit(1)

    if not wordpress_id or not post_type:
        print("ERROR: Missing WordPress ID or post type in draft registry.")
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
        return

    payload = build_update_payload(draft, intake)

    try:
        result = update_wordpress_post(
            api_base=wp_config["api_base"],
            post_type=post_type,
            wordpress_id=wordpress_id,
            payload=payload,
            username=username,
            app_password=app_password
        )
    except Exception as e:
        print(f"ERROR: WordPress update failed: {e}")
        return

    draft["wordpress_update"] = {
        "updated": True,
        "updated_at": now_utc(),
        "wordpress_id": result.get("id"),
        "wordpress_link": result.get("link"),
        "wordpress_status": result.get("status"),
        "post_type": post_type
    }

    draft["wordpress_status"] = "updated_as_draft"
    draft["ready_for_publishing"] = False

    draft_data["scope"] = "workspace"
    draft_data["workspace_id"] = workspace_id
    save_json(draft_registry_file, draft_data)

    print("WordPress draft updated successfully.")
    print(f"Draft ID: {draft_id}")
    print(f"WordPress ID: {result.get('id')}")
    print(f"Link: {result.get('link')}")
    print(f"Workspace registry: {draft_registry_file}")


if __name__ == "__main__":
    main()