#!/usr/bin/env python3
"""
Workspace-aware image asset metadata registry for Sofia.

Stores AI-generated and existing/prepared image assets after optimization.
Uses title, alt_text, and description.
Caption is intentionally not used by default.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


try:
    from app.workspace_paths import get_workspace_folder_path
except ModuleNotFoundError:
    import sys
    ROOT_DIR = Path(__file__).resolve().parents[2]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
    from app.workspace_paths import get_workspace_folder_path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_image_metadata_path(workspace_id: str) -> Path:
    return get_workspace_folder_path(workspace_id) / "image_metadata.json"


def empty_metadata(workspace_id: str) -> dict[str, Any]:
    return {
        "version": "1.0",
        "workspace_id": workspace_id,
        "last_updated": None,
        "images": {},
    }


def load_image_metadata(workspace_id: str) -> dict[str, Any]:
    path = get_image_metadata_path(workspace_id)

    if not path.exists():
        return empty_metadata(workspace_id)

    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("version", "1.0")
    data.setdefault("workspace_id", workspace_id)
    data.setdefault("last_updated", None)
    data.setdefault("images", {})

    if not isinstance(data["images"], dict):
        data["images"] = {}

    return data


def save_image_metadata(workspace_id: str, data: dict[str, Any]) -> None:
    path = get_image_metadata_path(workspace_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    data["workspace_id"] = workspace_id
    data.setdefault("version", "1.0")
    data.setdefault("images", {})
    data["last_updated"] = now_iso()

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def ensure_image_metadata_exists(workspace_id: str) -> Path:
    path = get_image_metadata_path(workspace_id)

    if not path.exists():
        save_image_metadata(workspace_id, empty_metadata(workspace_id))

    return path


def make_image_id(data: dict[str, Any]) -> str:
    images = data.get("images", {})
    numbers = []

    for image_id in images:
        if image_id.startswith("IMG-"):
            try:
                numbers.append(int(image_id.split("-")[1]))
            except Exception:
                pass

    next_number = max(numbers, default=0) + 1
    return f"IMG-{next_number:06d}"


def find_existing_image_for_slot(
    workspace_id: str,
    draft_id: str,
    slot_id: str,
) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    data = load_image_metadata(workspace_id)

    for image_id, image in data.get("images", {}).items():
        if image.get("draft_id") == draft_id and image.get("slot_id") == slot_id:
            return image_id, image

    return None, None


def register_image_asset(
    *,
    workspace_id: str,
    draft_id: str,
    slot_id: str,
    title: str = "",
    alt_text: str = "",
    description: str = "",
    filename: str = "",
    master_png: str = "",
    desktop_webp: str = "",
    tablet_webp: str = "",
    mobile_webp: str = "",
    thumb_webp: str = "",
    social_webp: str = "",
    provider: str = "",
    model: str = "",
    seed: int | str | None = None,
    generation_prompt: str = "",
    status: str = "optimized",
    source_type: str = "ai_generated",
    image_job_id: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:

    data = load_image_metadata(workspace_id)

    existing_id, existing = find_existing_image_for_slot(
        workspace_id=workspace_id,
        draft_id=draft_id,
        slot_id=slot_id,
    )

    image_id = existing_id or make_image_id(data)

    created_at = existing.get("created_at") if existing else now_iso()

    record = {
        "image_id": image_id,
        "created_at": created_at,
        "updated_at": now_iso(),

        "workspace_id": workspace_id,
        "draft_id": draft_id,
        "slot_id": slot_id,
        "source_type": source_type,
        "image_job_id": image_job_id,

        "title": title,
        "alt_text": alt_text,
        "description": description,
        "caption": "",

        "filename": filename,

        "master_png": master_png,
        "desktop_webp": desktop_webp,
        "tablet_webp": tablet_webp,
        "mobile_webp": mobile_webp,
        "thumb_webp": thumb_webp,
        "social_webp": social_webp,

        "provider": provider,
        "model": model,
        "seed": seed,
        "generation_prompt": generation_prompt,

        "status": status,

        "wordpress_media_id": None,
        "wordpress_url": None,
        "wordpress_uploaded_at": None,

        "metadata_policy": {
            "caption": "Intentionally empty by default. Use description for WordPress media description.",
            "description": "Stored in WordPress media description, not displayed below image.",
        },
    }

    if extra:
        record["extra"] = extra

    data["images"][image_id] = record
    save_image_metadata(workspace_id, data)

    return record


def get_image_by_id(workspace_id: str, image_id: str) -> dict[str, Any] | None:
    data = load_image_metadata(workspace_id)
    return data.get("images", {}).get(image_id)


def get_images_by_draft(workspace_id: str, draft_id: str) -> list[dict[str, Any]]:
    data = load_image_metadata(workspace_id)
    return [
        image
        for image in data.get("images", {}).values()
        if image.get("draft_id") == draft_id
    ]


def get_image_by_slot(
    workspace_id: str,
    draft_id: str,
    slot_id: str,
) -> dict[str, Any] | None:
    _, image = find_existing_image_for_slot(workspace_id, draft_id, slot_id)
    return image


def update_image_asset(
    workspace_id: str,
    image_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    data = load_image_metadata(workspace_id)

    if image_id not in data.get("images", {}):
        raise RuntimeError(f"Image not found: {image_id}")

    data["images"][image_id].update(updates)
    data["images"][image_id]["updated_at"] = now_iso()

    save_image_metadata(workspace_id, data)

    return data["images"][image_id]


if __name__ == "__main__":
    import sys
    workspace_id = sys.argv[1] if len(sys.argv) > 1 else "local.es"
    print(json.dumps(load_image_metadata(workspace_id), ensure_ascii=False, indent=2))
