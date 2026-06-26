"""
Sofia Visual Intelligence Layer.

Adds issue-oriented image roles, prompts, negative prompts and metadata.
This keeps image generation from defaulting every page to generic office scenes.
"""

from __future__ import annotations

import json
from pathlib import Path

import re
from typing import Any, Dict


NO_TEXT_NEGATIVE_PROMPT = (
    "text, letters, words, captions, typography, signs, labels, watermark, logo, "
    "readable documents, printed text, UI text, distorted text, gibberish text, "
    "fake writing, brand names, license plates, readable numbers"
)




ROOT_DIR = Path(__file__).resolve().parents[2]


def load_workspace_image_guidelines(workspace_id: str) -> Dict[str, Any]:
    """
    Load workspace-specific image guidance.
    Structural fallback remains in this module, but workspace profile wins.
    """
    mapping = {
        "local.es": "sites/local_sites/es",
        "local.pt": "sites/local_sites/pt",
        "local.br": "sites/local_sites/br",
        "local.fr": "sites/local_sites/fr",
        "local.be": "sites/local_sites/be",
        "local.tr": "sites/local_sites/tr",
        "local.in": "sites/local_sites/in",
        "local.ao": "sites/local_sites/ao",
        "local.co": "sites/local_sites/co",
        "local.ae": "sites/local_sites/ae",
    }

    rel = mapping.get(str(workspace_id or "").strip())
    if not rel:
        return {}

    path = ROOT_DIR / rel / "image_guidelines.json"
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_profile_visual_scenario(
    *,
    workspace_id: str,
    topic_family: str,
    role: str,
    topic: str = "",
) -> str:
    guidelines = load_workspace_image_guidelines(workspace_id)
    topic_mapping = guidelines.get("topic_mapping") or {}

    family = topic_mapping.get(topic_family) or {}

    # Fallback: match by configured terms if exact topic_family is unavailable.
    if not family:
        normalized_topic = normalize_text(topic)
        for candidate in topic_mapping.values():
            terms = candidate.get("match_terms") or []
            if any(normalize_text(term) in normalized_topic for term in terms):
                family = candidate
                break

    scenarios = family.get("visual_scenarios") or {}
    candidates = scenarios.get(role) or []

    if isinstance(candidates, list) and candidates:
        return str(candidates[0]).strip()

    return ""



def normalize_text(value: str) -> str:
    value = str(value or "").lower()
    value = re.sub(r"\s+", " ", value).strip()
    return value


def detect_visual_topic_family(text: str) -> str:
    haystack = normalize_text(text)

    if any(term in haystack for term in [
        "combustible", "fuel", "gasolina", "diésel", "diesel", "transporte",
        "flota", "camión", "camion", "cisterna"
    ]):
        return "fuel_fraud_transport"

    if any(term in haystack for term in [
        "inventario", "almacén", "almacen", "stock", "mercancía", "mercancia",
        "warehouse", "logístico", "logistico"
    ]):
        return "inventory_manipulation"

    if any(term in haystack for term in [
        "infidelidad", "pareja", "relación", "relacion", "conyugal"
    ]):
        return "infidelity"

    if any(term in haystack for term in [
        "pre-empleo", "pre empleo", "selección", "seleccion", "contratación",
        "contratacion", "integridad"
    ]):
        return "pre_employment_integrity"

    return "general_polygraph_service"


def infer_image_role(slot_id: str, topic_family: str) -> str:
    slot_id = str(slot_id or "").lower()

    if slot_id == "featured_image":
        if topic_family in {"fuel_fraud_transport", "inventory_manipulation"}:
            return "problem_scene"
        return "consultation_scene"

    if "in_article_1" in slot_id:
        return "investigation_scene"

    if "in_article_2" in slot_id:
        return "analysis_scene"

    if "in_article_3" in slot_id:
        return "consultation_scene"

    return "supporting_scene"


