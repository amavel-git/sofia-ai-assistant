#!/usr/bin/env python3
"""
Sofia Image Asset Planner

Builds draft-level image_plan metadata.
Phase 1: no generation, no upload, no insertion.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from image_asset_library import build_basic_image_plan
from image_metadata_generator import build_image_metadata
from image_generation_prompt_builder import build_generation_candidate
from image_selector import select_best_image

IMAGE_SELECTION_THRESHOLD = 999  # AI-first for featured images; existing assets are fallback only.


def slugify_filename_base(text: str, fallback: str = "imagen-poligrafo") -> str:
    text = (text or "").strip().lower()
    text = (
        text.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
        .replace("ç", "c")
    )
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or fallback


def infer_image_category(page_type: str, topic: str) -> str:
    combined = f"{page_type} {topic}".lower()

    if any(x in combined for x in ["historia", "history"]):
        return "history"

    if any(x in combined for x in ["metodologia", "methodology", "funciona", "cómo funciona", "chart", "grafica"]):
        return "methodology"

    if any(x in combined for x in ["instrument", "polar", "equipo", "software"]):
        return "instrumentation"

    if any(x in combined for x in ["legal", "abogado", "court", "tribunal", "juicio"]):
        return "legal"

    if any(x in combined for x in ["tratamiento", "therapy", "therapeutic", "psicoterapia"]):
        return "treatment"

    return "interview"


def build_alt_text(language: str, topic: str, country: str = "") -> str:
    topic = topic.strip() if topic else "prueba de polígrafo"

    if language == "es":
        if country:
            return f"Imagen profesional relacionada con {topic} en {country}"
        return f"Imagen profesional relacionada con {topic}"

    if language == "pt":
        if country:
            return f"Imagem profissional relacionada com {topic} em {country}"
        return f"Imagem profissional relacionada com {topic}"

    if language == "fr":
        if country:
            return f"Image professionnelle liée à {topic} en {country}"
        return f"Image professionnelle liée à {topic}"

    return f"Professional image related to {topic}"


def build_caption(language: str, topic: str) -> str:
    topic = topic.strip() if topic else "el proceso poligráfico"

    if language == "es":
        return f"Una imagen profesional para contextualizar {topic}."
    if language == "pt":
        return f"Uma imagem profissional para contextualizar {topic}."
    if language == "fr":
        return f"Une image professionnelle pour contextualiser {topic}."

    return f"A professional image to contextualize {topic}."


def build_ai_prompt_placeholder(language: str, topic: str, country: str = "") -> str:
    if language == "es":
        place = f" en {country}" if country else ""
        return (
            f"Imagen documental realista de una consulta profesional sobre {topic}{place}, "
            "oficina moderna, ambiente confidencial y tranquilo, interacción humana natural, "
            "sin clichés policiales, sin interrogatorio agresivo, sin cables exagerados."
        )

    return (
        f"Realistic documentary-style image about {topic}, modern office, confidential professional atmosphere, "
        "natural human interaction, no police clichés, no aggressive interrogation, no exaggerated wires."
    )


def enrich_image_plan_metadata(
    image_plan: Dict[str, Any],
    *,
    language: str,
    country: str,
    topic: str,
    page_slug: Optional[str] = None
) -> Dict[str, Any]:
    featured = image_plan.setdefault("featured_image", {})

    filename_base = slugify_filename_base(page_slug or topic)

    metadata = build_image_metadata(
        workspace_id=featured.get("workspace_id", ""),
        language=language,
        topic=topic,
        category=featured.get("category", "default"),
        placement="featured",
        page_type=featured.get("page_type", ""),
        fallback_country=country,
        professional_context="entrevista previa",
        filename_base=filename_base
    )

    # Preserve original asset filename and create SEO-friendly output filename
    original_filename = featured.get("filename", "")

    if original_filename:
        featured["source_filename"] = original_filename

    featured["recommended_filename"] = f"{filename_base}.webp"

    featured["alt_text"] = metadata.get("alt_text", featured.get("alt_text", ""))
    featured["title"] = metadata.get("title", featured.get("title", ""))
    featured["caption"] = metadata.get("caption", featured.get("caption", ""))
    featured["country_localized"] = metadata.get("country_localized", "")
    featured["metadata_strategy"] = metadata.get("metadata_strategy", "")

    if featured.get("source_type") == "future_generation" and not featured.get("prompt"):
        featured["prompt"] = build_ai_prompt_placeholder(language, topic, country)

    featured.setdefault("placement", "featured")
    featured.setdefault("format_preference", "webp")
    featured.setdefault("optimization_profile", "featured_image")
    featured.setdefault("social_reuse", True)

    image_plan.setdefault("in_article_images", [])

    return image_plan


def build_image_plan_for_draft(
    *,
    workspace_id: str,
    page_type: str,
    topic: str,
    language: str = "es",
    country: str = "España",
    page_slug: Optional[str] = None,
    category: Optional[str] = None
) -> Dict[str, Any]:
    category = category or infer_image_category(page_type, topic)

    selection = select_best_image(
        workspace_id=workspace_id,
        topic=topic,
        page_type=page_type,
        category=category,
        slot_id="featured_image"
    )

    if selection["decision"] == "reuse_existing_image":

        selected = selection["selected"]["candidate"]

        image_plan = {
            "featured_image": {
                **selected,
                "score": selection["selected"]["score"],
                "selection_reasons": selection["selected"]["reasons"],
                "workspace_id": workspace_id,
                "page_type": page_type
            },
            "in_article_images": []
        }

    else:

        image_plan = {
            "featured_image": {
                "source_type": "future_generation",
                "score": 0,
                "workspace_id": workspace_id,
                "page_type": page_type
            },
            "in_article_images": []
        }

    featured = image_plan.setdefault("featured_image", {})

    if "score" not in featured:
        featured["score"] = 100

    asset_score = int(featured.get("score", 100) or 0)

    if asset_score < IMAGE_SELECTION_THRESHOLD:
        featured = build_generation_candidate(
            workspace_id=workspace_id,
            topic=topic,
            language=language,
            country=country,
            page_type=page_type,
            category=featured.get("category", "professional_consultation"),
            placement="featured",
            filename_base=slugify_filename_base(page_slug or topic),
            reason=(
                f"No approved existing image asset reached threshold "
                f"{IMAGE_SELECTION_THRESHOLD}. Best score: {asset_score}."
            ),
        )
        image_plan["featured_image"] = featured

    image_plan = enrich_image_plan_metadata(
        image_plan,
        language=language,
        country=country,
        topic=topic,
        page_slug=page_slug
    )

    image_plan["planning_status"] = "phase_2_ai_generation"
    image_plan["generation_enabled"] = True
    image_plan["wordpress_upload_enabled"] = True
    image_plan["notes"] = [
        "AI image generation is enabled for featured images.",
        "Existing approved assets are fallback only when AI generation is not available."
    ]

    return image_plan


if __name__ == "__main__":
    plan = build_image_plan_for_draft(
        workspace_id="local.es",
        page_type="service_page",
        topic="prueba de polígrafo para infidelidad",
        language="es",
        country="España",
        page_slug="prueba-poligrafo-infidelidad-espana"
    )

    print(json.dumps(plan, ensure_ascii=False, indent=2))
