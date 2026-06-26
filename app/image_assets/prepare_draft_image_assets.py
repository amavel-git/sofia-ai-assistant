#!/usr/bin/env python3
"""
Prepare all draft image assets.

Processes:
- featured_image
- in_article_images[]

Existing assets are optimized.
AI generation candidates are upgraded automatically to ai_generated
when an optimized generated image already exists in image_metadata.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.workspace_paths import get_workspace_draft_registry_path
from app.image_assets.image_asset_registry import get_image_by_slot

try:
    from app.image_assets.prepare_image_asset import prepare_image_asset
except ModuleNotFoundError:
    from prepare_image_asset import prepare_image_asset


ROOT_DIR = Path(__file__).resolve().parents[2]
GLOBAL_ORIGINALS_DIR = ROOT_DIR / "data" / "image_assets" / "originals"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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


def resolve_source_path(image_slot):
    filename = (
        image_slot.get("source_filename")
        or image_slot.get("filename")
        or ""
    )

    if not filename:
        return None

    path = GLOBAL_ORIGINALS_DIR / filename

    if path.exists():
        return path

    return None


def prepare_existing_slot(workspace_id, image_slot):
    source_path = resolve_source_path(image_slot)

    if not source_path:
        return {
            "prepared": False,
            "source_type": image_slot.get("source_type"),
            "slot_id": image_slot.get("slot_id", "featured_image"),
            "error": "Source image not found",
            "filename": image_slot.get("filename")
            or image_slot.get("source_filename"),
        }

    recommended_filename = (
        image_slot.get("recommended_filename")
        or source_path.name
    )

    result = prepare_image_asset(
        workspace_id=workspace_id,
        source_path=str(source_path),
        recommended_filename=recommended_filename,
    )

    result["prepared"] = True
    result["slot_id"] = image_slot.get(
        "slot_id",
        "featured_image",
    )
    result["source_type"] = image_slot.get("source_type")

    result["image_metadata"] = {
        "alt_text": image_slot.get("alt_text", ""),
        "title": image_slot.get("title", ""),
        "caption": image_slot.get("caption", ""),
        "placement": image_slot.get("placement", ""),
        "category": image_slot.get("category", ""),
        "asset_id": image_slot.get("asset_id", ""),
    }

    return result




def normalize_match_text(value):
    return (
        str(value or "")
        .lower()
        .replace("_", "-")
        .replace(".webp", "")
        .replace(".png", "")
        .replace(".jpg", "")
        .replace(".jpeg", "")
        .strip()
    )


def generated_image_matches_slot(generated: dict, image_slot: dict) -> bool:
    """
    Prevent stale generated images from old reset runs being reused only because
    draft_id and slot_id match. The generated image must also match the current
    slot's expected filename/topic.
    """
    if not generated:
        return False

    expected_filename = normalize_match_text(
        image_slot.get("recommended_filename")
        or image_slot.get("filename")
        or image_slot.get("source_filename")
        or ""
    )

    expected_topic = normalize_match_text(
        image_slot.get("topic")
        or image_slot.get("title")
        or image_slot.get("alt_text")
        or ""
    )

    actual_parts = [
        generated.get("filename"),
        generated.get("desktop_webp"),
        generated.get("tablet_webp"),
        generated.get("mobile_webp"),
        generated.get("master_png"),
        generated.get("title"),
        generated.get("alt_text"),
        generated.get("description"),
        generated.get("generation_prompt"),
    ]

    actual_text = normalize_match_text(" ".join(str(x or "") for x in actual_parts))

    # Filename match is strongest. Remove size suffixes from actual generated files.
    actual_text_compact = actual_text.replace("-1600", "").replace("-1200", "").replace("-800", "")

    if expected_filename and expected_filename in actual_text_compact:
        return True

    # Topic match is secondary for older records that may not have exact filename.
    if expected_topic:
        important_terms = [
            t for t in expected_topic.split("-")
            if len(t) >= 5 and t not in {"sobre", "para", "professional", "investigation"}
        ]
        if important_terms:
            hits = sum(1 for term in important_terms if term in actual_text)
            return hits >= min(3, len(important_terms))

    return False



def prepare_slot(workspace_id, draft_id, image_slot):
    source_type = image_slot.get("source_type")
    slot_id = image_slot.get(
        "slot_id",
        "featured_image",
    )

    #
    # AI candidate
    #
    if source_type == "ai_generation_candidate":

        generated = get_image_by_slot(
            workspace_id,
            draft_id,
            slot_id,
        )

        #
        # Already generated and optimized
        #
        if (
            generated
            and generated.get("desktop_webp")
            and generated_image_matches_slot(generated, image_slot)
        ):

            return {
                "prepared": True,
                "slot_id": slot_id,
                "source_type": "ai_generated",

                "optimized": {
                    "variants": [
                        {
                            "label": "desktop",
                            "file": generated.get(
                                "desktop_webp"
                            ),
                        },
                        {
                            "label": "tablet",
                            "file": generated.get(
                                "tablet_webp"
                            ),
                        },
                        {
                            "label": "mobile",
                            "file": generated.get(
                                "mobile_webp"
                            ),
                        },
                    ]
                },

                "image_metadata": {
                    "alt_text": generated.get(
                        "alt_text",
                        "",
                    ),
                    "title": generated.get(
                        "title",
                        "",
                    ),
                    "caption": "",
                    "description": generated.get(
                        "description",
                        "",
                    ),
                    "placement": image_slot.get(
                        "placement",
                        "after_h2_2",
                    ),
                    "category": image_slot.get(
                        "category",
                        "",
                    ),
                },

                "generated_image_id": generated.get(
                    "image_id"
                ),
            }

        #
        # Still waiting generation
        #
        return {
            "prepared": False,
            "slot_id": slot_id,
            "source_type": source_type,
            "status": "generation_needed",
            "prompt": image_slot.get(
                "prompt",
                "",
            ),
            "recommended_filename": image_slot.get(
                "recommended_filename",
                "",
            ),
            "requires_examiner_approval": image_slot.get(
                "requires_examiner_approval",
                True,
            ),
        }

    #
    # Existing image
    #
    return prepare_existing_slot(
        workspace_id,
        image_slot,
    )


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: python -m app.image_assets.prepare_draft_image_assets WORKSPACE_ID DRAFT_ID"
        )
        sys.exit(1)

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]

    registry_path = get_workspace_draft_registry_path(
        workspace_id
    )
    registry = load_json(registry_path)

    draft = find_draft(
        registry,
        draft_id,
    )

    if not draft:
        raise SystemExit(
            f"Draft not found: {draft_id}"
        )

    image_plan = draft.get("image_plan") or {}

    featured = image_plan.get(
        "featured_image"
    ) or {}

    in_article_images = image_plan.get(
        "in_article_images"
    ) or []

    preparation = {
        "workspace_id": workspace_id,
        "draft_id": draft_id,
        "featured_image": None,
        "in_article_images": [],
        "generation_candidates": [],
    }

    if featured:
        preparation["featured_image"] = prepare_slot(
            workspace_id,
            draft_id,
            featured,
        )

        if (
            preparation["featured_image"]
            and preparation["featured_image"].get("source_type") == "ai_generation_candidate"
        ):
            preparation["generation_candidates"].append(
                preparation["featured_image"]
            )

    for slot in in_article_images:

        result = prepare_slot(
            workspace_id,
            draft_id,
            slot,
        )

        preparation["in_article_images"].append(
            result
        )

        if result.get("source_type") == "ai_generation_candidate":
            preparation["generation_candidates"].append(
                result
            )

    draft["image_asset_preparation"] = preparation

    save_json(
        registry_path,
        registry,
    )

    print(
        json.dumps(
            preparation,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
