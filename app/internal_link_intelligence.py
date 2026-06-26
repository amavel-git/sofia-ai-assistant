#!/usr/bin/env python3
"""
Sofia Internal Link Intelligence

Additive helper module.
No AI calls.
No WordPress calls.
No workflow side effects.

Purpose:
- Read workspace/global structure files safely.
- Build deterministic internal link suggestions.
- Prefer semantic anchors over generic service-list text.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
SITES_DIR = ROOT / "sites" / "local_sites"
DATA_DIR = ROOT / "data"


DEFAULT_TOPIC_ANCHORS: Dict[str, List[str]] = {
    "corporate_investigation": [
        "investigaciones corporativas",
        "prueba de polígrafo para empresas",
        "servicios para empresas",
    ],
    "employee_theft": [
        "polígrafo por robo interno",
        "investigación de hurto en empresas",
        "prueba de polígrafo laboral",
    ],
    "infidelity": [
        "prueba de polígrafo por infidelidad",
        "test de fidelidad",
        "consulta confidencial de pareja",
    ],
    "legal": [
        "prueba de polígrafo para abogados",
        "polígrafo en contexto legal",
        "evaluación poligráfica privada",
    ],
    "city_page": [
        "prueba de polígrafo en la ciudad",
        "polígrafo local confidencial",
        "consultar disponibilidad",
    ],
    "contact": [
        "solicitar una prueba de polígrafo",
        "contacto confidencial",
        "consultar mi caso",
    ],
}


TOPIC_KEYWORDS: Dict[str, List[str]] = {
    "corporate_investigation": [
        "empresa", "empresas", "corporativ", "laboral", "rrhh", "recursos-humanos",
        "investigacion-interna", "investigaciones", "empleados"
    ],
    "employee_theft": [
        "robo", "hurto", "sustraccion", "interno", "empleado", "empresa",
        "combustible", "inventario", "fraude"
    ],
    "infidelity": [
        "infidelidad", "pareja", "fidelidad", "matrimonial", "relacion"
    ],
    "legal": [
        "legal", "abogado", "abogados", "judicial", "pericial", "tribunal"
    ],
    "contact": [
        "contacto", "solicitar", "consulta", "cita"
    ],
    "city_page": [
        "madrid", "barcelona", "valencia", "sevilla", "zaragoza", "malaga",
        "cordoba", "granada", "toledo", "alicante", "bilbao"
    ],
}


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _workspace_dir(workspace_id: str) -> Path:
    """
    Resolve Sofia workspace folder safely.

    Supports both:
    - local.ao -> sites/local_sites/ao
    - ao       -> sites/local_sites/ao
    - local.es -> sites/local_sites/es
    """
    workspace_id = str(workspace_id or "").strip()

    direct = SITES_DIR / workspace_id
    if direct.exists():
        return direct

    if workspace_id.startswith("local."):
        short_id = workspace_id.split(".", 1)[1]
        short_path = SITES_DIR / short_id
        if short_path.exists():
            return short_path

    return direct


def _normalize_url(url: str) -> str:
    url = str(url or "").strip()
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if not url.startswith("/"):
        url = "/" + url
    return url


def _humanize_from_url(url: str) -> str:
    last = _normalize_url(url).rstrip("/").split("/")[-1]
    label = last.replace("-", " ").replace("_", " ").strip()
    return label or "más información"


def _extract_site_structure_links(site_structure: Any) -> List[Dict[str, Any]]:
    links: List[Dict[str, Any]] = []

    def walk(node: Any):
        if isinstance(node, dict):
            url = node.get("url") or node.get("slug") or node.get("path")
            title = node.get("title") or node.get("label") or node.get("name") or node.get("h1")
            page_type = node.get("page_type") or node.get("type")

            if url:
                links.append({
                    "url": _normalize_url(url),
                    "title": title or _humanize_from_url(str(url)),
                    "page_type": page_type,
                    "source": "site_structure",
                    "raw": node,
                })

            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)

        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(site_structure)
    return links


def _extract_content_inventory_links(content_inventory: Any) -> List[Dict[str, Any]]:
    links: List[Dict[str, Any]] = []

    items = []
    if isinstance(content_inventory, dict):
        for key in ("pages", "items", "content", "drafts", "published"):
            if isinstance(content_inventory.get(key), list):
                items.extend(content_inventory.get(key, []))
        if not items:
            items = list(content_inventory.values())
    elif isinstance(content_inventory, list):
        items = content_inventory

    for item in items:
        if not isinstance(item, dict):
            continue

        status = str(item.get("status", "")).lower()
        if status and status not in {"published", "active", "live", "approved", "wordpress_draft"}:
            continue

        url = item.get("url") or item.get("slug") or item.get("path") or item.get("wordpress_link")
        if not url:
            continue

        links.append({
            "url": _normalize_url(url),
            "title": item.get("title") or item.get("seo_title") or item.get("h1") or _humanize_from_url(str(url)),
            "page_type": item.get("page_type") or item.get("type"),
            "source": "content_inventory",
            "raw": item,
        })

    return links


def _dedupe_links(links: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result = []
    for link in links:
        url = _normalize_url(link.get("url", ""))
        if not url or url in seen:
            continue
        seen.add(url)
        link["url"] = url
        result.append(link)
    return result


def _load_topic_anchors(workspace_id: str) -> Dict[str, List[str]]:
    workspace = _workspace_dir(workspace_id)
    language_profile = _load_json(workspace / "language_profile.json", {})
    page_presentation = _load_json(workspace / "page_presentation.json", {})
    page_blueprints = _load_json(DATA_DIR / "page_blueprints.json", {})

    anchors: Dict[str, List[str]] = dict(DEFAULT_TOPIC_ANCHORS)

    for source in (page_blueprints, page_presentation, language_profile):
        if not isinstance(source, dict):
            continue
        candidate = source.get("topic_anchor_labels")
        if isinstance(candidate, dict):
            for key, labels in candidate.items():
                if isinstance(labels, list):
                    anchors[str(key)] = [str(x).strip() for x in labels if str(x).strip()]

    return anchors


def _score_link(link: Dict[str, Any], topic_key: Optional[str], page_type: Optional[str]) -> float:
    haystack = " ".join([
        str(link.get("url", "")),
        str(link.get("title", "")),
        str(link.get("page_type", "")),
    ]).lower()

    score = 0.0

    if page_type and str(link.get("page_type", "")).lower() == page_type.lower():
        score += 2.0

    if topic_key:
        keywords = TOPIC_KEYWORDS.get(topic_key, [])
        for keyword in keywords:
            if keyword.lower() in haystack:
                score += 1.0

    if link.get("source") == "site_structure":
        score += 0.25

    if "contact" in haystack or "contacto" in haystack:
        if topic_key == "contact":
            score += 2.0
        else:
            score -= 0.25

    return score


def _select_anchor(
    link: Dict[str, Any],
    topic_key: Optional[str],
    topic_anchors: Dict[str, List[str]],
    used_anchors: set,
) -> str:
    preferred = topic_anchors.get(topic_key or "", [])

    for anchor in preferred:
        if anchor not in used_anchors:
            used_anchors.add(anchor)
            return anchor

    title = str(link.get("title") or "").strip()
    if title:
        anchor = title[:90]
    else:
        anchor = _humanize_from_url(link.get("url", ""))

    used_anchors.add(anchor)
    return anchor


def get_internal_link_suggestions(
    workspace_id: str,
    topic_key: Optional[str] = None,
    page_type: Optional[str] = None,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    """
    Return deterministic internal link suggestions.

    Output shape:
    [
      {
        "url": "/servicios/poligrafo-empresas",
        "anchor": "prueba de polígrafo para empresas",
        "reason": "Matched topic corporate_investigation",
        "source": "site_structure",
        "score": 3.25
      }
    ]
    """
    workspace = _workspace_dir(workspace_id)

    site_structure = _load_json(workspace / "site_structure.json", {})
    content_inventory = _load_json(workspace / "content_inventory.json", {})

    links = []
    links.extend(_extract_site_structure_links(site_structure))
    links.extend(_extract_content_inventory_links(content_inventory))
    links = _dedupe_links(links)

    topic_anchors = _load_topic_anchors(workspace_id)

    scored = []
    for link in links:
        score = _score_link(link, topic_key, page_type)
        if score <= 0 and topic_key:
            continue
        scored.append((score, link))

    scored.sort(key=lambda item: item[0], reverse=True)

    used_anchors = set()
    suggestions: List[Dict[str, Any]] = []

    for score, link in scored[: max(limit, 1)]:
        anchor = _select_anchor(link, topic_key, topic_anchors, used_anchors)
        suggestions.append({
            "url": link["url"],
            "anchor": anchor,
            "reason": f"Matched topic {topic_key}" if topic_key else "General internal link candidate",
            "source": link.get("source", "unknown"),
            "score": round(score, 3),
        })

    return suggestions


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview Sofia internal link suggestions.")
    parser.add_argument("workspace_id", help="Workspace ID, e.g. local.es")
    parser.add_argument("--topic", dest="topic_key", default=None, help="Topic key, e.g. corporate_investigation")
    parser.add_argument("--page-type", dest="page_type", default=None, help="Page type, e.g. city_page")
    parser.add_argument("--limit", type=int, default=6)
    args = parser.parse_args()

    suggestions = get_internal_link_suggestions(
        workspace_id=args.workspace_id,
        topic_key=args.topic_key,
        page_type=args.page_type,
        limit=args.limit,
    )

    print(json.dumps(suggestions, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
