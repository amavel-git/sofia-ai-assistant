import json
import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

DRAFT_REGISTRY_FILE = BASE_DIR / "sites" / "draft_registry.json"
OUTPUT_DIR = BASE_DIR / "drafts" / "approved"


def load_json(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path: Path, data):
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_approved_draft(drafts):
    for draft in drafts:
        if draft.get("draft_status") == "approved" and draft.get("wordpress_status") == "ready_for_preparation":
            return draft
    return None


def extract_field(content, field_name):
    pattern = rf"{re.escape(field_name)}\s*:\s*(.+)"
    match = re.search(pattern, content, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def extract_section(content, section_name):
    pattern = rf"{section_name}.*?:\s*(.*?)(?:\n\n|\Z)"
    match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def extract_body(content):
    pattern = r"Body Content.*?:\s*(.*)"
    match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def determine_post_type(content_type):
    if content_type in ["blog_post"]:
        return "post"
    return "page"


def parse_list_section(text):
    items = []
    if not text:
        return items

    lines = text.split("\n")
    for line in lines:
        line = line.strip("-• ").strip()
        if line:
            items.append(line)

    return items


def main():
    print("=== Sofia: Prepare WordPress Export (Enhanced) ===\n")

    if not DRAFT_REGISTRY_FILE.exists():
        print("ERROR: draft_registry.json not found")
        return

    try:
        draft_registry_data = load_json(DRAFT_REGISTRY_FILE)
    except Exception as e:
        print(f"ERROR: Could not read draft registry: {e}")
        return

    drafts = draft_registry_data.get("drafts", [])
    draft = find_approved_draft(drafts)

    if not draft:
        print("No approved draft ready for WordPress preparation.")
        return

    draft_id = draft.get("draft_id")
    print(f"Preparing draft: {draft_id}")

    content = draft.get("draft_content", {}).get("content", "")

    if not content:
        print("ERROR: No content found.")
        return

    # Core fields
    title = extract_field(content, "Title")
    meta_title = extract_field(content, "Meta Title")
    meta_description = extract_field(content, "Meta Description")
    slug = extract_field(content, "Slug")
    focus_keyphrase = extract_field(content, "Focus Keyphrase")
    h1 = extract_field(content, "H1")
    body = extract_body(content)

    # Sections
    image_section = extract_section(content, "Image Suggestions")
    internal_links_section = extract_section(content, "Internal Link Suggestions")
    external_links_section = extract_section(content, "External Link Suggestions")

    images = parse_list_section(image_section)
    internal_links = parse_list_section(internal_links_section)
    external_links = parse_list_section(external_links_section)

    wordpress_data = {
        "draft_id": draft_id,
        "workspace_id": draft.get("workspace_id"),
        "site_target": draft.get("site_target"),
        "language": draft.get("language"),
        "locale": draft.get("locale"),

        "post_type": determine_post_type(draft.get("content_type")),

        "title": title,
        "h1": h1,
        "slug": slug,

        "content": body,

        "seo": {
            "meta_title": meta_title,
            "meta_description": meta_description,
            "focus_keyphrase": focus_keyphrase
        },

        "images": images,
        "internal_links": internal_links,
        "external_links": external_links,

        "status": "draft",
        "notes": "Prepared by Sofia for WordPress upload"
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"{draft_id}_wordpress.json"

    try:
        save_json(output_file, wordpress_data)
    except Exception as e:
        print(f"ERROR: Could not save export file: {e}")
        return

    draft["wordpress_status"] = "prepared"
    draft["wordpress_export_file"] = str(output_file)

    try:
        save_json(DRAFT_REGISTRY_FILE, draft_registry_data)
    except Exception as e:
        print(f"ERROR: Could not update draft registry: {e}")
        return

    print("WordPress export prepared successfully.")
    print(f"File: {output_file}")


if __name__ == "__main__":
    main()