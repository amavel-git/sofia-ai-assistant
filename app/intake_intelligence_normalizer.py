"""
Deterministic Sofia intake intelligence normalizer.

Purpose:
- Clean examiner-originated opportunity text before it becomes intake.
- Prevent command text such as "Sofía, crea..." from becoming titles.
- Produce clean issue, sector, title, H1, focus keyphrase, slug and topic family.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict


COMMAND_PATTERNS = [
    r"\bsof[ií]a\b[,:\s-]*",
    r"\bcrea(?:r)?\s+(?:una\s+)?p[aá]gina\s+(?:para\s+empresas\s+)?(?:sobre\s+)?",
    r"\bhaz(?:me)?\s+(?:una\s+)?p[aá]gina\s+(?:sobre\s+)?",
    r"\bgenera(?:r)?\s+(?:una\s+)?p[aá]gina\s+(?:sobre\s+)?",
    r"\bescribe(?:me)?\s+(?:una\s+)?p[aá]gina\s+(?:sobre\s+)?",
    r"\bseo\s+sobre\s+",
]


COUNTRY_TERMS = {
    "es": ("España", "espana", "spain"),
    "pt": ("Portugal", "portugal"),
    "br": ("Brasil", "brasil", "brazil"),
    "ao": ("Angola", "angola"),
    "fr": ("France", "Francia", "france", "francia"),
    "be": ("Belgique", "Bélgica", "belgica", "belgium"),
    "tr": ("Türkiye", "Turquía", "turquia", "turkey"),
    "in": ("India", "india"),
}


TOPIC_FAMILIES = [
    {
        "family": "workplace_drug_use",
        "issue": "consumo de drogas en empleados",
        "matches": [
            "consumo de drogas", "drogas", "sustancias", "estupefacientes",
            "empleados bajo efectos", "consumo laboral"
        ],
    },
    {
        "family": "fuel_fraud_transport",
        "issue": "fraude de combustible",
        "matches": [
            "combustible", "gasolina", "diesel", "diésel", "carburante",
            "transporte", "flota", "camiones"
        ],
    },
    {
        "family": "inventory_manipulation",
        "issue": "manipulación de inventario",
        "matches": [
            "inventario", "almacén", "almacen", "stock", "existencias",
            "mercancía", "mercancia"
        ],
    },
    {
        "family": "internal_theft",
        "issue": "robo interno",
        "matches": [
            "robo interno", "hurto", "sustracción", "sustraccion",
            "empleado robó", "empleado robo"
        ],
    },
    {
        "family": "infidelity",
        "issue": "infidelidad",
        "matches": [
            "infidelidad", "pareja", "relación", "relacion", "engaño sentimental"
        ],
    },
    {
        "family": "pre_employment",
        "issue": "evaluación de integridad prelaboral",
        "matches": [
            "pre empleo", "pre-empleo", "prelaboral", "contratación",
            "contratacion", "selección de personal", "seleccion de personal"
        ],
    },
]


SECTORS = [
    {
        "sector": "entidades financieras",
        "matches": [
            "entidades financieras", "empresa financiera", "empresas financieras",
            "banco", "bancos", "financiera", "sector financiero",
            "institución financiera", "institucion financiera"
        ],
    },
    {
        "sector": "empresas de transporte",
        "matches": ["transporte", "camiones", "flota", "logística", "logistica"],
    },
    {
        "sector": "almacenes logísticos",
        "matches": ["almacén", "almacen", "almacenes", "logística", "logistica"],
    },
    {
        "sector": "empresas",
        "matches": ["empresa", "empresas", "corporativo", "organización", "organizacion"],
    },
]


def strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", value or "")
        if unicodedata.category(ch) != "Mn"
    )


def norm(value: str) -> str:
    value = strip_accents(value or "").lower()
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def clean_examiner_command(text: str) -> str:
    cleaned = text or ""

    for pattern in COMMAND_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.I)

    cleaned = re.sub(r"^\s*(sobre|para|acerca de)\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;-")
    return cleaned


def slugify(text: str) -> str:
    text = norm(text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:80].strip("-")


def detect_country(workspace: Dict[str, Any], text: str) -> str:
    country_code = workspace.get("country_code", "")
    terms = COUNTRY_TERMS.get(country_code, ())
    if terms:
        return terms[0]

    haystack = norm(text)
    for values in COUNTRY_TERMS.values():
        for value in values:
            if norm(value) in haystack:
                return values[0]

    return workspace.get("country") or ""


def detect_topic_family(text: str) -> Dict[str, str]:
    haystack = norm(text)

    best = {"family": "general_polygraph_service", "issue": ""}
    best_score = 0

    for item in TOPIC_FAMILIES:
        score = 0
        for term in item["matches"]:
            if norm(term) in haystack:
                score += 1
        if score > best_score:
            best_score = score
            best = {"family": item["family"], "issue": item["issue"]}

    return best


def detect_sector(text: str) -> str:
    haystack = norm(text)

    best_sector = ""
    best_score = 0

    for item in SECTORS:
        score = 0
        for term in item["matches"]:
            if norm(term) in haystack:
                score += 1
        if score > best_score:
            best_score = score
            best_sector = item["sector"]

    return best_sector


def build_clean_fields(raw_text: str, workspace: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = clean_examiner_command(raw_text)
    family = detect_topic_family(cleaned)
    sector = detect_sector(cleaned)
    country = detect_country(workspace, cleaned)

    issue = family.get("issue") or cleaned

    if issue and sector:
        normalized_title = f"Investigación de {issue} en {sector}"
    elif issue:
        normalized_title = f"Investigación de {issue}"
    else:
        normalized_title = cleaned

    if country and country.lower() not in normalized_title.lower():
        page_h1 = f"{normalized_title} en {country}"
    else:
        page_h1 = normalized_title

    key_parts = []
    if issue:
        key_parts.append(issue)
    if sector:
        key_parts.append(sector)

    focus_keyphrase = " ".join(key_parts) or cleaned
    suggested_slug = slugify(focus_keyphrase)

    return {
        "raw_opportunity_text": raw_text,
        "cleaned_request": cleaned,
        "normalized_title": normalized_title,
        "page_h1": page_h1,
        "issue": issue,
        "sector": sector,
        "country_localized": country,
        "focus_keyphrase": focus_keyphrase,
        "suggested_slug": suggested_slug,
        "topic_family": family.get("family"),
        "visual_topic_family": family.get("family"),
        "normalization_confidence": "high" if family.get("family") != "general_polygraph_service" else "medium",
        "normalization_source": "deterministic_intake_intelligence_v1",
    }


def normalize_opportunity_for_intake(opportunity: Dict[str, Any], workspace: Dict[str, Any]) -> Dict[str, Any]:
    seo_brief = opportunity.get("seo_brief", {}) or {}

    raw_text = (
        opportunity.get("localized_topic")
        or opportunity.get("topic_label")
        or opportunity.get("workspace_language_topic")
        or opportunity.get("raw_signal")
        or opportunity.get("title")
        or opportunity.get("topic")
        or seo_brief.get("page_title")
        or ""
    )

    return build_clean_fields(raw_text, workspace)
