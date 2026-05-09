import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

from workspace_paths import (
    get_workspace_draft_registry_path,
    empty_draft_registry,
)


SOFIA_ROOT = Path(__file__).resolve().parents[1]

WORKSPACES_PATH = SOFIA_ROOT / "data" / "workspaces.json"
# Deprecated: draft registries are now workspace-level.
GLOBAL_DRAFT_REGISTRY_PATH = SOFIA_ROOT / "sites" / "draft_registry.json"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path, default=None):
    if not path.exists():
        return default if default is not None else {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_workspace(workspace_id):
    data = load_json(WORKSPACES_PATH, {"workspaces": []})
    for workspace in data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def find_draft(workspace_id, draft_id):
    registry_path = get_workspace_draft_registry_path(workspace_id)
    data = load_json(registry_path, empty_draft_registry(workspace_id))

    for draft in data.get("drafts", []):
        if draft.get("draft_id") == draft_id:
            return draft

    return None


def normalize_language(language):
    language = str(language or "en").strip()

    if language.startswith("pt"):
        return "pt-PT"
    if language.startswith("es"):
        return "es"
    if language.startswith("fr"):
        return "fr"
    if language.startswith("en"):
        return "en"

    return language or "en"


def slug_to_topic(slug):
    slug = str(slug or "").strip("/")
    slug = slug.split("/")[-1]
    return slug.replace("-", " ").strip()


def clean_terms(values):
    terms = []
    seen = set()

    for value in values:
        if not value:
            continue

        value = str(value).strip()
        value = re.sub(r"\s+", " ", value)

        if not value:
            continue

        key = value.lower()

        if key not in seen:
            terms.append(value)
            seen.add(key)

    return terms


def get_wordpress_info(draft):
    update = draft.get("wordpress_update", {}) or {}
    upload = draft.get("wordpress_upload", {}) or {}

    wordpress_id = (
        update.get("wordpress_id")
        or upload.get("wordpress_id")
        or draft.get("wordpress_id")
    )

    wordpress_link = (
        update.get("wordpress_link")
        or upload.get("wordpress_link")
        or draft.get("wordpress_link")
        or ""
    )

    post_type = (
        update.get("post_type")
        or upload.get("post_type")
        or draft.get("post_type")
        or ""
    )

    wordpress_status = (
        update.get("wordpress_status")
        or upload.get("wordpress_status")
        or draft.get("wordpress_status")
        or ""
    )

    return {
        "wordpress_id": wordpress_id,
        "wordpress_link": wordpress_link,
        "post_type": post_type,
        "wordpress_status": wordpress_status,
    }


def build_content_id(workspace, draft):
    market_code = (
        workspace.get("market_code")
        or workspace.get("country_code")
        or workspace.get("workspace_id", "XX").split(".")[-1]
    )
    market_code = str(market_code).upper()
    number = re.sub(r"\D+", "", draft.get("draft_id", "")) or "0000"
    return f"CONTENT-{market_code}-{int(number):04d}"


def build_inventory_entry(workspace, draft):
    wp = get_wordpress_info(draft)

    title = (
        draft.get("title")
        or draft.get("working_title")
        or draft.get("draft_title")
        or ""
    )

    focus_keyphrase = (
        draft.get("focus_keyphrase")
        or draft.get("target_keyword")
        or ""
    )

    slug = (
        draft.get("slug")
        or draft.get("suggested_slug")
        or ""
    )

    seo_title = (
        draft.get("seo_title")
        or title
    )

    meta_description = (
        draft.get("meta_description")
        or ""
    )

    target_keyword = (
        draft.get("target_keyword")
        or focus_keyphrase
        or title
    )

    related_topics = clean_terms([
        slug_to_topic(slug),
        draft.get("working_title"),
        draft.get("target_keyword"),
        draft.get("focus_keyphrase"),
    ])

    cannibalization_terms = clean_terms([
        focus_keyphrase,
        target_keyword,
        title,
        slug_to_topic(slug),
    ])

    return {
        "content_id": build_content_id(workspace, draft),
        "draft_id": draft.get("draft_id", ""),
        "intake_id": draft.get("created_from_intake_id", ""),
        "workspace_id": workspace.get("workspace_id", ""),
        "title": title,
        "seo_title": seo_title,
        "focus_keyphrase": focus_keyphrase,
        "slug": slug,
        "meta_description": meta_description,
        "wordpress_id": wp["wordpress_id"],
        "wordpress_link": wp["wordpress_link"],
        "canonical_url": "",
        "post_type": wp["post_type"],
        "wordpress_status": wp["wordpress_status"],
        "language": normalize_language(draft.get("language") or workspace.get("language")),
        "country": workspace.get("country", ""),
        "content_type": draft.get("content_type", ""),
        "status": "completed_for_manual_publication",
        "published_live": False,
        "primary_topic": target_keyword,
        "related_topics": related_topics,
        "cannibalization_terms": cannibalization_terms,
        "created_from": draft.get("source_type") or draft.get("created_from") or "sofia_content_workflow",
        "completed_at": draft.get("completed_at") or now_iso(),
        "updated_at": now_iso(),
    }


def update_content_inventory(workspace, draft):
    folder_path = workspace.get("folder_path")
    if not folder_path:
        raise RuntimeError(f"Workspace has no folder_path: {workspace.get('workspace_id')}")

    inventory_path = SOFIA_ROOT / folder_path / "content_inventory.json"

    inventory = load_json(
        inventory_path,
        {
            "version": "1.0",
            "workspace_id": workspace.get("workspace_id"),
            "domain": workspace.get("domain", ""),
            "last_updated": None,
            "content_items": []
        }
    )

    if "content_items" not in inventory:
        inventory["content_items"] = []

    entry = build_inventory_entry(workspace, draft)

    replaced = False
    for idx, item in enumerate(inventory["content_items"]):
        if item.get("draft_id") == draft.get("draft_id"):
            inventory["content_items"][idx] = {
                **item,
                **entry,
                "updated_at": now_iso()
            }
            replaced = True
            break

    if not replaced:
        inventory["content_items"].append(entry)

    inventory["workspace_id"] = workspace.get("workspace_id")
    inventory["domain"] = workspace.get("domain", "")
    inventory["last_updated"] = now_iso()

    save_json(inventory_path, inventory)

    return inventory_path, entry, replaced


def update_site_content_memory(workspace, draft, inventory_entry):
    folder_path = workspace.get("folder_path")
    memory_path = SOFIA_ROOT / folder_path / "site_content_memory.json"

    memory = load_json(
        memory_path,
        {
            "workspace_info": {
                "workspace_id": workspace.get("workspace_id"),
                "language": workspace.get("language"),
                "market_code": workspace.get("market_code"),
                "domain": workspace.get("domain"),
            },
            "published_content": [],
            "draft_content": [],
            "content_topics": [],
            "keyword_index": [],
            "protected_topics": [],
            "cannibalization_notes": [],
            "content_opportunities": []
        }
    )

    for key in ["published_content", "draft_content", "content_topics", "keyword_index", "protected_topics", "cannibalization_notes", "content_opportunities"]:
        if key not in memory:
            memory[key] = []

    published_item = {
        "draft_id": inventory_entry["draft_id"],
        "content_id": inventory_entry["content_id"],
        "title": inventory_entry["title"],
        "target_keyword": inventory_entry["primary_topic"],
        "focus_keyphrase": inventory_entry["focus_keyphrase"],
        "slug": inventory_entry["slug"],
        "url": inventory_entry["wordpress_link"],
        "status": inventory_entry["status"],
        "published_live": inventory_entry["published_live"],
        "completed_at": inventory_entry["completed_at"]
    }

    replaced = False
    for idx, item in enumerate(memory["published_content"]):
        if item.get("draft_id") == draft.get("draft_id"):
            memory["published_content"][idx] = {
                **item,
                **published_item
            }
            replaced = True
            break

    if not replaced:
        memory["published_content"].append(published_item)

    # Keep keyword index updated for cannibalization checks.
    existing_keywords = {str(k).lower() for k in memory.get("keyword_index", [])}
    for term in inventory_entry.get("cannibalization_terms", []):
        if term and term.lower() not in existing_keywords:
            memory["keyword_index"].append(term)
            existing_keywords.add(term.lower())

    # Keep topic index updated.
    existing_topics = {str(t).lower() for t in memory.get("content_topics", [])}
    for topic in inventory_entry.get("related_topics", []):
        if topic and topic.lower() not in existing_topics:
            memory["content_topics"].append(topic)
            existing_topics.add(topic.lower())

    # Remove the draft from active draft_content if present.
    memory["draft_content"] = [
        item for item in memory.get("draft_content", [])
        if item.get("draft_id") != draft.get("draft_id")
    ]

    memory["last_updated"] = now_iso()

    save_json(memory_path, memory)

    return memory_path


def main():
    print("=== Sofia: Update Content Inventory ===\n")

    if len(sys.argv) != 3:
        print("Usage:")
        print("python app/update_content_inventory.py WORKSPACE_ID DRAFT_ID")
        return

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]

    workspace = find_workspace(workspace_id)
    if not workspace:
        print(f"ERROR: Workspace not found: {workspace_id}")
        return

    draft = find_draft(workspace_id, draft_id)
    if not draft:
        print(f"ERROR: Draft not found: {draft_id}")
        return

    if draft.get("draft_status") != "completed":
        print(f"ERROR: Draft is not completed. Current status: {draft.get('draft_status')}")
        return

    inventory_path, entry, replaced = update_content_inventory(workspace, draft)
    memory_path = update_site_content_memory(workspace, draft, entry)

    print("Content inventory updated successfully.")
    print(f"Workspace: {workspace_id}")
    print(f"Draft: {draft_id}")
    print(f"Content ID: {entry.get('content_id')}")
    print(f"Inventory file: {inventory_path}")
    print(f"Site content memory file: {memory_path}")
    print(f"Action: {'updated existing item' if replaced else 'created new item'}")


if __name__ == "__main__":
    main()