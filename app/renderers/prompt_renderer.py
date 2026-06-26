#!/usr/bin/env python3
"""
Sofia Prompt Builder

Converts Editorial Packages into model-ready prompt text.

During Phase 6 this module begins evolving from a generic prompt builder
into a renderer layer.

This module contains no Sofia business logic.
"""

from __future__ import annotations

from typing import Any, Dict, List


PROMPT_BUILDER_VERSION = "1.6"


def format_writer_safety_rules_for_prompt() -> str:
    return """
WRITER OUTPUT SAFETY RULES

These rules are mandatory.

Do NOT generate:
- placeholder images
- placeholder URLs
- via.placeholder.com images
- example.com links
- invented image tags
- invented image captions
- invented email addresses
- invented mailto links
- invented phone numbers
- invented WhatsApp links
- invented office addresses

Images are handled by Sofia's deterministic image pipeline.
WordPress/Gutenberg blocks are handled after generation.
Contact blocks are handled by Sofia's WordPress assembly pipeline.

If an image, contact block, WhatsApp block, city grid, trust block, or reusable block is needed,
do not invent it in the HTML body.

Write only the page body content.
Use only links explicitly provided in the prompt.
If no valid contact URL is provided, write plain visitor-facing contact text without a hyperlink.
""".strip()



def format_professional_editorial_quality_rules_for_prompt() -> str:
    return """
PROFESSIONAL EDITORIAL QUALITY RULES

These rules improve writing quality without changing Sofia's strategy.

Write like an experienced investigative or forensic professional, not like a generic content generator.

Mandatory editorial behaviour:
- Open with the real-world problem, risk, decision, or uncertainty behind the topic.
- Use the semantic entities as concrete anchors for examples, explanations, and section depth.
- Do not reduce specific incidents, assets, industries, audiences, or investigation types into generic wording.
- Build a natural narrative from section to section instead of restarting the article at every heading.
- Use transitions that explain why the next section matters.
- Add realistic professional examples when useful, but do not invent specific cases, clients, agencies, names, dates, statistics, or confidential details.
- Explain context, limits, decision-making, and practical implications.
- Use confident, precise, professional language.
- Avoid exaggerated marketing claims, guarantees, fear-based language, or sensational tone.
- Avoid repetitive openings such as "In today's world", "It is important to note", or "When it comes to".
- Avoid repeating the same keyphrase unnaturally.
- Use SEO wording naturally inside useful explanations, not as keyword stuffing.
- Vary sentence length and paragraph rhythm.
- Prefer clear, mature paragraphs over generic bullet lists, unless a list improves readability.
- Replace generic business language with concrete operational language derived from the topic, semantic entities, and section contract.
- Avoid vague phrases such as "significant challenges", "important problem", "deeper issues", "negative impact", "current situation", or "various factors" unless immediately explained with specific context.
- When discussing a business or investigation, mention the type of records, access points, responsibilities, documents, controls, timelines, or decision pressures that are relevant to the provided topic.
- Do not invent exact evidence, figures, clients, dates, or events. Use professional scenario language such as "may show", "can involve", "often requires", or "should be reviewed".

Section quality expectations:
- Introductions should quickly show why the topic matters to the visitor.
- Problem/context sections should explain the practical situation, not only define terms.
- Investigation/process sections should explain how professionals think, sequence decisions, and avoid premature conclusions.
- Service/application sections should explain when the service is useful, when it is limited, and how it fits into a broader professional process.
- CTA sections should sound advisory and professional, not pushy.
- FAQ answers should be specific, useful, and anticipate the visitor's real doubts.

Do not change the page strategy.
Do not add invented facts.
Do not ignore safety, language, register, or localization rules provided elsewhere in the prompt.
""".strip()


