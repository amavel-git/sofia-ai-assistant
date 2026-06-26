#!/usr/bin/env python3
"""
Sofia Image Selector

Decides whether Sofia should:
- reuse an existing global/original asset
- reuse a workspace image from image_metadata.json
- queue AI image generation

This is deterministic scoring only. No AI calls.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


from app.image_assets.image_asset_registry import load_image_metadata


GLOBAL_LIBRARY_PATH = ROOT_DIR / "data" / "image_assets" / "global_image_asset_library.json"


def load_json(path: Path, default=None):
    if default is None:
        default = {}
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_tokens(value: str) -> set[str]:
    value = str(value or "").lower()
    value = re.sub(r"[^a-záéíóúüñçàèìòùâêîôûãõ0-9]+", " ", value)
    return {token for token in value.split() if len(token) > 2}


def overlap_score(text_a: str, text_b: str) -> int:
    a = normalize_tokens(text_a)
    b = normalize_tokens(text_b)

    if not a or not b:
        return 0

    return len(a & b) * 10


def as_text_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    return []


def score_candidate(
    *,
    candidate: dict[str, Any],
    topic: str,
    page_type: str,
    category: str,
    slot_id: str,
    workspace_id: str,
    source_origin: str,
) -> dict[str, Any]:

    score = 0
    reasons = []

    searchable = " ".join([
        candidate.get("title", ""),
        candidate.get("alt_text", ""),
        candidate.get("description", ""),
        candidate.get("filename", ""),
        candidate.get("category", ""),
        " ".join(as_text_list(candidate.get("categories"))),
        " ".join(as_text_list(candidate.get("topics"))),
        " ".join(as_text_list(candidate.get("can_reuse_for"))),
        " ".join(as_text_list(candidate.get("best_for_page_types"))),
    ])

    topic_points = overlap_score(topic, searchable)
    if topic_points:
        score += topic_points
        reasons.append(f"topic overlap +{topic_points}")

    category_values = set(
        v.lower()
        for v in as_text_list(candidate.get("categories")) + [candidate.get("category", "")]
        if v
    )

    primary_category = str(candidate.get("category", "")).lower().strip()

    if category and category.lower() == primary_category:
        score += 55
        reasons.append("primary category exact match +55")

    elif category and category.lower() in category_values:
        score += 35
        reasons.append("category match +35")

    visual_context = str(candidate.get("visual_context", "")).lower().strip()

    if category and visual_context and category.lower() in visual_context:
        score += 20
        reasons.append("visual context category match +20")

    if topic and visual_context:
        visual_points = overlap_score(topic, visual_context)
        if visual_points:
            score += visual_points
            reasons.append(f"visual context topic overlap +{visual_points}")

    best_for = [v.lower() for v in as_text_list(candidate.get("best_for_page_types"))]
    if page_type and page_type.lower() in best_for:
        score += 30
        reasons.append("page type match +30")

    avoid_for = [v.lower() for v in as_text_list(candidate.get("avoid_for_page_types"))]
    if page_type and page_type.lower() in avoid_for:
        score -= 100
        reasons.append("avoid page type -100")

    if slot_id == "featured_image":
        score += 10
        reasons.append("featured-capable default +10")

    if source_origin == "workspace":
        if candidate.get("workspace_id") == workspace_id:
            score += 15
            reasons.append("same workspace +15")

        if candidate.get("status") in {"uploaded", "optimized", "registered"}:
            score += 10
            reasons.append("ready image status +10")

    if source_origin == "global":
        score += 5
        reasons.append("approved global asset +5")

    reuse_count = int(candidate.get("reuse_count") or 0)
    if reuse_count:
        score -= min(reuse_count * 5, 30)
        reasons.append(f"reuse penalty -{min(reuse_count * 5, 30)}")

    return {
        "candidate": candidate,
        "score": score,
        "reasons": reasons,
        "source_origin": source_origin,
    }


def collect_global_candidates() -> list[dict[str, Any]]:
    data = load_json(GLOBAL_LIBRARY_PATH, {})
    assets = data.get("assets") or []

    candidates = []

    for asset in assets:
        asset = dict(asset)
        asset["source_origin"] = "global"
        candidates.append(asset)

    return candidates


def collect_workspace_candidates(workspace_id: str) -> list[dict[str, Any]]:
    data = load_image_metadata(workspace_id)
    images = data.get("images") or {}

    candidates = []

    for image_id, image in images.items():
        image = dict(image)
        image["image_id"] = image_id
        image["source_origin"] = "workspace"
        candidates.append(image)

    return candidates


def select_best_image(
    *,
    workspace_id: str,
    topic: str,
    page_type: str = "",
    category: str = "",
    slot_id: str = "featured_image",
    minimum_score: int = 80,
) -> dict[str, Any]:

    scored = []

    for candidate in collect_global_candidates():
        scored.append(score_candidate(
            candidate=candidate,
            topic=topic,
            page_type=page_type,
            category=category,
            slot_id=slot_id,
            workspace_id=workspace_id,
            source_origin="global",
        ))

    for candidate in collect_workspace_candidates(workspace_id):
        scored.append(score_candidate(
            candidate=candidate,
            topic=topic,
            page_type=page_type,
            category=category,
            slot_id=slot_id,
            workspace_id=workspace_id,
            source_origin="workspace",
        ))

    scored.sort(key=lambda item: item["score"], reverse=True)

    best = scored[0] if scored else None

    if best and best["score"] >= minimum_score:
        return {
            "decision": "reuse_existing_image",
            "selected": best,
            "minimum_score": minimum_score,
            "candidate_count": len(scored),
            "top_candidates": scored[:5],
        }

    return {
        "decision": "queue_ai_generation",
        "selected": best,
        "minimum_score": minimum_score,
        "candidate_count": len(scored),
        "top_candidates": scored[:5],
        "reason": "No existing image reached the minimum selection score.",
    }


def main():
    if len(sys.argv) < 3:
        print(
            "Usage:\n"
            "python -m app.image_assets.image_selector WORKSPACE_ID TOPIC "
            "[PAGE_TYPE] [CATEGORY] [SLOT_ID]"
        )
        sys.exit(1)

    workspace_id = sys.argv[1]
    topic = sys.argv[2]
    page_type = sys.argv[3] if len(sys.argv) > 3 else ""
    category = sys.argv[4] if len(sys.argv) > 4 else ""
    slot_id = sys.argv[5] if len(sys.argv) > 5 else "featured_image"

    result = select_best_image(
        workspace_id=workspace_id,
        topic=topic,
        page_type=page_type,
        category=category,
        slot_id=slot_id,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
