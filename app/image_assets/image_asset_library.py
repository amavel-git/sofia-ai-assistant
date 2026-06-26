#!/usr/bin/env python3
"""
Sofia Image Asset Library

Selects the best approved existing image asset for a draft.

Public function:
- build_basic_image_plan(...)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List


ROOT_DIR = Path(__file__).resolve().parents[2]
LIBRARY_PATH = ROOT_DIR / "data" / "image_assets" / "global_image_asset_library.json"


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"assets": []}

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_text(text: str) -> str:
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

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def text_contains_any(text: str, terms: List[str]) -> bool:
    text = normalize_text(text)
    return any(normalize_text(term) in text for term in terms)


def infer_desired_image_categories(page_type: str, topic: str) -> List[str]:
    page_type_norm = normalize_text(page_type)
    topic_norm = normalize_text(topic)

    desired = []

    if "educational" in page_type_norm or "authority" in page_type_norm or "pillar" in page_type_norm:
        desired.extend(["methodology", "documents", "question_review", "charts", "training"])

    if text_contains_any(topic_norm, ["metodologia", "methodology", "procedimiento", "procedure", "preguntas", "questions"]):
        desired.extend(["methodology", "documents", "question_review", "charts"])

    if text_contains_any(topic_norm, ["infidelidad", "infidelity", "pareja", "relationship"]):
        desired.extend(["consultation", "interview", "confidential_consultation"])

    if text_contains_any(topic_norm, ["empresa", "corporate", "fraude", "robo", "theft", "empleado", "employee"]):
        desired.extend(["corporate", "meeting", "documents", "investigation"])

    if text_contains_any(topic_norm, ["formacion", "training", "curso", "seminar"]):
        desired.extend(["training", "seminar", "authority"])

    if not desired:
        desired.extend(["interview", "consultation", "professional_environment"])

    # Preserve order, remove duplicates.
    return list(dict.fromkeys(desired))


def score_asset(asset: Dict[str, Any], page_type: str, topic: str) -> int:
    page_type_norm = normalize_text(page_type)
    topic_norm = normalize_text(topic)

    score = 0

    status = str(asset.get("status", "approved")).lower()
    if status in ["approved", "selected", "active"]:
        score += 10
    else:
        score -= 100

    if asset.get("reuse_allowed", True) is False:
        score -= 100

    category = normalize_text(asset.get("category", ""))
    categories = [
        normalize_text(item)
        for item in asset.get("categories", [])
        if str(item).strip()
    ]

    topics = [
        normalize_text(item)
        for item in asset.get("topics", [])
        if str(item).strip()
    ]

    visual_context = normalize_text(asset.get("visual_context", ""))

    best_for = [
        normalize_text(item)
        for item in asset.get("best_for_page_types", [])
        if str(item).strip()
    ]

    avoid_for = [
        normalize_text(item)
        for item in asset.get("avoid_for_page_types", [])
        if str(item).strip()
    ]

    desired_categories = infer_desired_image_categories(page_type, topic)
    desired_norm = [normalize_text(item) for item in desired_categories]

    if page_type_norm in best_for:
        score += 30

    if page_type_norm in avoid_for:
        score -= 80

    if category in desired_norm:
        score += 30

    overlap = set(categories).intersection(set(desired_norm))
    score += min(len(overlap) * 15, 45)

    if visual_context in desired_norm:
        score += 20

    for item in topics:
        if item and item in topic_norm:
            score += 12

    # Specific boosts.
    if "methodology" in desired_norm:
        if category in ["methodology", "documents", "charts"]:
            score += 20
        if visual_context in ["question_review", "document_review", "chart_analysis"]:
            score += 20
        if category in ["interview", "consultation"] and "educational" in page_type_norm:
            score -= 15

    if "corporate" in desired_norm and category in ["corporate", "meeting", "investigation"]:
        score += 20

    if "training" in desired_norm and category in ["training", "seminar", "authority"]:
        score += 20

    return max(score, 0)


def select_best_asset(
    page_type: str,
    topic: str,
    exclude_asset_ids=None
) -> Dict[str, Any]:

    exclude_asset_ids = set(exclude_asset_ids or [])
    library = load_json(LIBRARY_PATH)
    assets = library.get("assets", [])

    scored = []

    for asset in assets:

        if asset.get("asset_id") in exclude_asset_ids:
            continue
        score = score_asset(asset, page_type=page_type, topic=topic)
        asset_copy = dict(asset)
        asset_copy["score"] = score
        scored.append(asset_copy)

    scored.sort(key=lambda item: item.get("score", 0), reverse=True)

    if scored:
        return scored[0]

    return {
        "asset_id": "",
        "filename": "",
        "category": "professional_consultation",
        "topics": [],
        "placement": "featured",
        "status": "missing",
        "score": 0,
    }


def build_basic_image_plan(
    page_type: str = "",
    topic: str = "",
    placement: str = "featured",
    **kwargs,
) -> Dict[str, Any]:
    """
    Build a basic image plan using the best approved existing asset.

    The planner may later replace this with an ai_generation_candidate
    if score is below IMAGE_SELECTION_THRESHOLD.
    """

    selected = select_best_asset(page_type=page_type, topic=topic)

    featured_image = {
        "source_type": "existing_asset",
        "asset_id": selected.get("asset_id", ""),
        "filename": selected.get("filename", ""),
        "category": selected.get("category", ""),
        "categories": selected.get("categories", []),
        "topics": selected.get("topics", []),
        "visual_context": selected.get("visual_context", ""),
        "best_for_page_types": selected.get("best_for_page_types", []),
        "avoid_for_page_types": selected.get("avoid_for_page_types", []),
        "placement": placement,
        "status": "selected" if selected.get("filename") else "missing",
        "score": selected.get("score", 0),
    }

    return {
        "featured_image": featured_image,
        "in_article_images": [],
    }


if __name__ == "__main__":
    print(json.dumps(
        build_basic_image_plan(
            page_type="educational_page",
            topic="metodología del polígrafo",
        ),
        ensure_ascii=False,
        indent=2
    ))
