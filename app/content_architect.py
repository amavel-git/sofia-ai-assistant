#!/usr/bin/env python3
"""
Sofia Content Architect

Phase 4.4B

Transforms a Generation Package into
section-centric content architecture.

Language agnostic.

Does NOT generate prompts.

Does NOT generate HTML.

Produces deterministic section architecture
that can later be rendered into prompts,
checked by the Critic,
or reused by future AI providers.
"""

from copy import deepcopy


CONTENT_ARCHITECT_VERSION = "1.0"


def build_content_architecture(generation_package):
    """
    Merge all page intelligence into
    self-contained section architecture.
    """

    page_plan = generation_package.get("page_plan", {})

    section_intelligence = (
        page_plan.get("section_intelligence") or {}
    )

    navigation_plan = (
        generation_package.get("navigation") or {}
    )

    image_plan = (
        generation_package.get("image_plan") or {}
    )

    presentation = (
        generation_package.get("page_presentation") or {}
    )

    validation = (
        page_plan.get("validation_requirements") or {}
    )

    architecture = {

        "version": CONTENT_ARCHITECT_VERSION,

        "draft_id": generation_package.get("draft_id"),

        "workspace_id": generation_package.get("workspace_id"),

        "page_type": page_plan.get("page_type"),

        "sections": []
    }

    #
    # Index image slots by section_id
    #

    image_index = {}

    for image in image_plan.get("in_article_images", []):

        section_id = image.get("section_id")

        if section_id:

            image_index.setdefault(
                section_id,
                []
            ).append(
                deepcopy(image)
            )

    #
    # Index navigation
    #

    navigation_index = (
        navigation_plan.get("sections") or {}
    )

    #
    # Build one architecture object
    # per section.
    #

    for section in page_plan.get(
        "required_sections",
        []
    ):

        section_id = section.get("id")

        section_type = section.get("type")

        architecture["sections"].append({

            "section_id": section_id,

            "section_type": section_type,

            "required": section.get(
                "required",
                False
            ),

            "minimum_words": section.get(
                "min_words",
                0
            ),

            #
            # Semantic intelligence
            #

            "semantic": deepcopy(
                section_intelligence.get(
                    section_id,
                    {}
                )
            ),

            #
            # Navigation
            #

            "navigation": deepcopy(
                navigation_index.get(
                    section_id,
                    {}
                )
            ),

            #
            # Images
            #

            "images": deepcopy(
                image_index.get(
                    section_id,
                    []
                )
            ),

            #
            # Presentation
            #

            "presentation": deepcopy(
                presentation
            ),

            #
            # Validation
            #

            "validation": deepcopy(
                validation
            )

        })

    return architecture


def summarize_architecture(
    architecture
):
    """
    Lightweight debugging helper.
    """

    return {

        "version":
            architecture.get("version"),

        "page_type":
            architecture.get("page_type"),

        "sections":
            len(
                architecture.get(
                    "sections",
                    []
                )
            )

    }


if __name__ == "__main__":

    print(
        "Content Architect\n"
        "Import build_content_architecture()."
    )
