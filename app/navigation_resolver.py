#!/usr/bin/env python3
"""
Sofia Navigation Resolver

Phase 4.2B

Resolves semantic navigation targets from page_plan["navigation_plan"]
into real workspace URLs using site_structure.json through site_graph.py.

Language-agnostic:
- no localized anchors
- no CTA wording
- no country-specific text
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from site_graph import build_site_graph


NAVIGATION_RESOLVER_VERSION = "1.0"


TARGET_GROUP_MAP = {
    "related_service": "service_pages",
    "methodology": "methodology_pages",
    "authority": "authority_pages",
    "faq": "faq_pages",
    "pricing": "pricing_pages",
    "city_page": "city_pages",
    "contact": "contact_pages",
    "about": "about_pages",
    "pillar": "pillar_pages",
    "supporting_article": "educational_pages",
    "semantic_cluster": "service_pages",
}


def normalize_text(value: str) -> str:
    value = str(value or "").lower()
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
        value = value.replace(old, new)
    return " ".join(value.split())


def page_score(page: Dict[str, Any], context_text: str) -> int:
    haystack = normalize_text(" ".join([
        page.get("slug", ""),
        page.get("topic", ""),
        page.get("title", ""),
        page.get("h1", ""),
        page.get("section", ""),
        page.get("page_type", ""),
    ]))

    context = normalize_text(context_text)

    score = 0

    for token in context.split():
        if len(token) >= 4 and token in haystack:
            score += 1

    topic = normalize_text(page.get("topic", ""))

    if topic and topic in context:
        score += 8

    if page.get("section") in ("tag", "category", "spice_post_slider"):
        score -= 20

    if page.get("url", "").rstrip("/").endswith("/"):
        score += 1

    return score


def get_graph_group(graph: Dict[str, Any], semantic_target: str) -> List[Dict[str, Any]]:
    group_name = TARGET_GROUP_MAP.get(semantic_target)

    if not group_name:
        return []

    if group_name in graph:
        return graph.get(group_name, [])

    return []


def resolve_best_page(
    graph: Dict[str, Any],
    semantic_target: Optional[str],
    context_text: str,
    used_urls: set,
) -> Optional[Dict[str, Any]]:
    if not semantic_target:
        return None

    candidates = get_graph_group(graph, semantic_target)

    if semantic_target == "contact":
        candidates = [
            page for page in graph.get("pages", [])
            if "contact" in normalize_text(page.get("slug", ""))
            or "contact" in normalize_text(page.get("title", ""))
            or "contacto" in normalize_text(page.get("slug", ""))
            or "contacto" in normalize_text(page.get("title", ""))
        ]

    if semantic_target == "about":
        candidates = [
            page for page in graph.get("pages", [])
            if page.get("section") == "quienes-somos"
            or "quienes" in normalize_text(page.get("slug", ""))
            or "profesionales" in normalize_text(page.get("slug", ""))
        ]

    if semantic_target == "pillar":
        candidates = [
            page for page in graph.get("pages", [])
            if page.get("page_type") in ("content_page", "info_page")
            and page.get("section") == "top_level"
        ]

    candidates = [
        page for page in candidates
        if page.get("url") and page.get("url") not in used_urls
    ]

    if not candidates:
        return None

    ranked = sorted(
        candidates,
        key=lambda page: page_score(page, context_text),
        reverse=True,
    )

    best = ranked[0]

    if page_score(best, context_text) < -5:
        return None

    return best


def resolve_navigation_plan(
    page_plan: Dict[str, Any],
    site_structure: Dict[str, Any],
) -> Dict[str, Any]:
    graph = build_site_graph(site_structure)

    navigation_plan = page_plan.get("navigation_plan") or {}
    section_intelligence = page_plan.get("section_intelligence") or {}

    context_text = " ".join([
        page_plan.get("title", ""),
        page_plan.get("target_keyword", ""),
        page_plan.get("topic_key", ""),
        page_plan.get("topic_label", ""),
        (page_plan.get("topic_intelligence_profile") or {}).get("topic_family", ""),
    ])

    used_urls = set()

    resolved = {
        "version": NAVIGATION_RESOLVER_VERSION,
        "source_navigation_version": navigation_plan.get("version", ""),
        "resolved": True,
        "sections": {},
    }

    for section_id, item in (navigation_plan.get("sections") or {}).items():
        goal = item.get("navigation_goal") or {}
        section_semantics = section_intelligence.get(section_id) or {}

        max_links = int(goal.get("max_links") or 0)
        semantic_targets = [
            goal.get("primary_target"),
            goal.get("secondary_target"),
        ]

        links = []

        for semantic_target in semantic_targets:
            if not semantic_target:
                continue

            if len(links) >= max_links:
                break

            page = resolve_best_page(
                graph=graph,
                semantic_target=semantic_target,
                context_text=" ".join([
                    context_text,
                    section_id,
                    item.get("section_type", ""),
                    section_semantics.get("internal_link_intent", ""),
                    section_semantics.get("writing_objective", ""),
                ]),
                used_urls=used_urls,
            )

            if not page:
                continue

            used_urls.add(page.get("url"))

            links.append({
                "semantic_target": semantic_target,
                "url": page.get("url", ""),
                "slug": page.get("slug", ""),
                "page_type": page.get("page_type", ""),
                "topic": page.get("topic", ""),
                "title": page.get("title", ""),
                "h1": page.get("h1", ""),
                "section": page.get("section", ""),
                "anchor_source": "resolver_candidate_title_or_h1",
            })

        resolved["sections"][section_id] = {
            "section_type": item.get("section_type", ""),
            "navigation_goal": goal,
            "section_intent": {
                "internal_link_intent": section_semantics.get("internal_link_intent", ""),
                "conversion_stage": section_semantics.get("conversion_stage", ""),
                "visitor_state": section_semantics.get("visitor_state", ""),
            },
            "resolved_links": links,
            "resolved": bool(links),
        }

    return resolved


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    print(
        "Navigation Resolver Module\n"
        "Import resolve_navigation_plan(page_plan, site_structure)."
    )