def build_visual_prompt(topic: str, page_type: str, country: str, role: str, topic_family: str, workspace_id: str = "") -> str:
    profile_scenario = get_profile_visual_scenario(
        workspace_id=workspace_id,
        topic_family=topic_family,
        role=role,
        topic=topic,
    )

    scenario = profile_scenario or topic
    country = country or "the target country"

    role_prompts = {
        "problem_scene": (
            f"Realistic documentary-style scene representing the concrete investigated problem: {scenario}."
        ),
        "investigation_scene": (
            f"Realistic professional scene showing the internal review or investigation context: {scenario}."
        ),
        "analysis_scene": (
            f"Realistic professional scene showing document review, records analysis, or question preparation: {scenario}."
        ),
        "consultation_scene": (
            f"Realistic professional consultation scene related to: {scenario}."
        ),
        "supporting_scene": (
            f"Realistic professional supporting image related to: {scenario}."
        ),
    }

    base = role_prompts.get(role, role_prompts["supporting_scene"])

    safeguards = (
        f" Page type: {page_type}. Local context: {country}. "
        "Professional, calm, ethical, confidential atmosphere. Natural lighting. "
        "No police interrogation clichés. No aggressive suspect imagery. "
        "No exaggerated wires. No unrealistic lie detector machine. "
        "No authority badges. No visual implication of guaranteed results. "
        "No visible text. No readable words. No typography. No signs. "
        "No labels. No logos. No watermarks. Documents may appear but must be blank or unreadable."
    )

    return base + safeguards


def build_visual_metadata(topic: str, country: str, role: str, topic_family: str) -> Dict[str, str]:
    country = country or "España"

    # Human editorial metadata.
    # Titles should sound like media-library titles, not raw keywords.
    # Alt text should describe the visual subject and page context.
    # Captions remain intentionally empty by default.

    if topic_family == "fuel_fraud_transport":
        if role == "problem_scene":
            return {
                "alt_text": "Posible sustracción de combustible en una empresa de transporte",
                "title": "Sospecha de fraude de combustible en transporte",
                "description": (
                    f"Imagen profesional utilizada como apoyo visual en una página sobre investigaciones "
                    f"de fraude o desvío de combustible en empresas de transporte en {country}."
                ),
                "caption": "",
            }

        if role == "investigation_scene":
            return {
                "alt_text": "Revisión de información durante una investigación interna por fraude de combustible",
                "title": "Revisión interna de un caso de fraude de combustible",
                "description": (
                    f"Imagen profesional utilizada como apoyo visual para representar la revisión de registros, "
                    f"consumos y documentación en una investigación interna relacionada con fraude de combustible "
                    f"en {country}."
                ),
                "caption": "",
            }

        if role == "analysis_scene":
            return {
                "alt_text": "Análisis documental en una investigación relacionada con fraude de combustible",
                "title": "Análisis documental de un caso de fraude de combustible",
                "description": (
                    f"Imagen profesional utilizada como apoyo visual para representar el análisis de documentación, "
                    f"rutas, consumos y preparación de preguntas en una investigación de fraude de combustible "
                    f"en {country}."
                ),
                "caption": "",
            }

        return {
            "alt_text": "Consulta profesional relacionada con una investigación de fraude de combustible",
            "title": "Consulta profesional sobre fraude de combustible",
            "description": (
                f"Imagen profesional utilizada como apoyo visual para representar una consulta relacionada "
                f"con fraude de combustible en empresas de transporte en {country}."
            ),
            "caption": "",
        }

    if topic_family == "inventory_manipulation":
        if role == "problem_scene":
            return {
                "alt_text": "Discrepancias de inventario en un entorno logístico",
                "title": "Sospecha de manipulación de inventario",
                "description": (
                    f"Imagen profesional utilizada como apoyo visual en una página sobre investigaciones "
                    f"de manipulación de inventario y pérdidas internas en {country}."
                ),
                "caption": "",
            }

        if role == "investigation_scene":
            return {
                "alt_text": "Revisión de registros durante una investigación interna de inventario",
                "title": "Revisión interna de diferencias de inventario",
                "description": (
                    f"Imagen profesional utilizada como apoyo visual para representar la revisión de registros, "
                    f"accesos y discrepancias de inventario en {country}."
                ),
                "caption": "",
            }

        return {
            "alt_text": "Análisis documental relacionado con manipulación de inventario",
            "title": "Análisis de una investigación de inventario",
            "description": (
                f"Imagen profesional utilizada como apoyo visual para representar el análisis de documentación "
                f"en una investigación de manipulación de inventario en {country}."
            ),
            "caption": "",
        }

    role_metadata = {
        "consultation_scene": {
            "alt_text": "Consulta profesional previa a una evaluación poligráfica",
            "title": "Consulta profesional previa",
            "description": f"Imagen profesional utilizada como apoyo visual para representar una consulta confidencial en {country}.",
        },
        "educational_concept_scene": {
            "alt_text": "Explicación profesional de un concepto relacionado con el polígrafo",
            "title": "Explicación profesional del polígrafo",
            "description": f"Imagen profesional utilizada como apoyo visual en una página educativa sobre evaluación poligráfica en {country}.",
        },
        "process_scene": {
            "alt_text": "Preparación profesional dentro del proceso de evaluación poligráfica",
            "title": "Preparación del proceso de evaluación",
            "description": f"Imagen profesional utilizada como apoyo visual para representar la preparación del proceso de evaluación poligráfica en {country}.",
        },
        "authority_professional_scene": {
            "alt_text": "Revisión profesional de documentación y estándares",
            "title": "Revisión profesional de estándares",
            "description": f"Imagen profesional utilizada como apoyo visual en una página sobre estándares, metodología o práctica profesional en {country}.",
        },
        "standards_documentation_scene": {
            "alt_text": "Documentación profesional relacionada con estándares de evaluación",
            "title": "Documentación profesional y estándares",
            "description": f"Imagen profesional utilizada como apoyo visual para representar documentación, estándares o revisión profesional en {country}.",
        },
        "article_topic_scene": {
            "alt_text": "Imagen de apoyo para un artículo informativo sobre evaluación poligráfica",
            "title": "Imagen de apoyo para artículo informativo",
            "description": f"Imagen profesional utilizada como apoyo visual en un artículo informativo en {country}.",
        },
    }

    selected = role_metadata.get(role)
    if selected:
        return {
            "alt_text": selected["alt_text"],
            "title": selected["title"],
            "description": selected["description"],
            "caption": "",
        }

    cleaned_topic = " ".join(str(topic or "evaluación poligráfica").split())
    return {
        "alt_text": f"Imagen profesional de apoyo sobre {cleaned_topic}",
        "title": "Imagen profesional de apoyo",
        "description": f"Imagen profesional utilizada como apoyo visual en una página sobre {cleaned_topic} en {country}.",
        "caption": "",
    }


