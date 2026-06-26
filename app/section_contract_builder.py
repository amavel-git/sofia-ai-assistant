#!/usr/bin/env python3
"""
Sofia Section Contract Builder

Builds section-level editorial contracts from Content Architecture.

A Section Contract is not a prompt.
It is a reusable editorial contract consumed by:
- Prompt Builder
- Writer Agent
- future Critic Agent
- future Repair Agent
- future Maintenance Agent
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List


SECTION_CONTRACT_VERSION = "1.0"


def estimate_section_words(section: Dict[str, Any]) -> int:
    semantic = section.get("semantic") or {}
    minimum = int(section.get("minimum_words") or 0)
    priority = semantic.get("content_priority", "")

    if minimum > 0:
        return minimum

    if priority == "critical":
        return 220

    if priority == "high":
        return 180

    if priority == "supporting":
        return 120

    return 150


def build_transition_context(sections: List[Dict[str, Any]], index: int) -> Dict[str, str]:
    previous_section = sections[index - 1] if index > 0 else {}
    next_section = sections[index + 1] if index + 1 < len(sections) else {}

    return {
        "previous_section_id": previous_section.get("section_id", ""),
        "previous_section_type": previous_section.get("section_type", ""),
        "next_section_id": next_section.get("section_id", ""),
        "next_section_type": next_section.get("section_type", ""),
    }


def build_section_contract(section: Dict[str, Any], sections: List[Dict[str, Any]], index: int) -> Dict[str, Any]:
    semantic = section.get("semantic") or {}
    transition = build_transition_context(sections, index)

    return {
        "version": SECTION_CONTRACT_VERSION,

        "section_order": index + 1,
        "section_id": section.get("section_id", ""),
        "section_type": section.get("section_type", ""),
        "heading_level": "H2",
        "required": bool(section.get("required", False)),
        "estimated_words": estimate_section_words(section),

        "semantic": deepcopy(semantic),
        "navigation": deepcopy(section.get("navigation") or {}),
        "images": deepcopy(section.get("images") or []),
        "validation": deepcopy(section.get("validation") or {}),

        "writing": {
            "purpose": semantic.get("purpose", ""),
            "objective": semantic.get("writing_objective", ""),
            "visitor_state": semantic.get("visitor_state", ""),
            "conversion_stage": semantic.get("conversion_stage", ""),
            "content_priority": semantic.get("content_priority", ""),
            "topic_focus": semantic.get("drafting_focus", ""),
            "cta_intent": semantic.get("cta_intent", ""),
            "internal_link_intent": semantic.get("internal_link_intent", ""),
            "must_avoid": deepcopy(semantic.get("avoid") or []),
            "quality_risk_flags": deepcopy(semantic.get("quality_risk_flags") or []),
        },

        "transition": transition,
    }


def build_section_contracts(content_architecture: Dict[str, Any]) -> Dict[str, Any]:
    sections = content_architecture.get("sections") or []

    contracts = [
        build_section_contract(section, sections, index)
        for index, section in enumerate(sections)
    ]

    return {
        "version": SECTION_CONTRACT_VERSION,
        "draft_id": content_architecture.get("draft_id", ""),
        "workspace_id": content_architecture.get("workspace_id", ""),
        "page_type": content_architecture.get("page_type", ""),
        "section_count": len(contracts),
        "section_contracts": contracts,
    }


def summarize_section_contracts(section_contract_package: Dict[str, Any]) -> Dict[str, Any]:
    contracts = section_contract_package.get("section_contracts") or []

    return {
        "version": section_contract_package.get("version", ""),
        "page_type": section_contract_package.get("page_type", ""),
        "section_count": len(contracts),
        "critical_sections": len([
            item for item in contracts
            if (item.get("writing") or {}).get("content_priority") == "critical"
        ]),
        "sections_with_images": len([
            item for item in contracts
            if item.get("images")
        ]),
        "sections_with_navigation": len([
            item for item in contracts
            if (item.get("navigation") or {}).get("navigation_goal")
        ]),
    }


if __name__ == "__main__":
    print("Section Contract Builder module.")
