#!/usr/bin/env python3
"""
Sofia Image Metadata Generator

Language/workspace-agnostic metadata generation.

This module contains logic only.
Language-specific wording belongs in:
- data/image_assets/image_metadata_templates.json
- data/image_assets/country_localization.json
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Dict, Optional


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data" / "image_assets"

TEMPLATES_PATH = DATA_DIR / "image_metadata_templates.json"
COUNTRY_LOCALIZATION_PATH = DATA_DIR / "country_localization.json"


def load_json(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if default is None:
        default = {}

    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_language(language: str) -> str:
    language = str(language or "").lower().strip()

    aliases = {
        "spanish": "es",
        "español": "es",
        "espanol": "es",
        "castellano": "es",
        "es-es": "es",
        "portuguese": "pt",
        "português": "pt",
        "portugues": "pt",
        "pt-pt": "pt",
        "pt-br": "pt",
        "french": "fr",
        "français": "fr",
        "francais": "fr",
        "fr-fr": "fr",
        "english": "en",
        "en-us": "en",
        "en-gb": "en",
    }

    if language in aliases:
        return aliases[language]

    if "-" in language:
        return language.split("-", 1)[0]

    return language or "en"


def infer_workspace_country_code(workspace_id: str, fallback: str = "") -> str:
    workspace_id = str(workspace_id or "").strip().lower()

    if "." in workspace_id:
        return workspace_id.split(".")[-1].upper()

    return str(fallback or "").upper()


def localize_country(
    *,
    workspace_id: str,
    language: str,
    country_code: Optional[str] = None,
    fallback_country: str = ""
) -> str:
    language = normalize_language(language)
    country_code = (country_code or infer_workspace_country_code(workspace_id)).upper()

    country_data = load_json(COUNTRY_LOCALIZATION_PATH, {})
    localized = (
        country_data.get(language, {}).get(country_code)
        or country_data.get("en", {}).get(country_code)
        or fallback_country
        or country_code
    )

    return localized


def stable_template_choice(options: list, seed: str) -> str:
    """
    Deterministic template selection so metadata is stable across repeated runs.
    """
    options = [str(item) for item in options if str(item).strip()]

    if not options:
        return ""

    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % len(options)

    return options[index]


def get_template_group(
    *,
    language: str,
    category: str,
    placement: str = "featured"
) -> Dict[str, Any]:
    language = normalize_language(language)
    category = str(category or "default").lower().strip()
    placement = str(placement or "featured").lower().strip()

    templates = load_json(TEMPLATES_PATH, {})

    lang_templates = templates.get(language) or templates.get("en") or {}
    default_group = lang_templates.get("default", {})
    category_group = lang_templates.get(category, {})

    # Optional placement override.
    placement_group = category_group.get("placements", {}).get(placement, {})

    result = dict(default_group)
    result.update(category_group)
    result.update(placement_group)

    return result


def clean_text(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def render_template(template: str, variables: Dict[str, str]) -> str:
    rendered = str(template or "")

    for key, value in variables.items():
        rendered = rendered.replace("{" + key + "}", str(value or ""))

    return clean_text(rendered)


def truncate_alt_text(text: str, max_length: int = 160) -> str:
    text = clean_text(text)

    if len(text) <= max_length:
        return text

    truncated = text[:max_length].rsplit(" ", 1)[0].strip()
    return truncated or text[:max_length].strip()


def build_image_metadata(
    *,
    workspace_id: str,
    language: str,
    topic: str,
    category: str = "default",
    placement: str = "featured",
    page_type: str = "",
    country_code: Optional[str] = None,
    fallback_country: str = "",
    professional_context: str = "",
    filename_base: str = ""
) -> Dict[str, str]:
    """
    Build localized image metadata using JSON templates.

    No language-specific text should be hardcoded here.
    """
    language = normalize_language(language)

    country = localize_country(
        workspace_id=workspace_id,
        language=language,
        country_code=country_code,
        fallback_country=fallback_country
    )

    topic = clean_text(topic)
    category = clean_text(category).lower() or "default"
    placement = clean_text(placement).lower() or "featured"
    page_type = clean_text(page_type)
    professional_context = clean_text(professional_context)

    template_group = get_template_group(
        language=language,
        category=category,
        placement=placement
    )

    seed = "|".join([
        workspace_id,
        language,
        topic,
        category,
        placement,
        page_type,
        professional_context,
        filename_base,
    ])

    variables = {
        "topic": topic,
        "country": country,
        "category": category,
        "placement": placement,
        "page_type": page_type,
        "professional_context": professional_context,
        "filename_base": filename_base,
    }

    alt_template = stable_template_choice(
        template_group.get("alt_templates", []),
        seed + "|alt"
    )
    title_template = stable_template_choice(
        template_group.get("title_templates", []),
        seed + "|title"
    )
    description_template = stable_template_choice(
        template_group.get("description_templates", [])
        or template_group.get("caption_templates", []),
        seed + "|description"
    )

    alt_text = render_template(alt_template, variables)
    title = render_template(title_template, variables)
    description = render_template(description_template, variables)

    if not alt_text:
        alt_text = render_template("{professional_context} {topic} {country}", variables)

    if not title:
        title = render_template("{topic} {country}", variables)

    if not description:
        description = render_template("{topic}", variables)

    # Captions are intentionally empty by default.
    # Use description for WordPress media description to avoid visible text below images.
    caption = ""

    return {
        "alt_text": truncate_alt_text(alt_text),
        "title": title,
        "description": description,
        "caption": caption,
        "country_localized": country,
        "language": language,
        "category": category,
        "placement": placement,
        "professional_context": professional_context,
        "metadata_strategy": "template_deterministic_v1"
    }


if __name__ == "__main__":
    sample = build_image_metadata(
        workspace_id="local.es",
        language="es-ES",
        topic="metodología del polígrafo",
        category="interview",
        placement="featured",
        page_type="educational_page",
        fallback_country="Spain",
        professional_context="entrevista previa"
    )

    print(json.dumps(sample, ensure_ascii=False, indent=2))
