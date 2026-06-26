#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

from app.image_assets.image_asset_registry import load_image_metadata
from app.image_assets.upload_featured_image_to_wordpress import (
    load_json,
    save_json,
    find_workspace,
    find_draft,
    get_wordpress_auth,
    set_featured_media,
)

ROOT = Path(__file__).resolve().parents[2]
WORKSPACES_PATH = ROOT / "data" / "workspaces.json"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def main():
    if len(sys.argv) != 4:
        print(
            "Usage:\n"
            "python -m app.image_assets.set_registered_image_as_featured "
            "WORKSPACE_ID DRAFT_ID IMAGE_ID"
        )
        sys.exit(1)

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]
    image_id = sys.argv[3]

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, workspace_id)

    if not workspace:
        raise SystemExit(f"Workspace not found: {workspace_id}")

    registry_path = ROOT / workspace["draft_registry_path"]
    draft_registry = load_json(registry_path)
    draft = find_draft(draft_registry, draft_id)

    if not draft:
        raise SystemExit(f"Draft not found: {draft_id}")

    image_registry = load_image_metadata(workspace_id)
    image = image_registry.get("images", {}).get(image_id)

    if not image:
        raise SystemExit(f"Image not found: {image_id}")

    media_id = image.get("wordpress_media_id")
    wordpress_url = image.get("wordpress_url", "")

    if not media_id:
        raise SystemExit(f"Image is not uploaded to WordPress yet: {image_id}")

    _, username, password = get_wordpress_auth(workspace)

    set_featured_media(
        workspace=workspace,
        username=username,
        password=password,
        draft=draft,
        media_id=media_id,
    )

    featured_record = {
        "uploaded": True,
        "uploaded_at": image.get("wordpress_uploaded_at") or now_iso(),
        "media_id": media_id,
        "source_file": image.get("desktop_webp", ""),
        "filename": image.get("filename", ""),
        "wordpress_url": wordpress_url,
        "alt_text": image.get("alt_text", ""),
        "description": image.get("description", ""),
        "caption": "",
        "featured_image_set": True,
        "source_type": image.get("source_type", "ai_generated"),
        "image_id": image_id,
        "wordpress_post_id": draft.get("wordpress_id"),
        "wordpress_post_type": draft.get("wordpress_post_type") or "pages",
    }

    draft["featured_image"] = featured_record
    draft.setdefault("image_plan", {}).setdefault("featured_image", {})
    draft["image_plan"]["featured_image"]["wordpress_media_id"] = media_id
    draft["image_plan"]["featured_image"]["wordpress_url"] = wordpress_url
    draft["image_plan"]["featured_image"]["featured_image_set"] = True
    draft["image_plan"]["featured_image"]["image_id"] = image_id
    draft["updated_at"] = now_iso()

    save_json(registry_path, draft_registry)

    print(json.dumps(featured_record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
