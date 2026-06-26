#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

from app.image_assets.image_asset_registry import load_image_metadata, save_image_metadata
from app.image_assets.upload_featured_image_to_wordpress import (
    load_json,
    find_workspace,
    get_wordpress_auth,
    upload_media,
)

ROOT = Path(__file__).resolve().parents[2]
WORKSPACES_PATH = ROOT / "data" / "workspaces.json"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def main():

    if len(sys.argv) != 3:
        print(
            "Usage:\n"
            "python -m app.image_assets.upload_registered_image_to_wordpress "
            "WORKSPACE_ID IMAGE_ID"
        )
        sys.exit(1)

    workspace_id = sys.argv[1]
    image_id = sys.argv[2]

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, workspace_id)

    if not workspace:
        raise SystemExit(f"Workspace not found: {workspace_id}")

    _, username, password = get_wordpress_auth(workspace)

    registry = load_image_metadata(workspace_id)

    image = registry["images"].get(image_id)

    if not image:
        raise SystemExit(f"Image not found: {image_id}")

    if image.get("wordpress_media_id"):
        print("Image already uploaded.")
        print(json.dumps(image, ensure_ascii=False, indent=2))
        return

    image_path = ROOT / image["desktop_webp"]

    if not image_path.exists():
        raise SystemExit(f"Missing image file: {image_path}")

    metadata = {
        "alt_text": image.get("alt_text", ""),
        "caption": image.get("description", ""),
        "title": image.get("title", image_id),
    }

    media = upload_media(
        workspace=workspace,
        username=username,
        password=password,
        image_path=image_path,
        metadata=metadata,
    )

    image["wordpress_media_id"] = media.get("id")
    image["wordpress_url"] = media.get("source_url")
    image["wordpress_uploaded_at"] = now_iso()
    image["status"] = "uploaded"

    registry["last_updated"] = now_iso()

    save_image_metadata(workspace_id, registry)

    print(json.dumps({
        "image_id": image_id,
        "wordpress_media_id": image["wordpress_media_id"],
        "wordpress_url": image["wordpress_url"],
        "status": image["status"]
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
