#!/usr/bin/env python3
"""
Upload Sofia prepared featured image to WordPress and set it as featured_media.

Input:
python -m app.image_assets.upload_featured_image_to_wordpress WORKSPACE_ID DRAFT_ID
"""

from __future__ import annotations

import json
import os
import sys
import mimetypes
from pathlib import Path
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
WORKSPACES_PATH = ROOT / "data" / "workspaces.json"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_workspace(workspaces, workspace_id):
    for workspace in workspaces.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


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


def get_wordpress_auth(workspace):
    wp_config = workspace.get("wordpress", {}) or {}

    if not wp_config.get("enabled"):
        raise RuntimeError("WordPress is not enabled for this workspace.")

    username = os.getenv(wp_config.get("username_env", ""))
    password = os.getenv(wp_config.get("password_env", ""))

    if not username or not password:
        raise RuntimeError("Missing WordPress credentials in .env.")

    return wp_config, username, password




def normalize_image_match_text(value):
    return (
        str(value or "")
        .lower()
        .replace("_", "-")
        .replace(".webp", "")
        .replace(".png", "")
        .replace(".jpg", "")
        .replace(".jpeg", "")
        .replace("-1600", "")
        .replace("-1200", "")
        .replace("-800", "")
        .strip()
    )


def featured_variant_matches_plan(variant: dict, draft: dict) -> bool:
    image_plan = draft.get("image_plan") or {}
    featured = image_plan.get("featured_image") or {}

    expected = normalize_image_match_text(
        featured.get("recommended_filename")
        or featured.get("topic")
        or featured.get("title")
        or featured.get("alt_text")
        or ""
    )

    actual = normalize_image_match_text(
        variant.get("filename")
        or variant.get("file")
        or ""
    )

    if not expected:
        return True

    return expected in actual or actual in expected


def skip_mismatched_featured_image(registry_path, registry, draft, variant):
    image_plan = draft.get("image_plan") or {}
    featured = image_plan.get("featured_image") or {}

    warning = {
        "uploaded": False,
        "uploaded_at": None,
        "media_id": None,
        "source_file": variant.get("file", "") if isinstance(variant, dict) else "",
        "filename": Path(str(variant.get("file", ""))).name if isinstance(variant, dict) else "",
        "wordpress_url": "",
        "alt_text": featured.get("alt_text", ""),
        "caption": "",
        "description": featured.get("description", ""),
        "featured_image_set": False,
        "warning": "stale_featured_image_mismatch_skipped",
        "expected_filename": featured.get("recommended_filename", ""),
        "actual_file": variant.get("file", "") if isinstance(variant, dict) else "",
        "wordpress_post_id": draft.get("wordpress_id"),
        "wordpress_post_type": draft.get("wordpress_post_type") or "pages",
    }

    draft["featured_image"] = warning
    draft.setdefault("image_warnings", []).append({
        "type": "stale_featured_image_mismatch_skipped",
        "message": "Featured image upload skipped because the prepared image did not match the current image plan.",
        "expected_filename": warning["expected_filename"],
        "actual_file": warning["actual_file"],
    })
    draft["updated_at"] = now_iso()

    save_json(registry_path, registry)

    print("Warning: featured image mismatch. Upload skipped; draft workflow can continue.")
    print(json.dumps(warning, ensure_ascii=False, indent=2))
    return



def select_featured_variant(draft):
    prep = draft.get("image_asset_preparation") or {}

    # New structure:
    # draft["image_asset_preparation"]["featured_image"]["optimized"]["variants"]
    featured = prep.get("featured_image") or {}
    optimized = featured.get("optimized") or {}

    # Backward compatibility with old structure:
    # draft["image_asset_preparation"]["optimized"]["variants"]
    if not optimized:
        optimized = prep.get("optimized") or {}

    variants = optimized.get("variants") or []

    # Prefer desktop 1600 variant for WP featured image.
    for variant in variants:
        if variant.get("label") == "desktop":
            return variant

    if variants:
        return variants[0]

    return None


def get_image_metadata(draft):
    image_plan = draft.get("image_plan") or {}
    featured = image_plan.get("featured_image") or {}

    prepared_assets = draft.get("prepared_image_assets") or {}
    prepared_featured = prepared_assets.get("featured_image") or {}
    prepared_metadata = prepared_featured.get("image_metadata") or {}

    generated_assets = draft.get("generated_image_assets") or {}
    generated_featured = generated_assets.get("featured_image") or {}
    generated_metadata = generated_featured.get("image_metadata") or {}

    # Prefer the most recent prepared/generated metadata, then fall back to the original plan.
    metadata_source = {}
    for candidate in (prepared_metadata, generated_metadata, featured):
        if isinstance(candidate, dict) and any(candidate.get(k) for k in ("alt_text", "title", "description")):
            metadata_source = candidate
            break

    return {
        "alt_text": metadata_source.get("alt_text") or featured.get("alt_text", ""),
        "caption": "",
        "description": metadata_source.get("description") or featured.get("description", ""),
        "title": (
            metadata_source.get("title")
            or featured.get("title")
            or draft.get("title")
            or draft.get("focus_keyphrase")
            or metadata_source.get("alt_text")
            or featured.get("alt_text")
            or "Featured image"
        )
    }


