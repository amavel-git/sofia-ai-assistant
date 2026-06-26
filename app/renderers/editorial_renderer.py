#!/usr/bin/env python3
"""
Sofia Editorial Renderer

Generic renderer for Editorial AI tasks.

This module converts deterministic Editorial Tasks into model-ready prompts.

It contains no Sofia business logic and no localized wording.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from app.renderers.prompt_renderer import (
    build_full_page_prompt_from_editorial_package,
)


EDITORIAL_RENDERER_VERSION = "1.1"


CRITIC_FINDING_TYPES: List[str] = [
    "purpose_not_fulfilled",
    "writing_objective_not_fulfilled",
    "visitor_state_mismatch",
    "transition_issue",
    "heading_issue",
    "repetition",
    "internal_link_issue",
    "cta_timing_issue",
    "semantic_inconsistency",
    "image_section_mismatch",
    "conversion_flow_issue",
    "content_quality",
    "editorial_quality",
    "missing_section",
    "section_too_short",
    "other",
]


CRITIC_SEVERITIES: List[str] = [
    "info",
    "warning",
    "needs_repair",
    "blocker",
]


def format_allowed_values(values: List[str]) -> str:
    return "\n".join(f"- {value}" for value in values)


def render_writer_prompt(
    *,
    editorial_task: Dict[str, Any],
    base_prompt: str,
) -> str:
    """
    Render a full-page Writer prompt from a write_page Editorial Task.
    """

    if editorial_task.get("task_type") != "write_page":
        raise ValueError("render_writer_prompt requires a write_page task.")

    editorial_package = editorial_task.get("editorial_package") or {}

    return build_full_page_prompt_from_editorial_package(
        base_prompt=base_prompt,
        editorial_package=editorial_package,
    )


def render_critic_prompt(
    *,
    editorial_task: Dict[str, Any],
) -> str:
    """
    Render a Critic prompt from a critique_page Editorial Task.

    The Critic must evaluate only.
    It must not rewrite content.
    """

    if editorial_task.get("task_type") != "critique_page":
        raise ValueError("render_critic_prompt requires a critique_page task.")

    editorial_package = editorial_task.get("editorial_package") or {}
    payload = editorial_task.get("payload") or {}
    generated_html = payload.get("generated_html", "")

    section_contracts = (
        editorial_package
        .get("section_contracts", {})
        .get("section_contracts", [])
    )

    section_contracts_json = json.dumps(
        section_contracts,
        ensure_ascii=False,
        indent=2,
    )

    finding_types_text = format_allowed_values(CRITIC_FINDING_TYPES)
    severities_text = format_allowed_values(CRITIC_SEVERITIES)

    return (
        "SOFIA EDITORIAL CRITIC TASK\n\n"
        "You are evaluating generated page HTML against deterministic "
        "Sofia Section Contracts.\n\n"
        "Rules:\n"
        "- Do not rewrite the content.\n"
        "- Do not create new sections.\n"
        "- Do not change the page strategy.\n"
        "- Evaluate editorial quality only.\n"
        "- Return ONLY valid JSON.\n"
        "- Do not include explanations outside the JSON.\n\n"
        "Use ONLY the following finding_type values:\n\n"
        f"{finding_types_text}\n\n"
        "Use ONLY the following severity values:\n\n"
        f"{severities_text}\n\n"
        "Evaluate the generated HTML against the following section contracts:\n\n"
        f"{section_contracts_json}\n\n"
        "Generated HTML:\n\n"
        f"{generated_html}\n\n"
        "Return JSON with this exact structure:\n\n"
        "{\n"
        '  "findings": [\n'
        "    {\n"
        '      "section_id": "",\n'
        '      "section_type": "",\n'
        '      "finding_type": "",\n'
        '      "severity": "",\n'
        '      "message": "",\n'
        '      "evidence": "",\n'
        '      "recommendation": ""\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ).strip()


def render_repair_prompt(
    *,
    editorial_task: Dict[str, Any],
) -> str:
    """
    Render a future Repair prompt from a repair_sections Editorial Task.

    This is a placeholder renderer for Phase 6.3.
    """

    if editorial_task.get("task_type") != "repair_sections":
        raise ValueError("render_repair_prompt requires a repair_sections task.")

    return (
        "SOFIA EDITORIAL REPAIR TASK\n\n"
        "Repair prompt rendering will be implemented in Phase 6.3."
    )


if __name__ == "__main__":
    print("Editorial Renderer module.")
