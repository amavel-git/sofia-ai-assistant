#!/usr/bin/env python3
"""
Sofia Phase 4 — Semantic Page Intelligence.

This module does not generate content.
It converts a resolved page blueprint into a richer semantic execution plan.

Purpose:
- section intelligence
- dynamic image slot planning
- internal link intent planning
- CTA/trust placement planning
- future Content Critic comparison baseline
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from app.page_blueprints import build_page_blueprint_package
from app.workspace_paths import get_workspace_draft_registry_path


def load_json(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}
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


def find_draft(registry, draft_id: str):
    for draft in get_drafts(registry):
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def infer_topic_family(draft: Dict[str, Any]) -> str:
    intelligence = draft.get("opportunity_intelligence") or {}
    return (
        draft.get("topic_family")
        or draft.get("visual_topic_family")
        or intelligence.get("topic_family")
        or intelligence.get("visual_topic_family")
        or "general_polygraph_service"
    )


def infer_page_type(draft: Dict[str, Any]) -> str:
    return (
        draft.get("page_type")
        or draft.get("content_type")
        or draft.get("blueprint_id")
        or "landing_page"
    )


def section_defaults(section_id: str, page_type: str) -> Dict[str, Any]:
    """
    Deterministic semantic defaults.
    These are structural, not language-specific.
    """
    section_id = str(section_id or "").lower()

    mapping = {
        "hero": {
            "purpose": "capture_attention_and_confirm_relevance",
            "image_role": "problem_scene",
            "internal_link_intent": "none",
            "cta_intent": "soft_contact",
            "conversion_stage": "attention",
        },
        "problem": {
            "purpose": "visitor_identification",
            "image_role": "problem_scene",
            "internal_link_intent": "related_service",
            "cta_intent": "none",
            "conversion_stage": "recognition",
        },
        "consequences": {
            "purpose": "increase_urgency",
            "image_role": "supporting_scene",
            "internal_link_intent": "related_case_or_service",
            "cta_intent": "soft_contact",
            "conversion_stage": "urgency",
        },
        "investigation": {
            "purpose": "explain_complexity",
            "image_role": "investigation_scene",
            "internal_link_intent": "process_or_methodology",
            "cta_intent": "none",
            "conversion_stage": "complexity",
        },
        "investigation_challenges": {
            "purpose": "explain_complexity",
            "image_role": "investigation_scene",
            "internal_link_intent": "process_or_methodology",
            "cta_intent": "none",
            "conversion_stage": "complexity",
        },
        "solution": {
            "purpose": "position_professional_solution",
            "image_role": "analysis_scene",
            "internal_link_intent": "polygraph_process",
            "cta_intent": "soft_contact",
            "conversion_stage": "solution",
        },
        "polygraph_role": {
            "purpose": "position_polygraph_as_complementary_tool",
            "image_role": "analysis_scene",
            "internal_link_intent": "polygraph_process",
            "cta_intent": "none",
            "conversion_stage": "solution",
        },
        "process": {
            "purpose": "reduce_uncertainty",
            "image_role": "question_preparation_scene",
            "internal_link_intent": "how_it_works",
            "cta_intent": "none",
            "conversion_stage": "reassurance",
        },
        "trust": {
            "purpose": "build_credibility",
            "image_role": "professional_trust_scene",
            "internal_link_intent": "about_or_examiner",
            "cta_intent": "none",
            "conversion_stage": "trust",
        },
        "faq": {
            "purpose": "remove_objections",
            "image_role": "none",
            "internal_link_intent": "supporting_explanation",
            "cta_intent": "none",
            "conversion_stage": "objection_handling",
        },
        "cities": {
            "purpose": "local_reassurance",
            "image_role": "none",
            "internal_link_intent": "city_pages",
            "cta_intent": "local_contact",
            "conversion_stage": "local_trust",
        },
        "cta": {
            "purpose": "generate_contact",
            "image_role": "none",
            "internal_link_intent": "contact",
            "cta_intent": "primary_contact",
            "conversion_stage": "conversion",
        },
        "final_cta": {
            "purpose": "generate_contact",
            "image_role": "none",
            "internal_link_intent": "contact",
            "cta_intent": "primary_contact",
            "conversion_stage": "conversion",
        },
    }

    for key, value in mapping.items():
        if key in section_id:
            return dict(value)

    return {
        "purpose": "support_page_goal",
        "image_role": "supporting_scene",
        "internal_link_intent": "contextual_support",
        "cta_intent": "none",
        "conversion_stage": "support",
    }


def recommended_image_count(page_type: str, word_target: int = 1200) -> int:
    """
    Total image slots including featured image.

    Hardware/resource policy:
    - Always allow 1 featured image.
    - Allow maximum 3 article images.
    - Therefore max total image slots = 4.
    """
    page_type = str(page_type or "").lower()

    if page_type in {"authority_page", "pillar_page"}:
        wanted = 4 if word_target >= 1400 else 3
    elif page_type in {"city_page"}:
        wanted = 3
    elif page_type in {"landing_page"}:
        wanted = 3 if word_target >= 900 else 2
    else:
        wanted = 2

    return min(max(wanted, 1), 4)


def build_dynamic_image_slots(
    sections: List[Dict[str, Any]],
    page_type: str,
    topic_family: str,
    word_target: int = 1200,
) -> List[Dict[str, Any]]:
    wanted = recommended_image_count(page_type, word_target)

    slots = []
    used_roles = set()

    for section in sections:
        role = section.get("image_role")
        if not role or role == "none":
            continue

        if role in used_roles and role not in {"supporting_scene"}:
            continue

        slot_id = "featured_image" if not slots else f"in_article_{len(slots)}"

        slots.append({
            "slot_id": slot_id,
            "section_id": section.get("id"),
            "visual_role": role,
            "visual_topic_family": topic_family,
            "placement_strategy": "section_driven",
            "placement": "featured" if slot_id == "featured_image" else f"after_section:{section.get('id')}",
            "required": slot_id == "featured_image",
        })

        used_roles.add(role)

        if len(slots) >= wanted:
            break

    return slots


def build_internal_link_slots(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    slots = []

    for section in sections:
        intent = section.get("internal_link_intent")
        if not intent or intent == "none":
            continue

        slots.append({
            "section_id": section.get("id"),
            "intent": intent,
            "placement_strategy": "inside_or_after_section",
            "max_links": 1,
            "anchor_style": "natural_contextual",
        })

    return slots


def build_cta_slots(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    slots = []

    for section in sections:
        intent = section.get("cta_intent")
        if not intent or intent == "none":
            continue

        slots.append({
            "section_id": section.get("id"),
            "intent": intent,
            "placement_strategy": "after_section",
            "strength": "primary" if intent == "primary_contact" else "soft",
        })

    return slots


def build_semantic_page_plan(draft: Dict[str, Any], workspace_id: str) -> Dict[str, Any]:
    page_type = infer_page_type(draft)
    blueprint_id = draft.get("blueprint_id") or page_type
    topic_family = infer_topic_family(draft)

    source = {
        "page_type": page_type,
        "blueprint_id": blueprint_id,
        "title": draft.get("title") or draft.get("working_title"),
        "target_keyword": draft.get("target_keyword") or draft.get("focus_keyphrase"),
        "search_intent": draft.get("search_intent"),
        "topic_key": topic_family,
    }

    package = build_page_blueprint_package(source, workspace_id=workspace_id)

    raw_sections = package.get("sections") or []
    semantic_sections = []

    for index, section in enumerate(raw_sections, start=1):
        section_id = section.get("id") or f"section_{index}"
        defaults = section_defaults(section_id, page_type)

        merged = {
            "order": index,
            "id": section_id,
            "type": section.get("type", ""),
            "required": bool(section.get("required")),
            "blueprint_purpose": section.get("purpose", ""),
            **defaults,
            "section_intelligence": section.get("section_intelligence") or {},
            "writing_goal": defaults.get("purpose"),
            "avoid_repetition": True,
            "must_advance_narrative": True,
        }

        semantic_sections.append(merged)

    word_target = (
        (draft.get("generated_content") or {}).get("target_word_count")
        or (package.get("validation_requirements") or {}).get("target_word_count")
        or 1200
    )

    return {
        "version": "1.0",
        "source": "semantic_page_intelligence_v1",
        "workspace_id": workspace_id,
        "draft_id": draft.get("draft_id"),
        "page_type": page_type,
        "blueprint_id": package.get("blueprint_id"),
        "topic_family": topic_family,
        "word_target": word_target,
        "sections": semantic_sections,
        "image_resource_policy": {
            "featured_images": 1,
            "max_article_images": 3,
            "max_total_images": 4,
            "requires_manual_approval_above_limit": True,
        },
        "dynamic_image_slots": build_dynamic_image_slots(
            semantic_sections,
            page_type=page_type,
            topic_family=topic_family,
            word_target=int(word_target or 1200),
        ),
        "internal_link_slots": build_internal_link_slots(semantic_sections),
        "cta_slots": build_cta_slots(semantic_sections),
        "critic_baseline": {
            "check_repetition": True,
            "check_heading_specificity": True,
            "check_conversion_strength": True,
            "check_section_purpose": True,
            "check_image_content_coherence": True,
            "check_internal_link_coverage": True,
        },
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: python -m app.page_semantic_intelligence WORKSPACE_ID DRAFT_ID [--write]")
        raise SystemExit(1)

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]
    write = "--write" in sys.argv

    registry_path = get_workspace_draft_registry_path(workspace_id)
    registry = load_json(registry_path, default={"drafts": []})
    draft = find_draft(registry, draft_id)

    if not draft:
        raise SystemExit(f"Draft not found: {draft_id}")

    plan = build_semantic_page_plan(draft, workspace_id)

    if write:
        draft["semantic_page_plan"] = plan
        save_json(registry_path, registry)
        print(f"Semantic page plan saved to draft: {draft_id}")

    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