def upload_media(workspace, username, password, image_path: Path, metadata):
    endpoint = f"{workspace['domain']}/wp-json/wp/v2/media"

    mime_type, _ = mimetypes.guess_type(str(image_path))
    mime_type = mime_type or "image/webp"

    headers = {
        "Content-Disposition": f'attachment; filename="{image_path.name}"',
        "Content-Type": mime_type,
    }

    with image_path.open("rb") as f:
        response = requests.post(
            endpoint,
            auth=(username, password),
            headers=headers,
            data=f,
            timeout=60
        )

    if response.status_code not in [200, 201]:
        raise RuntimeError(f"WordPress media upload failed: {response.status_code}\n{response.text}")

    media = response.json()
    media_id = media.get("id")

    # Update alt/caption/title after upload.
    update_payload = {
        "alt_text": metadata.get("alt_text", ""),
        "caption": "",
        "description": metadata.get("description", ""),
        "title": metadata.get("title", ""),
    }

    update_response = requests.post(
        f"{endpoint}/{media_id}",
        auth=(username, password),
        json=update_payload,
        timeout=30
    )

    if update_response.status_code not in [200, 201]:
        raise RuntimeError(
            f"WordPress media metadata update failed: {update_response.status_code}\n"
            f"{update_response.text}"
        )

    return update_response.json()


def set_featured_media(workspace, username, password, draft, media_id):
    wordpress_id = draft.get("wordpress_id")
    post_type = (
        draft.get("wordpress_post_type")
        or (draft.get("wordpress_upload") or {}).get("post_type")
        or "pages"
    )

    if not wordpress_id:
        raise RuntimeError("Draft has no wordpress_id. Create WordPress draft first.")

    endpoint = f"{workspace['domain']}/wp-json/wp/v2/{post_type}/{wordpress_id}"

    response = requests.post(
        endpoint,
        auth=(username, password),
        json={"featured_media": media_id},
        timeout=30
    )

    if response.status_code not in [200, 201]:
        raise RuntimeError(f"Setting featured media failed: {response.status_code}\n{response.text}")

    return response.json()


def main():
    if len(sys.argv) != 3:
        print("Usage:")
        print("python -m app.image_assets.upload_featured_image_to_wordpress WORKSPACE_ID DRAFT_ID")
        sys.exit(1)

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, workspace_id)

    if not workspace:
        raise SystemExit(f"Workspace not found: {workspace_id}")

    registry_path = ROOT / workspace["draft_registry_path"]
    registry = load_json(registry_path)
    draft = find_draft(registry, draft_id)

    if not draft:
        raise SystemExit(f"Draft not found: {draft_id}")

    wp_config, username, password = get_wordpress_auth(workspace)

    existing_featured = draft.get("featured_image") or {}
    existing_media_id = existing_featured.get("media_id")

    if existing_featured.get("uploaded") and existing_media_id:
        existing_variant = {
            "file": existing_featured.get("source_file") or existing_featured.get("filename") or "",
            "filename": existing_featured.get("filename") or "",
        }

        if featured_variant_matches_plan(existing_variant, draft):
            print("Featured image already uploaded. Skipping duplicate upload.")
            print(json.dumps(existing_featured, ensure_ascii=False, indent=2))
            return

        skip_mismatched_featured_image(
            registry_path=registry_path,
            registry=registry,
            draft=draft,
            variant=existing_variant,
        )
        return

    variant = select_featured_variant(draft)

    if not variant:
        featured_record = {
            "uploaded": False,
            "uploaded_at": None,
            "media_id": None,
            "source_file": "",
            "filename": "",
            "wordpress_url": "",
            "alt_text": "",
            "caption": "",
            "description": image_metadata.get("description", ""),
            "featured_image_set": False,
            "warning": "No optimized featured image variants found. Featured image upload skipped.",
            "wordpress_post_id": draft.get("wordpress_id"),
            "wordpress_post_type": draft.get("wordpress_post_type") or "pages",
        }

        draft["featured_image"] = featured_record
        draft["updated_at"] = now_iso()
        save_json(registry_path, registry)

        print("Warning: no optimized featured image variants found. Skipping featured image upload.")
        print(json.dumps(featured_record, ensure_ascii=False, indent=2))
        return

    if not featured_variant_matches_plan(variant, draft):
        skip_mismatched_featured_image(
            registry_path=registry_path,
            registry=registry,
            draft=draft,
            variant=variant,
        )
        return

    image_path = Path(variant.get("file", ""))

    if not image_path.is_absolute():
        image_path = ROOT / image_path

    if not image_path.exists():
        raise SystemExit(f"Featured image file not found: {image_path}")

    metadata = get_image_metadata(draft)

    media = upload_media(
        workspace=workspace,
        username=username,
        password=password,
        image_path=image_path,
        metadata=metadata
    )

    media_id = media.get("id")
    post_result = set_featured_media(
        workspace=workspace,
        username=username,
        password=password,
        draft=draft,
        media_id=media_id
    )

    featured_record = {
        "uploaded": True,
        "uploaded_at": now_iso(),
        "media_id": media_id,
        "source_file": str(image_path),
        "filename": image_path.name,
        "wordpress_url": media.get("source_url", ""),
        "alt_text": metadata.get("alt_text", ""),
        "caption": "",
        "description": metadata.get("description", ""),
        "featured_image_set": True,
        "wordpress_post_id": draft.get("wordpress_id"),
        "wordpress_post_type": draft.get("wordpress_post_type") or "pages",
    }

    draft["featured_image"] = featured_record
    draft["image_plan"]["featured_image"]["wordpress_media_id"] = media_id
    draft["image_plan"]["featured_image"]["wordpress_url"] = media.get("source_url", "")
    draft["image_plan"]["featured_image"]["featured_image_set"] = True
    draft["updated_at"] = now_iso()

    save_json(registry_path, registry)

    print("Featured image uploaded and set successfully.")
    print(json.dumps(featured_record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