def format_semantic_entities_for_prompt(editorial_package: Dict[str, Any]) -> str:
    entities = (
        editorial_package.get("semantic_entities")
        or (editorial_package.get("section_contracts") or {}).get("semantic_entities")
        or (editorial_package.get("content_architecture") or {}).get("semantic_entities")
        or (editorial_package.get("page_plan") or {}).get("semantic_entities")
        or {}
    )

    if not entities:
        return "No semantic entities available."

    labels = {
        "service": "Service",
        "incident": "Incident",
        "object": "Object / asset involved",
        "industry": "Industry / sector",
        "country": "Country / market",
        "audience": "Audience",
        "investigation_type": "Investigation type",
        "raw_topic_text": "Original topic text",
    }

    lines = [
        "MANDATORY SEMANTIC ENTITIES",
        "",
        "Use these entities as the page's concrete topic anchor.",
        "Do not generalize them into broader concepts unless the source is genuinely broader.",
        "Every major non-FAQ section should remain connected to these entities.",
        "",
    ]

    for key, label in labels.items():
        value = entities.get(key)
        if value:
            lines.append(f"- {label}: {value}")

    return "\n".join(lines).strip()



def format_section_editorial_execution_guidance_for_prompt(contract: Dict[str, Any]) -> List[str]:
    section_type = str(contract.get("section_type") or "").lower()
    writing = contract.get("writing") or {}

    guidance: List[str] = []
    guidance.append("   Editorial execution guidance:")

    guidance.append(
        "   - Start this section with a concrete professional observation, not a generic definition."
    )
    guidance.append(
        "   - Write at least two developed paragraphs for normal non-FAQ sections unless the contract clearly requires a shorter section."
    )
    guidance.append(
        "   - Connect the explanation to the section purpose and topic focus."
    )
    guidance.append(
        "   - Add practical reasoning: what the visitor should understand, evaluate, or avoid."
    )
    guidance.append(
        "   - Develop the section with context, implications, and professional judgement instead of giving only a short summary."
    )
    guidance.append(
        "   - Use specific examples only when they can be derived from the provided topic, entities, or contract."
    )
    guidance.append(
        "   - Prefer concrete operational details over abstract business language: records, access, authorization, documents, responsibilities, timelines, controls, inconsistencies, and decision risks."
    )

    if any(token in section_type for token in ["intro", "hero", "opening"]):
        guidance.append(
            "   - Make the opening paragraph immediately show the practical risk, uncertainty, or decision behind the page."
        )

    if any(token in section_type for token in ["problem", "pain", "context", "risk"]):
        guidance.append(
            "   - Explain why the problem creates operational, legal, financial, or decision-making pressure."
        )

    if any(token in section_type for token in ["process", "investigation", "method", "procedure"]):
        guidance.append(
            "   - Explain the professional sequence of thinking: review information, define facts, formulate questions, interpret limits."
        )

    if any(token in section_type for token in ["service", "solution", "application"]):
        guidance.append(
            "   - Explain when the service is appropriate and when it should remain only one part of a broader process."
        )

    if any(token in section_type for token in ["faq", "question"]):
        guidance.append(
            "   - Answer FAQs as a professional would answer a real client: direct, specific, cautious, and useful."
        )
        guidance.append(
            "   - FAQ answers should normally contain two to four useful sentences, not only a short yes/no answer."
        )

    if any(token in section_type for token in ["cta", "conversion", "contact"]):
        guidance.append(
            "   - Write the CTA as professional guidance. Avoid pressure, hype, or generic sales language."
        )
        guidance.append(
            "   - Explain what information the visitor should prepare before requesting a professional evaluation."
        )

    if writing.get("topic_focus"):
        guidance.append(
            "   - Keep the section anchored to the topic focus instead of drifting into general polygraph content."
        )

    return guidance