def enhance_image_generation_request(request: Dict[str, Any], draft: Dict[str, Any] | None = None, workspace: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Enhance an image-generation request in-place.

    Safe to call repeatedly. Keeps existing filenames and IDs, but replaces generic
    prompts/metadata with issue-oriented visual intelligence.
    """
    draft = draft or {}
    workspace = workspace or {}
    source_slot = request.get("source_slot") or {}

    slot_id = request.get("slot_id") or source_slot.get("slot_id") or ""
    topic = (
        source_slot.get("topic")
        or draft.get("target_keyword")
        or draft.get("focus_keyphrase")
        or draft.get("title")
        or request.get("draft_id")
        or "servicio profesional de polígrafo"
    )

    page_plan = draft.get("page_plan") or {}
    page_type = page_plan.get("page_type") or draft.get("page_type") or "landing_page"
    country = workspace.get("country") or source_slot.get("country_localized") or "España"

    topic_family = detect_visual_topic_family(
        " ".join([
            str(topic),
            str(draft.get("title", "")),
            str(draft.get("summary", "")),
            str(draft.get("target_keyword", "")),
            str(draft.get("focus_keyphrase", "")),
        ])
    )
    role = (
        source_slot.get("visual_role")
        or source_slot.get("role")
        or infer_image_role(slot_id, topic_family)
    )

    prompt = build_visual_prompt(
        topic=str(topic),
        page_type=str(page_type),
        country=str(country),
        role=role,
        topic_family=topic_family,
    )
    metadata = build_visual_metadata(
        topic=str(topic),
        country=str(country),
        role=role,
        topic_family=topic_family,
    )

    request["prompt"] = prompt
    request["negative_prompt"] = NO_TEXT_NEGATIVE_PROMPT

    source_slot["prompt"] = prompt
    source_slot["negative_prompt"] = NO_TEXT_NEGATIVE_PROMPT
    source_slot["visual_role"] = role
    source_slot["visual_topic_family"] = topic_family
    source_slot["country_localized"] = country
    source_slot["metadata_strategy"] = "visual_intelligence_v1"

    for key, value in metadata.items():
        source_slot[key] = value

    request["source_slot"] = source_slot
    return request
