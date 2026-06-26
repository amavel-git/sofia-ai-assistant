#!/usr/bin/env python3
"""
Sofia Image Generation Prompt Builder

Creates AI image generation candidates when no approved existing asset
is strong enough for the page topic/page type.
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    from image_metadata_generator import build_image_metadata
except ModuleNotFoundError:
    from app.image_assets.image_metadata_generator import build_image_metadata


def slugify_filename_base(text: str) -> str:
    text = str(text or "").lower().strip()

    replacements = {
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u",
        "ç": "c",
        "ñ": "n",
    }

    for original, replacement in replacements.items():
        text = text.replace(original, replacement)

    import re
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)

    return text.strip("-") or "imagen-poligrafo"


def build_generation_prompt(
    *,
    topic: str,
    page_type: str,
    country: str = "",
    category: str = "professional_consultation",
) -> str:
    prompt_parts = [
        "Realistic documentary-style professional photography.",
        f"Topic: {topic}.",
        f"Page type: {page_type}.",
        "Professional polygraph-related consultation scene.",
        "Modern office environment.",
        "Natural lighting.",
        "Human interaction is central.",
        "Examiner reviewing documents, questions, or case information with a client.",
        "Calm, ethical, confidential and professional atmosphere.",
        "No police interrogation clichés.",
        "No exaggerated wires.",
        "No unrealistic lie detector machine.",
        "No authority badges.",
        "No visual implication of guaranteed results.",
    ]

    if country:
        prompt_parts.append(f"Local context: {country}.")

    if category:
        prompt_parts.append(f"Visual category: {category}.")

    return " ".join(prompt_parts)


def build_generation_candidate(
    *,
    workspace_id: str,
    topic: str,
    language: str,
    country: str = "",
    page_type: str = "",
    category: str = "professional_consultation",
    placement: str = "featured",
    filename_base: str = "",
    reason: str = "No approved existing image asset reached the required selection threshold.",
) -> dict:
    filename_base = filename_base or slugify_filename_base(topic)

    metadata = build_image_metadata(
        workspace_id=workspace_id,
        language=language,
        topic=topic,
        category=category,
        placement=placement,
        page_type=page_type,
        fallback_country=country,
        professional_context="entrevista previa",
        filename_base=filename_base,
    )

    return {
        "source_type": "ai_generation_candidate",
        "status": "generation_needed",
        "reason": reason,
        "topic": topic,
        "category": category,
        "placement": placement,
        "prompt": build_generation_prompt(
            topic=topic,
            page_type=page_type,
            country=metadata.get("country_localized") or country,
            category=category,
        ),
        "source_filename": "",
        "recommended_filename": f"{filename_base}.webp",
        "alt_text": metadata.get("alt_text", ""),
        "title": metadata.get("title", ""),
        "caption": metadata.get("caption", ""),
        "country_localized": metadata.get("country_localized", ""),
        "metadata_strategy": metadata.get("metadata_strategy", ""),
        "format_preference": "webp",
        "optimization_profile": "featured_image",
        "social_reuse": True,
        "generation_model_preference": "Flux2Klein",
        "requires_examiner_approval": True,
        "wordpress_upload_enabled": False,
    }


if __name__ == "__main__":
    sample = build_generation_candidate(
        workspace_id="local.es",
        topic="metodología del polígrafo",
        language="es",
        country="España",
        page_type="educational_page",
        category="methodology",
    )

    print(json.dumps(sample, ensure_ascii=False, indent=2))
