#!/usr/bin/env python3
"""
Upload prepared in-article images to WordPress media library.

This does not insert images into content yet.
It only uploads media and stores media_id / URL in draft_registry.
"""

from __future__ import annotations

import json
import mimetypes
import sys
from pathlib import Path

import requests

try:
    from app.workspace_paths import get_workspace_draft_registry_path
    from app.image_assets.upload_featured_image_to_wordpress import (
        WORKSPACES_PATH,
        load_json,
        find_workspace,
        get_wordpress_auth,
        upload_media,
    )
except ModuleNotFoundError:
    from workspace_paths import get_workspace_draft_registry_path
    from upload_featured_image_to_wordpress import (
        WORKSPACES_PATH,
        load_json,
        find_workspace,
        get_wordpress_auth,
        upload_media,
    )


ROOT_DIR = Path(__file__).resolve().parents[2]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_drafts(registry):
    if isinstance(registry, dict):
        return registry.get("drafts", [])
    if isinstance(registry, list):
        return registry
    return []


def find_draft(registry, draft_id):
    for draft in get_drafts(registry):
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def select_desktop_variant(prepared_slot):
    variants = prepared_slot.get("optimized", {}).get("variants", [])

    for variant in variants:
        if variant.get("label") == "desktop":
            return variant

    return variants[0] if variants else None


def resolve_file_path(file_value):
    path = Path(file_value)

    if path.is_absolute():
        return path

    return ROOT_DIR / path


def upload_slot(workspace, auth, slot):
    if slot.get("uploaded") and slot.get("media_id"):
        return slot

    variant = select_desktop_variant(slot)

    if not variant:
        slot["upload_error"] = "No optimized desktop variant found."
        return slot

    file_path = resolve_file_path(variant.get("file", ""))

    if not file_path.exists():
        slot["upload_error"] = f"Optimized file not found: {file_path}"
        return slot

    metadata = slot.get("image_metadata", {}) or {}

    upload_result = upload_media(
        workspace=workspace,
        username=auth["username"],
        password=auth["password"],
        image_path=file_path,
        metadata={
            "title": metadata.get("title") or variant.get("filename") or "In-article image",
            "alt_text": metadata.get("alt_text", ""),
            "caption": metadata.get("caption", ""),
            "description": metadata.get("description", ""),
        }
    )

    slot["uploaded"] = True
    slot["media_id"] = upload_result.get("id") or upload_result.get("media_id")
    slot["wordpress_url"] = upload_result.get("source_url") or upload_result.get("wordpress_url")
    slot["uploaded_filename"] = variant.get("filename")
    slot["wordpress_media"] = upload_result

    return slot


def main():
    if len(sys.argv) != 3:
        print("Usage:")
        print("python -m app.image_assets.upload_in_article_images_to_wordpress WORKSPACE_ID DRAFT_ID")
        sys.exit(1)

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, workspace_id)
    wp_config, username, password = get_wordpress_auth(workspace)

    auth = {
        "username": username,
        "password": password,
    }

    registry_path = get_workspace_draft_registry_path(workspace_id)
    registry = load_json(registry_path)
    draft = find_draft(registry, draft_id)

    if not draft:
        raise SystemExit(f"Draft not found: {draft_id}")

    preparation = draft.get("image_asset_preparation") or {}
    in_article_images = preparation.get("in_article_images") or []

    uploaded = []
    warnings = []

    for slot in in_article_images:
        if slot.get("source_type") == "ai_generation_candidate":
            warnings.append({
                "slot_id": slot.get("slot_id"),
                "warning": "AI generation candidate not uploaded yet."
            })
            uploaded.append(slot)
            continue

        try:
            updated_slot = upload_slot(workspace, auth, slot)
        except Exception as exc:
            updated_slot = dict(slot)
            updated_slot["upload_error"] = str(exc)

        if updated_slot.get("upload_error"):
            warnings.append({
                "slot_id": updated_slot.get("slot_id"),
                "warning": updated_slot.get("upload_error")
            })

        uploaded.append(updated_slot)

    preparation["in_article_images"] = uploaded
    preparation["in_article_upload_warnings"] = warnings
    draft["image_asset_preparation"] = preparation

    save_json(registry_path, registry)

    result = {
        "workspace_id": workspace_id,
        "draft_id": draft_id,
        "uploaded_count": len([x for x in uploaded if x.get("uploaded")]),
        "warnings": warnings,
        "in_article_images": uploaded,
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
