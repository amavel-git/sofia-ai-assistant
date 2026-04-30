import json
import re
import sys
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]
DRAFT_REGISTRY_FILE = SOFIA_ROOT / "sites" / "draft_registry.json"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_draft(drafts, draft_id):
    for draft in drafts:
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def is_already_linked(content: str, target_url: str) -> bool:
    return target_url in content


def insert_anchor_once(content: str, anchor_text: str, target_url: str):
    if is_already_linked(content, target_url):
        return content, False, "target_already_linked"

    if not anchor_text.strip():
        return content, False, "empty_anchor"

    pattern = re.compile(rf"(?<!>)\b({re.escape(anchor_text)})\b(?![^<]*</a>)", re.IGNORECASE)

    def replacer(match):
        return f'<a href="{target_url}">{match.group(1)}</a>'

    updated_content, count = pattern.subn(replacer, content, count=1)

    if count > 0:
        return updated_content, True, "inserted"

    return content, False, "anchor_not_found"


def main():
    print("=== Sofia: Apply AI Internal Links ===\n")

    if len(sys.argv) != 2:
        print("Usage:")
        print("python app/apply_ai_internal_links.py DRAFT-0005")
        return

    draft_id = sys.argv[1]

    draft_data = load_json(DRAFT_REGISTRY_FILE)
    drafts = draft_data.get("drafts", [])

    draft = find_draft(drafts, draft_id)

    if not draft:
        print(f"Draft not found: {draft_id}")
        return

    if draft.get("draft_status") not in ["content_generated", "internal_links_added"]:
        print(f"Draft is not ready for AI link application. Current status: {draft.get('draft_status')}")
        return

    content_block = draft.get("generated_content", {})
    content = content_block.get("content", "")

    if not content:
        print("Draft has no generated content.")
        return

    ai_links = draft.get("ai_internal_link_suggestions", {}).get("links", [])

    if not ai_links:
        print("No AI internal link suggestions found.")
        return

    applied = []
    skipped = []

    for link in ai_links:
        target_url = link.get("target_url", "")
        anchor_text = link.get("anchor_text", "")

        content, inserted, reason = insert_anchor_once(content, anchor_text, target_url)

        result = {
            "target_url": target_url,
            "anchor_text": anchor_text,
            "reason": reason
        }

        if inserted:
            applied.append(result)
        else:
            skipped.append(result)

    draft["generated_content"]["content"] = content
    draft["ai_internal_links_applied"] = {
        "applied_count": len(applied),
        "skipped_count": len(skipped),
        "applied": applied,
        "skipped": skipped
    }

    if applied:
        draft["draft_status"] = "ai_internal_links_added"

    save_json(DRAFT_REGISTRY_FILE, draft_data)

    print(f"AI internal links applied for {draft_id}")
    print(f"Applied: {len(applied)}")
    print(f"Skipped: {len(skipped)}")


if __name__ == "__main__":
    main()