def format_section_contracts_for_prompt(editorial_package: Dict[str, Any]) -> str:
    section_package = editorial_package.get("section_contracts") or {}
    contracts = section_package.get("section_contracts") or []

    if not contracts:
        return "No section contracts available."

    lines: List[str] = []

    lines.append("SECTION-BY-SECTION EDITORIAL CONTRACTS")
    lines.append("")
    lines.append("Use these contracts as the primary writing guide.")
    lines.append("Do not mention contract IDs or section IDs in the final page.")
    lines.append("Convert each section contract into natural visitor-facing content.")
    lines.append("")

    for contract in contracts:
        writing = contract.get("writing") or {}
        transition = contract.get("transition") or {}
        navigation = contract.get("navigation") or {}
        images = contract.get("images") or []

        lines.append(
            f"{contract.get('section_order', '')}. "
            f"Section ID: {contract.get('section_id', '')}"
        )
        lines.append(f"   Section type: {contract.get('section_type', '')}")
        lines.append(f"   Required: {contract.get('required', False)}")
        lines.append(f"   Estimated words: {contract.get('estimated_words', 0)}")
        lines.append(f"   Heading level: {contract.get('heading_level', 'H2')}")

        lines.append("   Writing contract:")

        for key in [
            "purpose",
            "objective",
            "visitor_state",
            "conversion_stage",
            "content_priority",
            "topic_focus",
            "cta_intent",
            "internal_link_intent",
        ]:
            value = writing.get(key)
            if value:
                lines.append(f"   - {key}: {value}")

        must_avoid = writing.get("must_avoid") or []
        if must_avoid:
            lines.append(
                "   - must avoid: "
                + "; ".join(str(item) for item in must_avoid)
            )

        quality_risk_flags = writing.get("quality_risk_flags") or []
        if quality_risk_flags:
            lines.append(
                "   - quality risk flags: "
                + "; ".join(str(item) for item in quality_risk_flags)
            )

        lines.extend(format_section_editorial_execution_guidance_for_prompt(contract))

        if transition:
            lines.append("   Transition context:")
            if transition.get("previous_section_id"):
                lines.append(
                    f"   - previous section: "
                    f"{transition.get('previous_section_id')} "
                    f"({transition.get('previous_section_type', '')})"
                )
            if transition.get("next_section_id"):
                lines.append(
                    f"   - next section: "
                    f"{transition.get('next_section_id')} "
                    f"({transition.get('next_section_type', '')})"
                )

        goal = navigation.get("navigation_goal") or {}
        resolved_links = navigation.get("resolved_links") or []

        if goal or resolved_links:
            lines.append("   Navigation contract:")

            if goal:
                lines.append(
                    f"   - primary target: "
                    f"{goal.get('primary_target', '')}"
                )
                lines.append(
                    f"   - secondary target: "
                    f"{goal.get('secondary_target', '')}"
                )
                lines.append(
                    f"   - max links: "
                    f"{goal.get('max_links', '')}"
                )

            if resolved_links:
                lines.append("   - resolved links:")
                for link in resolved_links:
                    lines.append(
                        f"     * {link.get('semantic_target', '')}: "
                        f"{link.get('url', '')}"
                    )

        if images:
            lines.append("   Image contract:")
            for image in images:
                lines.append(
                    f"   - {image.get('slot_id', '')}: "
                    f"role={image.get('visual_role', '')}, "
                    f"placement={image.get('placement', '')}"
                )

        lines.append("")

    return "\n".join(lines).strip()


def build_full_page_prompt_from_editorial_package(
    *,
    base_prompt: str,
    editorial_package: Dict[str, Any],
) -> str:
    contract_prompt = format_section_contracts_for_prompt(editorial_package)
    semantic_entities_prompt = format_semantic_entities_for_prompt(editorial_package)

    return (
        f"{base_prompt.strip()}\n\n"
        f"{format_writer_safety_rules_for_prompt()}\n\n"
        f"{format_professional_editorial_quality_rules_for_prompt()}\n\n"
        f"{semantic_entities_prompt}\n\n"
        "SOFIA EDITORIAL PACKAGE LAYER\n\n"
        "The following editorial contracts come from Sofia Core Intelligence.\n"
        "They are deterministic and should be treated as the primary "
        "section-writing instructions.\n"
        "Do not reconstruct page strategy. Follow the contracts.\n"
        "Use them to control section purpose, visitor journey, transitions, "
        "internal navigation, image alignment, CTA timing, and conversion flow.\n\n"
        f"{contract_prompt}\n"
    ).strip()


