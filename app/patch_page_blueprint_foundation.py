#!/usr/bin/env python3
"""
Patch Sofia Page Blueprint Intelligence foundation files.

Updates:
- data/page_blueprints.json
- sites/local_sites/es/page_presentation.json

Adds validation/image/rendering enforcement fields without changing the
existing architecture.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[1]

BLUEPRINTS_PATH = ROOT / "data" / "page_blueprints.json"
PRESENTATION_PATH = ROOT / "sites" / "local_sites" / "es" / "page_presentation.json"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def backup(path: Path) -> Path:
    backup_path = path.with_suffix(path.suffix + f".bak-{utc_stamp()}")
    shutil.copy2(path, backup_path)
    return backup_path


def patch_blueprints(data: Dict[str, Any]) -> bool:
    changed = False

    page_blueprints = data.setdefault("page_blueprints", {})

    defaults_by_type = {
        "landing_page": {
            "minimum_word_count": 850,
            "minimum_faq_items": 4,
            "required_internal_link_count": 2,
            "requires_cta": True,
            "requires_trust_block": True,
            "requires_featured_image": True,
            "requires_hero_image": True,
        },
        "blog_post": {
            "minimum_word_count": 750,
            "minimum_faq_items": 4,
            "required_internal_link_count": 2,
            "requires_cta": True,
            "requires_trust_block": False,
            "requires_featured_image": True,
            "requires_hero_image": False,
        },
        "city_page": {
            "minimum_word_count": 800,
            "minimum_faq_items": 4,
            "required_internal_link_count": 3,
            "requires_cta": True,
            "requires_trust_block": True,
            "requires_featured_image": True,
            "requires_hero_image": True,
            "required_local_section": True,
        },
        "faq_page": {
            "minimum_word_count": 650,
            "minimum_faq_items": 8,
            "required_internal_link_count": 2,
            "requires_cta": True,
            "requires_trust_block": False,
            "requires_featured_image": False,
            "requires_hero_image": False,
        },
        "pricing_page": {
            "minimum_word_count": 750,
            "minimum_faq_items": 4,
            "required_internal_link_count": 2,
            "requires_cta": True,
            "requires_trust_block": True,
            "requires_featured_image": False,
            "requires_hero_image": False,
            "requires_pricing_section": True,
        },
        "pillar_page": {
            "minimum_word_count": 1200,
            "minimum_faq_items": 5,
            "required_internal_link_count": 5,
            "requires_cta": True,
            "requires_trust_block": True,
            "requires_featured_image": True,
            "requires_hero_image": True,
        },
        "educational_page": {
            "minimum_word_count": 900,
            "minimum_faq_items": 4,
            "required_internal_link_count": 3,
            "requires_cta": True,
            "requires_trust_block": False,
            "requires_featured_image": True,
            "requires_hero_image": True,
            "requires_educational_sections": True,
        },
        "authority_page": {
            "minimum_word_count": 900,
            "minimum_faq_items": 4,
            "required_internal_link_count": 3,
            "requires_cta": False,
            "requires_trust_block": True,
            "requires_featured_image": True,
            "requires_hero_image": False,
            "requires_authority_context": True,
        },
    }

    for blueprint_id, blueprint in page_blueprints.items():
        sections = blueprint.get("sections", [])
        required_section_ids = [
            section.get("id")
            for section in sections
            if section.get("required") is True and section.get("id")
        ]

        default_validation = defaults_by_type.get(
            blueprint_id,
            {
                "minimum_word_count": 750,
                "minimum_faq_items": 4,
                "required_internal_link_count": 2,
                "requires_cta": True,
                "requires_trust_block": False,
                "requires_featured_image": False,
                "requires_hero_image": False,
            },
        )

        validation_requirements = blueprint.setdefault("validation_requirements", {})

        additions = {
            **default_validation,
            "required_section_ids": required_section_ids,
            "fail_if_missing_required_sections": True,
            "fail_if_below_minimum_word_count": True,
            "fail_if_missing_required_faq": True,
            "fail_if_missing_required_cta": default_validation.get("requires_cta", False),
            "warn_if_missing_images": True,
            "warn_if_internal_links_below_recommended": True,
        }

        for key, value in additions.items():
            if key not in validation_requirements:
                validation_requirements[key] = value
                changed = True

        image_requirements = blueprint.setdefault("image_requirements", {})
        image_additions = {
            "featured_image_required": default_validation.get("requires_featured_image", False),
            "hero_image_required": default_validation.get("requires_hero_image", False),
            "inline_image_slots": [],
            "allow_future_ai_generation": True,
            "allow_wordpress_media_match": True,
        }

        for key, value in image_additions.items():
            if key not in image_requirements:
                image_requirements[key] = value
                changed = True

        for section in sections:
            if "heading_required" not in section:
                section["heading_required"] = True
                changed = True

            if "validation_weight" not in section:
                section["validation_weight"] = "blocking" if section.get("required") else "recommended"
                changed = True

            if "min_words" not in section:
                section_type = section.get("type")
                if section_type in {"faq", "cta", "strategic_links", "related_services"}:
                    section["min_words"] = 0
                elif section_type in {"hero", "introduction"}:
                    section["min_words"] = 80
                else:
                    section["min_words"] = 100
                changed = True

    return changed


def patch_presentation(data: Dict[str, Any]) -> bool:
    changed = False

    image_strategy = data.setdefault("image_strategy", {})
    image_additions = {
        "enabled": True,
        "featured_image_required_by_default": True,
        "hero_image_required_by_default": True,
        "inline_images_enabled": True,
        "preferred_style": "realistic professional consultation",
        "preferred_subjects": [
            "professional consultation",
            "pre-test interview",
            "examiner speaking calmly with client",
            "modern Spanish office",
            "confidential professional meeting",
        ],
        "avoid": [
            "interrogation imagery",
            "police custody",
            "fear-based visuals",
            "aggressive suspect imagery",
            "unrealistic polygraph equipment",
            "medical diagnosis imagery",
        ],
        "future_generator": "flux",
        "wordpress_insertion": {
            "featured_image": True,
            "hero_inline": True,
            "inline_images": True,
        },
    }

    for key, value in image_additions.items():
        if key not in image_strategy:
            image_strategy[key] = value
            changed = True

    rendering = data.setdefault("rendering", {})
    rendering_additions = {
        "faq_format": data.get("faq", {}).get("preferred_format", "standard_html"),
        "future_preferred_faq_format": "yoast_faq_block",
        "cta_rendering": "inline_html_now_reusable_block_later",
        "trust_rendering": "inline_html_now_reusable_block_later",
        "related_links_rendering": "inline_html_now_reusable_block_later",
        "image_rendering": "wordpress_media_or_generated_asset_later",
        "gutenberg_blocks_enabled": False,
    }

    for key, value in rendering_additions.items():
        if key not in rendering:
            rendering[key] = value
            changed = True

    validation_preferences = data.setdefault("validation_preferences", {})
    validation_additions = {
        "respect_blueprint_validation_requirements": True,
        "fail_on_missing_required_sections": True,
        "fail_on_missing_cta_when_required": True,
        "fail_on_missing_faq_when_required": True,
        "warn_on_missing_image_assets": True,
        "warn_on_missing_reusable_blocks": True,
    }

    for key, value in validation_additions.items():
        if key not in validation_preferences:
            validation_preferences[key] = value
            changed = True

    return changed


def main() -> None:
    blueprints = load_json(BLUEPRINTS_PATH)
    presentation = load_json(PRESENTATION_PATH)

    blueprints_changed = patch_blueprints(blueprints)
    presentation_changed = patch_presentation(presentation)

    if blueprints_changed:
        backup_path = backup(BLUEPRINTS_PATH)
        save_json(BLUEPRINTS_PATH, blueprints)
        print(f"Patched {BLUEPRINTS_PATH}")
        print(f"Backup: {backup_path}")
    else:
        print(f"No changes needed: {BLUEPRINTS_PATH}")

    if presentation_changed:
        backup_path = backup(PRESENTATION_PATH)
        save_json(PRESENTATION_PATH, presentation)
        print(f"Patched {PRESENTATION_PATH}")
        print(f"Backup: {backup_path}")
    else:
        print(f"No changes needed: {PRESENTATION_PATH}")


if __name__ == "__main__":
    main()