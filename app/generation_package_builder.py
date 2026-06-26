#!/usr/bin/env python3
"""
Sofia Generation Package Builder

Phase 4.4A

Purpose
-------
Build the complete semantic generation package used by AI writers.

This module does NOT generate prompts.

It produces a deterministic package describing everything
the AI needs to know.

Future consumers:

- prompt_builder.py
- content_critic.py
- maintenance_intelligence.py
- AI revision
- future LLM providers

Language agnostic.
"""

from copy import deepcopy


GENERATION_PACKAGE_VERSION = "1.0"


def build_generation_package(
    *,
    draft,
    workspace,
    context,
    page_plan,
    blueprint_package,
    strategy,
    knowledge_package,
    language_profile,
    page_presentation,
    image_plan,
    opportunity_intelligence,
    navigation_plan=None,
):
    """
    Build a complete generation package.

    Nothing here should contain rendered prompt text.

    Everything remains structured.
    """

    package = {
        "version": GENERATION_PACKAGE_VERSION,

        #
        # Core
        #
        "draft_id": draft.get("draft_id"),
        "workspace_id": workspace.get("workspace_id"),

        #
        # Identity
        #
        "context": deepcopy(context),

        #
        # Semantic architecture
        #
        "page_plan": deepcopy(page_plan),

        "blueprint": deepcopy(blueprint_package),

        "strategy": deepcopy(strategy),

        #
        # Content intelligence
        #
        "knowledge": deepcopy(knowledge_package),

        "opportunity_intelligence": deepcopy(
            opportunity_intelligence
        ),

        #
        # Presentation
        #
        "language_profile": deepcopy(language_profile),

        "page_presentation": deepcopy(page_presentation),

        #
        # Navigation
        #
        "navigation": deepcopy(
            navigation_plan or {}
        ),

        #
        # Images
        #
        "image_plan": deepcopy(image_plan),

        #
        # Future extensions
        #
        "market_intelligence": {},

        "critic": {},

        "maintenance": {},
    }

    return package


def summarize_generation_package(package):
    """
    Lightweight debug helper.
    """

    return {
        "version": package.get("version"),

        "workspace": package.get("workspace_id"),

        "draft": package.get("draft_id"),

        "blueprint": (
            package.get("blueprint", {})
            .get("blueprint_id")
        ),

        "page_type": (
            package.get("page_plan", {})
            .get("page_type")
        ),

        "sections": len(
            package.get("page_plan", {})
            .get("required_sections", [])
        ),

        "images": len(
            package.get("image_plan", {})
            .get("in_article_images", [])
        ),

        "knowledge_blocks": len(
            package.get("knowledge", {})
            .get("selected_blocks", [])
        ),
    }


if __name__ == "__main__":

    print(
        "Generation Package Builder\n"
        "Import build_generation_package()."
    )
