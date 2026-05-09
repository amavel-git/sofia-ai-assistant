import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone
from seo_field_rules import normalize_seo_fields

from workspace_paths import (
    find_draft_any_workspace,
    get_workspace_draft_registry_path,
)


SOFIA_ROOT = Path(__file__).resolve().parents[1]

DRAFT_REGISTRY_FILE = SOFIA_ROOT / "sites" / "draft_registry.json"
INTAKE_FILE = SOFIA_ROOT / "sites" / "content_intake.json"
EXPORT_DIR = SOFIA_ROOT / "drafts" / "wordpress_ready"


EXPORTABLE_STATUSES = [
    "content_generated",
    "content_revised",
    "internal_links_added",
    "ai_internal_links_added",
    "approved",
    "completed"
]


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_draft_registry_for_draft(draft_id):
    workspace_id, draft = find_draft_any_workspace(draft_id)

    if not workspace_id or not draft:
        raise RuntimeError(f"Draft not found in any workspace registry: {draft_id}")

    registry_path = get_workspace_draft_registry_path(workspace_id)
    registry_data = load_json(registry_path)

    return workspace_id, registry_path, registry_data, draft

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def slugify(text: str) -> str:
    text = text.lower().strip()
    replacements = {
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "õ": "o", "ô": "o",
        "ú": "u",
        "ç": "c"
    }

    for original, replacement in replacements.items():
        text = text.replace(original, replacement)

    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)

    return text.strip("-")


def find_intake_by_id(content_ideas, intake_id):
    for item in content_ideas:
        if item.get("intake_id") == intake_id:
            return item
    return None


def find_draft_by_id(drafts, draft_id):
    for draft in drafts:
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def build_wordpress_package(draft, intake):
    draft_input = intake.get("draft_input", {})
    seo = draft_input.get("seo", {})
    generated = draft.get("generated_content", {})

    title = (
        seo.get("page_title")
        or draft.get("title")
        or draft.get("working_title", "")
    )

    raw_slug = (
        seo.get("slug")
        or draft.get("slug")
        or draft.get("suggested_slug")
        or slugify(title)
    )

    seo_fields = normalize_seo_fields(
        title=title,
        focus_keyphrase=seo.get("focus_keyphrase") or draft.get("focus_keyphrase") or draft.get("target_keyword"),
        slug=raw_slug,
        meta_description=seo.get("meta_description") or draft.get("meta_description"),
        seo_title=seo.get("seo_title") or draft.get("seo_title") or title,
        fallback_topic=draft.get("target_keyword") or title,
        language=draft.get("language", "")
    )

    slug = seo_fields["slug"]

    return {
        "exported_at": now_utc(),
        "source": "sofia",
        "draft_id": draft.get("draft_id", ""),
        "intake_id": draft.get("created_from_intake_id", ""),
        "workspace_id": draft.get("workspace_id", ""),
        "workspace_path": draft.get("workspace_path", ""),
        "site_target": draft.get("site_target", ""),
        "language": draft.get("language", ""),
        "wordpress": {
            "post_status": "draft",
            "post_type": "post" if draft.get("content_type") == "blog_post" else "page",
            "title": title,
            "slug": slug,
            "content_html": generated.get("content", "")
        },
        "yoast_seo": {
            "focus_keyphrase": seo_fields["focus_keyphrase"],
            "seo_title": seo_fields["seo_title"],
            "meta_description": seo_fields["meta_description"]
        },
        "image": {
            "alt_text": seo.get("image_alt_text", ""),
            "filename": seo.get("image_filename", "")
        },
        "review": {
            "requires_final_human_review": True,
            "notes": "Exported by Sofia. Review before publishing."
        }
    }


def main():
    print("=== Sofia: Export WordPress Package ===\n")

    if len(sys.argv) != 2:
        print("Usage:")
        print("python app/export_wordpress_package.py DRAFT-0005")
        return

    draft_id = sys.argv[1]

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        workspace_id, draft_registry_file, draft_registry_data, draft = load_draft_registry_for_draft(draft_id)
    except Exception as e:
        print(f"ERROR: {e}")
        return

    intake_data = load_json(INTAKE_FILE)
    content_ideas = intake_data.get("content_ideas", [])

    if not draft:
        print(f"ERROR: Draft not found: {draft_id}")
        return

    status = draft.get("draft_status", "")

    if status not in EXPORTABLE_STATUSES:
        print(f"ERROR: Draft is not exportable. Current status: {status}")
        print(f"Exportable statuses: {', '.join(EXPORTABLE_STATUSES)}")
        return

    intake_id = draft.get("created_from_intake_id", "")
    intake = find_intake_by_id(content_ideas, intake_id)

    if not intake:
        print(f"ERROR: Linked intake not found: {intake_id}")
        return

    if not draft.get("generated_content", {}).get("content"):
        print("ERROR: Draft has no generated content.")
        return

    package = build_wordpress_package(draft, intake)

    export_file = EXPORT_DIR / f"{draft_id.lower()}-wordpress-package.json"
    save_json(export_file, package)

    draft["wordpress_export"] = {
        "exported": True,
        "exported_at": now_utc(),
        "export_file": str(export_file),
        "status": "package_created"
    }

    draft["wordpress_export_file"] = str(export_file)
    draft["wordpress_status"] = "package_created"

    draft_registry_data["scope"] = "workspace"
    draft_registry_data["workspace_id"] = workspace_id
    save_json(draft_registry_file, draft_registry_data)

    print("WordPress package created.")
    print(f"Draft ID: {draft_id}")
    print(f"Export file: {export_file}")
    print(f"Workspace registry: {draft_registry_file}")


if __name__ == "__main__":
    main()