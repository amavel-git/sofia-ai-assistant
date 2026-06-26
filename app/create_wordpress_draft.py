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


def resolve_wordpress_endpoint(workspace, draft):
    page_plan = draft.get("page_plan") or {}

    page_type = str(
        page_plan.get("page_type")
        or draft.get("page_type")
        or ""
    ).strip().lower()

    blueprint_id = str(
        page_plan.get("blueprint_id")
        or draft.get("blueprint_id")
        or ""
    ).strip().lower()

    content_type = str(draft.get("content_type", "")).strip().lower()

    # Page Blueprint Intelligence should override older content_type values.
    page_like_types = {
        "landing_page",
        "service_page",
        "city_page",
        "faq_page",
        "pricing_page",
        "pillar_page",
        "educational_page",
        "authority_page",
        "page",
    }

    post_like_types = {
        "blog_post",
        "post",
        "article",
    }

    if page_type in page_like_types or blueprint_id in page_like_types:
        return "pages"

    if page_type in post_like_types or blueprint_id in post_like_types:
        return "posts"

    if content_type in page_like_types:
        return "pages"

    if content_type in post_like_types:
        return "posts"

    return workspace.get("wordpress", {}).get("content_endpoint", "pages")


def format_image_recommendations_html(draft):
    recs = draft.get("image_recommendations") or {}

    if not recs:
        recs = (draft.get("generated_content") or {}).get("image_recommendations") or {}

    if not recs:
        return ""

    lines = [
        "<hr>",
        "<h2>Image Recommendations for Review</h2>",
        "<p><strong>Note:</strong> These are Sofia image planning recommendations. Images are not uploaded automatically in this phase.</p>"
    ]

    featured = recs.get("featured_image") or {}
    if featured:
        lines.extend([
            "<h3>Featured Image</h3>",
            "<ul>",
            f"<li><strong>Filename:</strong> {featured.get('filename', '')}</li>",
            f"<li><strong>Alt text:</strong> {featured.get('alt_text', '')}</li>",
            f"<li><strong>Caption:</strong> {featured.get('caption', '')}</li>",
            f"<li><strong>Placement:</strong> {featured.get('placement', '')}</li>",
            f"<li><strong>Prompt:</strong> {featured.get('prompt', '')}</li>",
            "</ul>"
        ])

    for index, item in enumerate(recs.get("in_article_images") or [], start=1):
        lines.extend([
            f"<h3>In-Article Image {index}</h3>",
            "<ul>",
            f"<li><strong>Filename:</strong> {item.get('filename', '')}</li>",
            f"<li><strong>Alt text:</strong> {item.get('alt_text', '')}</li>",
            f"<li><strong>Caption:</strong> {item.get('caption', '')}</li>",
            f"<li><strong>Placement:</strong> {item.get('placement', '')}</li>",
            f"<li><strong>Prompt:</strong> {item.get('prompt', '')}</li>",
            "</ul>"
        ])

    return "\n".join(lines)


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

    content_endpoint = resolve_wordpress_endpoint(workspace, draft)
    endpoint = f"{workspace['domain']}/wp-json/wp/v2/{content_endpoint}"

    #
    # Prefer the fully assembled WordPress content because it may already
    # contain Gutenberg blocks, inserted AI images, existing images,
    # internal links and other post-processing additions.
    #
    html_content = (
        draft.get("wordpress_content")
        or draft.get("assembled_wordpress_content")
        or draft.get("html_content")
        or draft.get("generated_content", {}).get("content")
        or draft.get("draft_content", {}).get("content")
    )

    if not html_content:
        print("No generated content found. Run generate_website_draft.py first.")
        return None
    
    # PATCH-ES-036
    # Image recommendations remain available in draft metadata,
    # but must not be injected into the public WordPress content body.
    # They are intended for examiner/publishing workflows only.
    image_recommendations_html = format_image_recommendations_html(draft)

    draft_input = draft.get("draft_input", {}) or {}
    seo_input = draft_input.get("seo", {}) or {}

    # SEO source priority:
    # 1. finalized draft fields from generate_website_draft.py
    # 2. normalized nested draft_input["seo"]
    # 3. flat draft_input fallback
    # 4. older draft fields
    # seo_brief is intentionally not used here because it may contain stale values.
    wp_title = (
        draft.get("title")
        or seo_input.get("page_title")
        or draft_input.get("page_title")
        or draft.get("working_title")
        or ""
    )

    wp_slug = (
        draft.get("slug")
        or seo_input.get("slug")
        or draft_input.get("slug")
        or draft.get("suggested_slug")
        or ""
    )

    wp_focus_keyphrase = (
        draft.get("focus_keyphrase")
        or seo_input.get("focus_keyphrase")
        or draft_input.get("focus_keyphrase")
        or draft.get("target_keyword")
        or ""
    )

    wp_seo_title = (
        draft.get("seo_title")
        or seo_input.get("seo_title")
        or draft_input.get("seo_title")
        or wp_title
        or ""
    )

    wp_meta_description = (
        draft.get("meta_description")
        or seo_input.get("meta_description")
        or draft_input.get("meta_description")
        or ""
    )

    payload = {
        "title": wp_title,
        "content": html_content,
        "status": wp_config.get("default_status", "draft"),
        "slug": wp_slug,
        "meta": {
            "_yoast_wpseo_focuskw": wp_focus_keyphrase,
            "_yoast_wpseo_title": wp_seo_title,
            "_yoast_wpseo_metadesc": wp_meta_description
        }
    }

    wordpress_id = draft.get("wordpress_id")

    if wordpress_id:
        endpoint = f"{endpoint}/{wordpress_id}"
        response = requests.post(
            endpoint,
            auth=(username, password),
            json=payload,
            timeout=30
        )
        action = "updating"
    else:
        response = requests.post(
            endpoint,
            auth=(username, password),
            json=payload,
            timeout=30
        )
        action = "creating"

    if response.status_code not in [200, 201]:
        print(f"Error {action} WordPress draft:")
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

    validation = draft.get("validation", {}) or {}
    validation_status = validation.get("status", "")

    if validation_status and validation_status != "passed":
        print(
            f"Draft validation status is '{validation_status}'. "
            "WordPress upload blocked."
        )
        return

    has_generated_content = bool(
        draft.get("html_content")
        or draft.get("generated_content", {}).get("content")
        or draft.get("draft_content", {}).get("content")
    )

    if not has_generated_content:
        print("Draft has no generated content ready for WordPress")
        return

    # Stabilization phase:
    # WordPress is now the first examiner-facing review object.
    # Do not require a prior examiner approval of the intermediate HTML draft.
    if not (
        draft.get("draft_status") == "approved"
        and draft.get("wordpress_status") == "ready_for_preparation"
    ):
        draft["draft_status"] = "wordpress_preparation"
        draft["wordpress_status"] = "ready_for_preparation"

    existing_wordpress_id = draft.get("wordpress_id")

    wp_result = create_wp_draft(workspace, draft)

    if not wp_result:
        return

    draft["wordpress_id"] = wp_result.get("id")
    draft["wordpress_link"] = wp_result.get("link")

    if existing_wordpress_id:
        draft["wordpress_updated_at"] = now_iso()
    else:
        draft["wordpress_created_at"] = now_iso()

    wp_endpoint = resolve_wordpress_endpoint(workspace, draft)
    wp_type_label = wp_result.get("type") or ("page" if wp_endpoint == "pages" else "post")

    draft["wordpress_upload"] = {
        "uploaded": True,
        "uploaded_at": draft.get("wordpress_created_at") or draft.get("wordpress_updated_at") or now_iso(),
        "updated_at": draft.get("wordpress_updated_at"),
        "wordpress_id": wp_result.get("id"),
        "wordpress_link": wp_result.get("link"),
        "wordpress_status": wp_result.get("status", "draft"),
        # Store the REST endpoint used for updates, not only the WP type label.
        # WordPress returns type="page", but REST updates require /pages/{id}.
        "post_type": wp_endpoint,
        "wordpress_type": wp_type_label,
    }

    draft["wordpress_post_type"] = wp_endpoint
    draft["wordpress_type"] = wp_type_label
    draft["wordpress_status"] = "draft_created"
    draft["draft_status"] = "wordpress_review"

    save_json(draft_registry_path, registry)

    if existing_wordpress_id:
        print("WordPress draft updated successfully.")
    else:
        print("WordPress draft created successfully.")
    print(f"ID: {draft['wordpress_id']}")
    print(f"Link: {draft['wordpress_link']}")

if __name__ == "__main__":
    main()