def format_section_architecture_for_prompt(content_architecture: Dict[str, Any]) -> str:
    sections = content_architecture.get("sections") or []

    if not sections:
        return "No section architecture available."

    lines: List[str] = []
    lines.append("SECTION-BY-SECTION CONTENT ARCHITECTURE")
    lines.append("")
    lines.append("Use this as the primary section-writing guide.")
    lines.append("Do not mention section IDs in the final page.")
    lines.append("Convert each section into natural visitor-facing headings.")
    lines.append("")

    for index, section in enumerate(sections, start=1):
        semantic = section.get("semantic") or {}
        navigation = section.get("navigation") or {}
        images = section.get("images") or []

        lines.append(f"{index}. Section ID: {section.get('section_id', '')}")
        lines.append(f"   Section type: {section.get('section_type', '')}")
        lines.append(f"   Required: {section.get('required', False)}")
        lines.append(f"   Minimum words: {section.get('minimum_words', 0)}")

        if semantic:
            lines.append("   Semantic intent:")
            for key in [
                "purpose",
                "visitor_state",
                "conversion_stage",
                "writing_objective",
                "content_priority",
                "drafting_focus",
                "cta_intent",
                "internal_link_intent",
            ]:
                value = semantic.get(key)
                if value:
                    lines.append(f"   - {key}: {value}")

            avoid = semantic.get("avoid") or []
            if avoid:
                lines.append("   - avoid: " + "; ".join(str(item) for item in avoid))

        goal = navigation.get("navigation_goal") or {}
        resolved_links = navigation.get("resolved_links") or []

        if goal or resolved_links:
            lines.append("   Navigation intent:")
            if goal:
                lines.append(f"   - primary target: {goal.get('primary_target', '')}")
                lines.append(f"   - secondary target: {goal.get('secondary_target', '')}")
                lines.append(f"   - max links: {goal.get('max_links', '')}")
            if resolved_links:
                lines.append("   - resolved links:")
                for link in resolved_links:
                    lines.append(
                        f"     * {link.get('semantic_target', '')}: {link.get('url', '')}"
                    )

        if images:
            lines.append("   Image intent:")
            for image in images:
                lines.append(
                    f"   - {image.get('slot_id', '')}: "
                    f"role={image.get('visual_role', '')}, "
                    f"placement={image.get('placement', '')}"
                )

        lines.append("")

    return "\n".join(lines).strip()


def build_full_page_prompt(
    *,
    base_prompt: str,
    content_architecture: Dict[str, Any],
) -> str:
    """
    Backward-compatible architecture-based prompt builder.

    New Phase 6 code should prefer build_full_page_prompt_from_editorial_package().
    """

    editorial_package = {
        "version": "legacy-wrapper",
        "content_architecture": content_architecture,
        "section_contracts": {
            "section_contracts": [],
        },
    }

    if editorial_package["section_contracts"]["section_contracts"]:
        return build_full_page_prompt_from_editorial_package(
            base_prompt=base_prompt,
            editorial_package=editorial_package,
        )

    architecture_prompt = format_section_architecture_for_prompt(content_architecture)

    return (
        f"{base_prompt.strip()}\n\n"
        f"{format_writer_safety_rules_for_prompt()}\n\n"
        f"{format_professional_editorial_quality_rules_for_prompt()}\n\n"
        "SOFIA CONTENT ARCHITECTURE LAYER\n\n"
        "The following section architecture comes from Sofia Core Intelligence.\n"
        "It is more specific than generic page-type instructions.\n"
        "Use it to improve section intent, flow, internal navigation, image alignment, "
        "and conversion logic.\n\n"
        f"{architecture_prompt}\n"
    ).strip()


if __name__ == "__main__":
    print("Prompt Builder module. Import build_full_page_prompt().")
