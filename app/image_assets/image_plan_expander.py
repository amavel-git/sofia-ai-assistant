#!/usr/bin/env python3
"""
Expand a draft image plan with semantic in-article image slots.

Phase 4.3:
- Images are selected from section_intelligence when available.
- Each image is tied to a semantic section purpose.
- Resource policy:
  - 1 featured image handled elsewhere
  - maximum 3 article images
  - maximum 4 generated images per page total
"""

from __future__ import annotations

import json
from pathlib import Path

SOFIA_ROOT = Path(__file__).resolve().parents[2]

try:
    from image_asset_library import select_best_asset
    from image_generation_prompt_builder import build_generation_candidate
    from image_metadata_generator import build_image_metadata
except ModuleNotFoundError:
    from app.image_assets.image_asset_library import select_best_asset
    from app.image_assets.image_generation_prompt_builder import build_generation_candidate
    from app.image_assets.image_metadata_generator import build_image_metadata


IMAGE_SELECTION_THRESHOLD = 999
MAX_ARTICLE_IMAGES = 3
MAX_GENERATED_IMAGES_PER_PAGE = 4
AI_IMAGE_GENERATION_CONFIG_PATH = SOFIA_ROOT / "data" / "image_assets" / "ai_image_generation_config.json"


def load_ai_image_generation_config():
    if not AI_IMAGE_GENERATION_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(AI_IMAGE_GENERATION_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def image_text_policy(slot):
    config = load_ai_image_generation_config()
    rules = (
        (config.get("ai_generation_rules", {}) or {}).get("text_policy", {})
        if isinstance(config, dict)
        else {}
    )

    allow_text = bool(slot.get("allow_text_in_image") or slot.get("allow_visible_text"))

    if allow_text:
        return {"prompt_suffix": "", "negative_prompt": ""}

    return {
        "prompt_suffix": rules.get(
            "prompt_suffix_no_text",
            (
                " No visible text. No readable words. No typography. "
                "No signs. No labels. No logos. No watermarks. "
                "Documents may appear but must be blank or unreadable."
            ),
        ),
        "negative_prompt": ", ".join(
            rules.get(
                "negative_prompt_terms",
                [
                    "text", "letters", "words", "captions", "typography",
                    "signs", "labels", "watermark", "logo",
                    "readable documents", "printed text", "UI text",
                    "distorted text",
                ],
            )
        ),
    }


def localized_country_name(country, language):
    raw = str(country or "").strip()
    key = raw.lower()

    if language == "es" and key in {"spain", "es", "españa"}:
        return "España"
    if language.startswith("pt") and key in {"portugal", "pt"}:
        return "Portugal"
    if language == "fr" and key in {"france", "fr"}:
        return "France"

    return raw


def build_existing_asset_slot(
    *,
    asset,
    workspace_id,
    topic,
    language,
    country,
    page_type,
    placement,
    slot_id,
    filename_base,
):
    metadata = build_image_metadata(
        workspace_id=workspace_id,
        language=language,
        topic=topic,
        category=asset.get("category", "default"),
        placement=placement,
        page_type=page_type,
        fallback_country=country,
        professional_context=asset.get("visual_context", ""),
        filename_base=filename_base,
    )

    return {
        "slot_id": slot_id,
        "source_type": "existing_asset",
        "asset_id": asset.get("asset_id", ""),
        "filename": asset.get("filename", ""),
        "source_filename": asset.get("filename", ""),
        "category": asset.get("category", ""),
        "categories": asset.get("categories", []),
        "topics": asset.get("topics", []),
        "visual_context": asset.get("visual_context", ""),
        "placement": placement,
        "status": "selected",
        "score": asset.get("score", 0),
        "recommended_filename": f"{filename_base}.webp",
        "alt_text": metadata.get("alt_text", ""),
        "title": metadata.get("title", ""),
        "caption": "",
        "description": (
            f"Imagen profesional relacionada con {topic} en {localized_country_name(country, language)}, "
            f"utilizada como apoyo visual para esta página."
        ),
        "country_localized": metadata.get("country_localized", ""),
        "metadata_strategy": metadata.get("metadata_strategy", ""),
        "format_preference": "webp",
        "optimization_profile": "in_article_image",
        "social_reuse": True,
    }


def semantic_image_priority_value(value: str) -> int:
    priorities = {
        "high": 30,
        "medium": 20,
        "low": 10,
        "none": 0,
        "": 0,
    }
    return priorities.get(str(value or "").strip().lower(), 0)


def placement_for_section_index(index: int) -> str:
    if index <= 1:
        return "after_h2_2"
    if index == 2:
        return "after_h2_4"
    return "before_faq"


def category_from_visual_role(role: str) -> str:
    role = str(role or "").strip()
    return {
        "problem_scene": "problem",
        "investigation_scene": "investigation",
        "analysis_scene": "analysis",
        "consultation_scene": "interview",
        "process_scene": "methodology",
        "standards_documentation_scene": "documents",
        "professional_relevance_scene": "professional",
        "local_context_scene": "local_service",
        "local_service_scene": "local_service",
        "educational_concept_scene": "education",
        "authority_professional_scene": "authority",
        "article_topic_scene": "article",
        "supporting_context_scene": "supporting",
        "case_situation_scene": "case_context",
        "application_scene": "application",
        "benefit_context_scene": "supporting",
        "trust_scene": "trust",
    }.get(role, "supporting")


def topic_suffix_from_section(section_id: str, section_type: str, intelligence: dict) -> str:
    objective = intelligence.get("writing_objective") or ""
    purpose = intelligence.get("purpose") or ""
    role = intelligence.get("image_role") or ""
    fallback = section_type or section_id or "supporting visual"

    suffix = objective or purpose or role or fallback
    return str(suffix).replace("_", " ").strip()


def build_semantic_slot_specs(page_plan: dict, minimum_images: int = 2) -> list[dict]:
    """
    Build article image slots from section_intelligence.

    This is the Phase 4.3 source of truth.
    Images belong to meaningful sections, not to a fixed count.
    """
    page_plan = page_plan or {}
    required_sections = page_plan.get("required_sections") or []
    section_intelligence = page_plan.get("section_intelligence") or {}

    candidates = []

    for order, section in enumerate(required_sections, start=1):
        if not isinstance(section, dict):
            continue

        section_id = section.get("id") or ""
        section_type = section.get("type") or ""
        intelligence = section_intelligence.get(section_id) or {}

        image_role = intelligence.get("image_role") or ""
        image_priority = intelligence.get("image_priority") or ""
        priority_value = semantic_image_priority_value(image_priority)

        if not image_role or image_role == "none" or priority_value <= 0:
            continue

        if section_type in {"faq", "cta", "soft_cta", "strategic_links", "related_services"}:
            continue

        candidates.append(
            {
                "section_id": section_id,
                "section_type": section_type,
                "priority_value": priority_value,
                "section_order": order,
                "slot_id": f"in_article_{len(candidates) + 1}",
                "placement": placement_for_section_index(len(candidates) + 1),
                "topic_suffix": topic_suffix_from_section(section_id, section_type, intelligence),
                "category": category_from_visual_role(image_role),
                "visual_role": image_role,
                "purpose": intelligence.get("purpose", ""),
                "writing_objective": intelligence.get("writing_objective", ""),
                "visitor_state": intelligence.get("visitor_state", ""),
                "conversion_stage": intelligence.get("conversion_stage", ""),
                "required": priority_value >= 30,
                "source": "section_intelligence",
            }
        )

    candidates.sort(
        key=lambda item: (
            item["priority_value"],
            -item["section_order"],
        ),
        reverse=True,
    )

    selected = sorted(
        candidates[:MAX_ARTICLE_IMAGES],
        key=lambda item: item["section_order"],
    )

    for index, item in enumerate(selected, start=1):
        item["slot_id"] = f"in_article_{index}"
        item["placement"] = placement_for_section_index(index)

    if len(selected) >= minimum_images:
        return selected

    return selected


def build_blueprint_slot_specs(page_plan: dict) -> list[dict]:
    blueprint_image_slots = (page_plan or {}).get("image_slots") or []
    slot_specs = []

    for raw in blueprint_image_slots:
        if not isinstance(raw, dict):
            continue

        slot_id = raw.get("slot_id") or ""
        if not slot_id or slot_id in ("featured_image", "hero_image"):
            continue

        role = raw.get("visual_role") or raw.get("role") or "supporting_scene"
        purpose = raw.get("purpose", "")

        slot_specs.append(
            {
                "slot_id": slot_id,
                "placement": raw.get("placement") or "in_article",
                "topic_suffix": purpose or role,
                "category": category_from_visual_role(role),
                "visual_role": role,
                "purpose": purpose,
                "required": bool(raw.get("required", False)),
                "source": "page_plan_image_slots_fallback",
            }
        )

    return slot_specs[:MAX_ARTICLE_IMAGES]


def legacy_default_slot_specs():
    return [
        {
            "slot_id": "in_article_1",
            "placement": "after_h2_2",
            "topic_suffix": "process and preparation",
            "category": "methodology",
            "visual_role": "investigation_scene",
            "source": "legacy_default_slots",
            "required": True,
        },
        {
            "slot_id": "in_article_2",
            "placement": "after_h2_4",
            "topic_suffix": "professional question review",
            "category": "documents",
            "visual_role": "analysis_scene",
            "source": "legacy_default_slots",
            "required": True,
        },
    ]


def count_generated_images(image_plan: dict) -> int:
    count = 0

    featured = image_plan.get("featured_image") or {}
    if featured.get("source_type") in {"ai_generation_candidate", "generated_image"}:
        count += 1

    for slot in image_plan.get("in_article_images") or []:
        if isinstance(slot, dict) and slot.get("source_type") in {"ai_generation_candidate", "generated_image"}:
            count += 1

    return count


def expand_image_plan_with_in_article_images(
    *,
    image_plan,
    workspace_id,
    page_type,
    topic,
    language,
    country,
    page_slug,
    minimum_images=2,
    page_plan=None,
):
    image_plan = image_plan or {}
    image_plan.setdefault("in_article_images", [])

    existing_slots = image_plan.get("in_article_images") or []
    used_asset_ids = set()

    featured = image_plan.get("featured_image", {})
    if featured.get("asset_id"):
        used_asset_ids.add(featured["asset_id"])

    page_plan = page_plan or image_plan.get("page_plan") or {}

    semantic_slot_specs = build_semantic_slot_specs(
        page_plan=page_plan,
        minimum_images=minimum_images,
    )

    if semantic_slot_specs:
        slot_specs = semantic_slot_specs
        expansion_source = "section_intelligence"
    else:
        blueprint_specs = build_blueprint_slot_specs(page_plan)
        if blueprint_specs:
            slot_specs = blueprint_specs
            expansion_source = "page_plan_image_slots_fallback"
        else:
            slot_specs = legacy_default_slot_specs()
            expansion_source = "legacy_default_slots"

    desired_count = min(
        MAX_ARTICLE_IMAGES,
        max(
            minimum_images,
            len([spec for spec in slot_specs if spec.get("required")]),
        ),
        len(slot_specs),
    )

    if len(existing_slots) >= desired_count:
        image_plan["in_article_images"] = existing_slots[:MAX_ARTICLE_IMAGES]
        image_plan["in_article_image_count"] = len(image_plan["in_article_images"])
        image_plan["image_plan_expanded"] = True
        image_plan["image_plan_expansion_source"] = expansion_source
        image_plan["article_image_policy"] = {
            "max_article_images": MAX_ARTICLE_IMAGES,
            "max_generated_images_per_page": MAX_GENERATED_IMAGES_PER_PAGE,
        }
        return image_plan

    existing_slot_ids = {
        str(slot.get("slot_id") or "")
        for slot in existing_slots
        if isinstance(slot, dict)
    }

    generated_count = count_generated_images(image_plan)

    for spec in slot_specs:
        if len(existing_slots) >= desired_count:
            break

        if spec["slot_id"] in existing_slot_ids:
            continue

        slot_topic = f"{topic} - {spec['topic_suffix']}"
        filename_base = f"{page_slug or 'imagen'}-{spec['slot_id']}"

        asset = select_best_asset(
            page_type=page_type,
            topic=slot_topic,
            exclude_asset_ids=used_asset_ids,
        )

        if int(asset.get("score", 0) or 0) >= IMAGE_SELECTION_THRESHOLD:
            slot = build_existing_asset_slot(
                asset=asset,
                workspace_id=workspace_id,
                topic=slot_topic,
                language=language,
                country=country,
                page_type=page_type,
                placement=spec["placement"],
                slot_id=spec["slot_id"],
                filename_base=filename_base,
            )

            if asset.get("asset_id"):
                used_asset_ids.add(asset["asset_id"])
        else:
            if generated_count >= MAX_GENERATED_IMAGES_PER_PAGE:
                continue

            slot = build_generation_candidate(
                workspace_id=workspace_id,
                topic=slot_topic,
                language=language,
                country=country,
                page_type=page_type,
                category=spec["category"],
                placement=spec["placement"],
                filename_base=filename_base,
                reason=(
                    "No approved existing in-article image asset reached "
                    f"threshold {IMAGE_SELECTION_THRESHOLD}. "
                    f"Best score: {asset.get('score', 0)}."
                ),
            )

            generated_count += 1
            text_policy = image_text_policy(slot)
            slot["prompt"] = str(slot.get("prompt") or "").strip() + text_policy["prompt_suffix"]
            slot["negative_prompt"] = text_policy["negative_prompt"]
            slot["caption"] = ""

        slot["slot_id"] = spec["slot_id"]
        slot["placement"] = spec["placement"]
        slot["visual_role"] = spec.get("visual_role", "")
        slot["role"] = spec.get("visual_role", "")
        slot["purpose"] = spec.get("purpose", "")
        slot["section_id"] = spec.get("section_id", "")
        slot["section_type"] = spec.get("section_type", "")
        slot["writing_objective"] = spec.get("writing_objective", "")
        slot["visitor_state"] = spec.get("visitor_state", "")
        slot["conversion_stage"] = spec.get("conversion_stage", "")
        slot["source"] = spec.get("source", "")

        existing_slots.append(slot)
        existing_slot_ids.add(spec["slot_id"])

    image_plan["in_article_images"] = existing_slots[:MAX_ARTICLE_IMAGES]
    image_plan["in_article_image_count"] = len(image_plan["in_article_images"])
    image_plan["image_plan_expanded"] = True
    image_plan["image_plan_expansion_source"] = expansion_source
    image_plan["article_image_policy"] = {
        "max_article_images": MAX_ARTICLE_IMAGES,
        "max_generated_images_per_page": MAX_GENERATED_IMAGES_PER_PAGE,
    }

    return image_plan
