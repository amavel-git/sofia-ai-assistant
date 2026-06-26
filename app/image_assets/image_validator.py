#!/usr/bin/env python3
"""
Sofia Image Asset Validator

Phase 1 validator for image_plan metadata.
Mostly warns; only clearly unsafe visual claims are treated as errors.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List


ALLOWED_PLACEMENTS = {
    "featured",
    "before_faq",
    "before_cta",
    "after_h2",
    "process_section",
    "cta_section",
    "social",
    "in_article"
}

PREFERRED_FORMATS = {"webp", "jpg", "jpeg", "avif"}

RISKY_TERMS = [
    "100% accurate",
    "guaranteed",
    "guarantee",
    "proves the truth",
    "detects lies",
    "lie detector proves",
    "police certified",
    "official police",
    "handcuffs",
    "interrogation room",
    "aggressive interrogation",
    "criminal suspect",
    "confession",
    "truth machine"
]


def is_slug_like_filename(filename: str) -> bool:
    if not filename:
        return False

    name = filename.rsplit(".", 1)[0]
    return bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name))


def get_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower().strip()


def validate_image_item(item: Dict[str, Any], label: str) -> Dict[str, List[str]]:
    warnings = []
    errors = []

    source_type = item.get("source_type", "")
    placement = item.get("placement", "")
    recommended_filename = item.get("recommended_filename") or item.get("filename", "")
    alt_text = item.get("alt_text", "")
    caption = item.get("caption", "")
    prompt = item.get("prompt", "")

    if not source_type:
        warnings.append(f"{label}: missing source_type.")

    if placement and placement not in ALLOWED_PLACEMENTS:
        warnings.append(f"{label}: unknown placement '{placement}'.")

    if not recommended_filename:
        warnings.append(f"{label}: missing recommended filename.")
    else:
        ext = get_extension(recommended_filename)
        if ext not in PREFERRED_FORMATS:
            warnings.append(f"{label}: image format '.{ext}' is not preferred. Prefer WebP for website images.")
        if not is_slug_like_filename(recommended_filename):
            warnings.append(f"{label}: filename is not SEO-friendly slug format.")

    if not alt_text:
        warnings.append(f"{label}: missing alt text.")
    elif len(alt_text) > 160:
        warnings.append(f"{label}: alt text is longer than 160 characters.")

    if not caption:
        warnings.append(f"{label}: missing caption.")

    searchable = f"{alt_text} {caption} {prompt}".lower()

    for term in RISKY_TERMS:
        if term.lower() in searchable:
            errors.append(f"{label}: risky image wording detected: '{term}'.")

    if source_type == "future_generation" and not prompt:
        warnings.append(f"{label}: future_generation image has no prompt.")

    return {
        "warnings": warnings,
        "errors": errors
    }


def validate_image_plan(image_plan: Dict[str, Any]) -> Dict[str, Any]:
    warnings = []
    errors = []

    if not isinstance(image_plan, dict) or not image_plan:
        return {
            "valid": True,
            "warnings": ["image_plan missing or empty."],
            "errors": []
        }

    featured = image_plan.get("featured_image") or {}

    if featured:
        result = validate_image_item(featured, "featured_image")
        warnings.extend(result["warnings"])
        errors.extend(result["errors"])
    else:
        warnings.append("featured_image missing from image_plan.")

    in_article_images = image_plan.get("in_article_images") or []

    if not isinstance(in_article_images, list):
        warnings.append("in_article_images must be a list.")
    else:
        if len(in_article_images) > 3:
            warnings.append("More than 3 in-article images planned. Check for image stuffing.")

        for index, item in enumerate(in_article_images, start=1):
            if not isinstance(item, dict):
                warnings.append(f"in_article_images[{index}] is not an object.")
                continue

            result = validate_image_item(item, f"in_article_images[{index}]")
            warnings.extend(result["warnings"])
            errors.extend(result["errors"])

    return {
        "valid": len(errors) == 0,
        "warnings": warnings,
        "errors": errors
    }


if __name__ == "__main__":
    sample = {
        "featured_image": {
            "source_type": "existing_asset",
            "asset_id": "IMG-GLOBAL-0001",
            "source_filename": "Interview.jpg",
            "recommended_filename": "prueba-poligrafo-infidelidad-espana.webp",
            "alt_text": "Imagen profesional relacionada con prueba de polígrafo para infidelidad en España",
            "caption": "Una imagen profesional para contextualizar prueba de polígrafo para infidelidad.",
            "placement": "featured",
            "format_preference": "webp"
        },
        "in_article_images": []
    }

    print(json.dumps(validate_image_plan(sample), ensure_ascii=False, indent=2))
