#!/usr/bin/env python3
"""
Sofia Page Plan Builder.

Creates a locked deterministic page_plan from:
- opportunity/intake/draft source data
- page type classifier
- global page blueprint
- workspace page presentation
- section library
- content taxonomy

Important:
The page_plan is a planning artifact.
Generation must follow it.
Validation must check against it.
Repair must not overwrite it.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


SOFIA_ROOT = Path(__file__).resolve().parents[1]

from page_blueprints import build_page_blueprint_package
from page_type_classifier import classify_page_type
from semantic_navigation import build_navigation_plan


PAGE_PLAN_VERSION = "1.1"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compact_section(section: Dict[str, Any]) -> Dict[str, Any]:
    """
    Keep page_plan compact and stable.
    Do not store the full section_library inside page_plan.
    """
    return {
        "id": section.get("id"),
        "type": section.get("type"),
        "required": bool(section.get("required")),
        "purpose": section.get("purpose", ""),
        "heading_required": bool(section.get("heading_required", True)),
        "validation_weight": section.get(
            "validation_weight",
            "blocking" if section.get("required") else "recommended",
        ),
        "min_words": int(section.get("min_words") or 0),
    }


def extract_source_value(source: Dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def infer_topic_key(source: Dict[str, Any]) -> str:
    return extract_source_value(
        source,
        "topic_key",
        "topic_id",
        "topic",
        "taxonomy_topic",
        default="",
    )


def build_image_slots(package: Dict[str, Any]) -> List[Dict[str, Any]]:
    blueprint = package.get("blueprint") or {}
    image_requirements = (
        package.get("image_requirements")
        or blueprint.get("image_requirements")
        or {}
    )

    # build_page_blueprint_package may expose legacy image_requirements at package level.
    # Prefer blueprint.image_requirements.visual_roles when available because visual roles
    # are the new source of truth for image structure.
    blueprint_image_requirements = blueprint.get("image_requirements") or {}
    if blueprint_image_requirements.get("visual_roles"):
        image_requirements = blueprint_image_requirements

    presentation = package.get("presentation_preferences") or {}
    image_strategy = presentation.get("image_strategy") or {}

    slots: List[Dict[str, Any]] = []

    # Preferred path: blueprint-driven visual roles.
    # These define the visual narrative of the page:
    # problem -> investigation -> analysis -> consultation/contact.
    visual_roles = image_requirements.get("visual_roles") or []
    if isinstance(visual_roles, list) and visual_roles:
        for index, raw_slot in enumerate(visual_roles, start=1):
            if not isinstance(raw_slot, dict):
                continue

            slot_id = raw_slot.get("slot_id") or raw_slot.get("id") or f"in_article_{index}"
            role = raw_slot.get("role") or raw_slot.get("visual_role") or "supporting_scene"

            slots.append(
                {
                    "slot_id": slot_id,
                    "required": bool(raw_slot.get("required", False)),
                    "role": role,
                    "visual_role": role,
                    "status": "planned",
                    "purpose": raw_slot.get("purpose", ""),
                    "placement": raw_slot.get("placement", ""),
                    "preferred_style": image_strategy.get("preferred_style", ""),
                    "future_generator": image_strategy.get("future_generator", ""),
                    "wordpress_insertion": raw_slot.get("wordpress_insertion") or "inline",
                    "source": "blueprint_visual_roles",
                }
            )

        return slots

    # Backward-compatible fallback for older blueprints.
    if image_requirements.get("featured_image_required"):
        slots.append(
            {
                "slot_id": "featured_image",
                "required": True,
                "role": "featured_image",
                "visual_role": "consultation_scene",
                "status": "planned",
                "preferred_style": image_strategy.get("preferred_style", ""),
                "future_generator": image_strategy.get("future_generator", ""),
                "wordpress_insertion": "featured_image",
                "source": "legacy_featured_image_required",
            }
        )

    if image_requirements.get("hero_image_required"):
        slots.append(
            {
                "slot_id": "hero_image",
                "required": True,
                "role": "hero_image",
                "visual_role": "hero_scene",
                "status": "planned",
                "preferred_style": image_strategy.get("preferred_style", ""),
                "future_generator": image_strategy.get("future_generator", ""),
                "wordpress_insertion": "hero_inline",
                "source": "legacy_hero_image_required",
            }
        )

    for raw_slot in image_requirements.get("inline_image_slots") or []:
        slot_id = raw_slot.get("slot_id") or raw_slot.get("id") or "inline_image"
        role = raw_slot.get("role") or raw_slot.get("visual_role") or "inline_image"
        slots.append(
            {
                "slot_id": slot_id,
                "required": bool(raw_slot.get("required", False)),
                "role": role,
                "visual_role": role,
                "status": "planned",
                "purpose": raw_slot.get("purpose", ""),
                "placement": raw_slot.get("placement", ""),
                "preferred_style": image_strategy.get("preferred_style", ""),
                "future_generator": image_strategy.get("future_generator", ""),
                "wordpress_insertion": "inline",
                "source": "legacy_inline_image_slots",
            }
        )

    return slots


def build_block_requirements(package: Dict[str, Any]) -> Dict[str, Any]:
    validation = package.get("validation_requirements") or {}
    presentation = package.get("presentation_preferences") or {}

    faq_prefs = presentation.get("faq") or {}
    rendering = presentation.get("rendering") or {}

    return {
        "faq": {
            "required": bool(validation.get("fail_if_missing_required_faq", False)),
            "minimum_items": int(validation.get("minimum_faq_items") or 0),
            "preferred_format": (
                rendering.get("faq_format")
                or faq_prefs.get("preferred_format")
                or faq_prefs.get("default_format")
                or "standard_html"
            ),
            "future_preferred_format": rendering.get(
                "future_preferred_faq_format",
                "yoast_faq_block",
            ),
        },
        "cta": {
            "required": bool(validation.get("requires_cta", False)),
            "rendering": rendering.get(
                "cta_rendering",
                "inline_html_now_reusable_block_later",
            ),
        },
        "trust": {
            "required": bool(validation.get("requires_trust_block", False)),
            "rendering": rendering.get(
                "trust_rendering",
                "inline_html_now_reusable_block_later",
            ),
        },
        "related_links": {
            "required_count": int(validation.get("required_internal_link_count") or 0),
            "rendering": rendering.get(
                "related_links_rendering",
                "inline_html_now_reusable_block_later",
            ),
        },
    }



def normalize_intelligence_text(value: str) -> str:
    return " ".join(str(value or "").lower().split())



def infer_semantic_entities(source: Dict[str, Any], title: str, topic: str, keyword: str) -> Dict[str, Any]:
    """
    Preserve concrete topic entities so downstream systems do not reduce
    specific opportunities into generic topic families.

    This remains language/workspace agnostic: it extracts semantic roles,
    not final wording.
    """
    haystack_raw = " ".join([
        str(title or ""),
        str(topic or ""),
        str(keyword or ""),
        str(source.get("summary", "")),
        str(source.get("description", "")),
        str(source.get("notes", "")),
    ])
    haystack = normalize_intelligence_text(haystack_raw)

    entities = {
        "service": "",
        "incident": "",
        "object": "",
        "industry": "",
        "country": "",
        "audience": "",
        "investigation_type": "",
        "raw_topic_text": haystack_raw.strip(),
    }

    if any(term in haystack for term in ["polígrafo", "poligrafo", "polygraph"]):
        entities["service"] = "polygraph_examination"

    if any(term in haystack for term in ["robo interno", "internal theft", "hurto interno"]):
        entities["incident"] = "internal_theft"

    if any(term in haystack for term in ["herramienta", "herramientas", "tools", "tool"]):
        entities["object"] = "tools"

    if any(term in haystack for term in ["mantenimiento", "maintenance"]):
        entities["industry"] = "maintenance_companies"

    if any(term in haystack for term in ["empresa", "empresas", "company", "companies"]):
        entities["audience"] = "companies"

    if any(term in haystack for term in ["españa", "spain"]):
        entities["country"] = "spain"

    if entities["audience"] == "companies" or entities["incident"] == "internal_theft":
        entities["investigation_type"] = "corporate_investigation"

    return entities


def infer_topic_intelligence_profile(source: Dict[str, Any], title: str, topic: str, keyword: str) -> Dict[str, Any]:
    """
    Build lightweight topic intelligence for section-level drafting.

    This does not replace market intelligence or knowledge blocks.
    It gives the generator practical angles so sections become less generic.
    """
    haystack = normalize_intelligence_text(" ".join([
        title,
        topic,
        keyword,
        str(source.get("summary", "")),
        str(source.get("description", "")),
        str(source.get("notes", "")),
    ]))

    profiles = [
        {
            "topic_family": "fuel_fraud",
            "terms": ["combustible", "fuel", "gasolina", "diésel", "diesel", "transporte", "flota"],
            "problem_angle": "sospechas de desvío de combustible, discrepancias entre consumo real y registros, uso indebido de tarjetas o pérdidas difíciles de atribuir",
            "consequence_angle": "pérdidas económicas recurrentes, deterioro del control interno, tensión entre conductores o empleados y dificultad para tomar decisiones disciplinarias justas",
            "investigation_angle": "los registros, GPS, tickets, auditorías internas o entrevistas pueden mostrar irregularidades sin aclarar de forma suficiente quién participó o qué ocurrió",
            "process_angle": "definir preguntas específicas sobre hechos verificables relacionados con combustible, acceso, autorización, conocimiento o participación",
            "faq_angle": "coste, confidencialidad, utilidad en empresas de transporte, voluntariedad, límites y relación con otras medidas de investigación",
            "typical_evidence_sources": ["fuel_card_records", "gps_logs", "mileage_records", "fuel_invoices", "route_schedules", "vehicle_assignments", "driver_statements"],
            "typical_missing_information": ["who_had_access_or_authorization", "whether_consumption_was_operational_or_irregular", "whether_participation_or_knowledge_can_be_clarified", "whether_records_explain_the_discrepancy"],
            "common_limitations": ["fuel_records_may_show_irregularities_without_proving_participation", "gps_data_may_not_explain_authorization_or_intent", "polygraph_results_must_be_interpreted_with_other_case_information"],
            "common_mistakes": ["assuming_every_fuel_difference_is_theft", "questioning_employees_before_reviewing_records", "using_the_polygraph_as_standalone_proof", "ignoring_operational_or_mechanical_explanations"],
            "visitor_questions": ["when_can_a_polygraph_support_a_fuel_fraud_investigation", "what_records_should_be_reviewed_first", "can_the_exam_help_clarify_driver_participation", "how_should_results_be_combined_with_audits_and_gps_data"],
            "common_objections": ["confidentiality", "employee_consent", "disciplinary_use", "limits_of_the_exam"],
        },
        {
            "topic_family": "inventory_manipulation",
            "terms": ["inventario", "almacén", "almacen", "stock", "mercancía", "mercancia", "warehouse"],
            "problem_angle": "diferencias de inventario, pérdidas internas, manipulación de stock, accesos no autorizados o registros que no coinciden con la mercancía real",
            "consequence_angle": "pérdidas financieras, errores operativos, sospechas entre empleados, ruptura de confianza y dificultad para mantener controles internos eficaces",
            "investigation_angle": "las cámaras, recuentos, sistemas de almacén o entrevistas pueden revelar discrepancias sin confirmar responsabilidad individual",
            "process_angle": "preparar preguntas claras sobre acceso, autorización, conocimiento, participación y manipulación de registros o mercancía",
            "faq_angle": "suitability for warehouse cases, confidentiality, employee consent, use with audits, limits and next steps",
            "typical_evidence_sources": ["inventory_records", "erp_or_wms_logs", "stock_movement_records", "warehouse_access_logs", "cycle_counts", "receiving_and_dispatch_records", "employee_statements"],
            "typical_missing_information": ["who_had_access_to_stock_or_records", "whether_discrepancies_are_operational_or_deliberate", "whether_authorization_or_knowledge_can_be_clarified", "whether_documentation_explains_the_missing_goods"],
            "common_limitations": ["inventory_records_may_confirm_loss_without_identifying_participation", "access_logs_may_show_presence_without_explaining_conduct", "polygraph_results_must_not_replace_audits_or_documentary_review"],
            "common_mistakes": ["assuming_every_stock_difference_is_intentional", "ignoring_receiving_or_dispatch_errors", "not_preserving_access_or_inventory_records", "using_the_polygraph_before_defining_verifiable_facts"],
            "visitor_questions": ["when_can_a_polygraph_support_an_inventory_investigation", "what_records_should_be_reviewed_before_the_exam", "can_the_exam_help_clarify_access_or_participation", "how_should_results_be_used_with_internal_audits"],
            "common_objections": ["confidentiality", "employee_consent", "use_with_audits", "limits_of_the_exam"],
        },
        {
            "topic_family": "infidelity",
            "terms": ["infidelidad", "pareja", "relación", "relacion", "conyugal"],
            "problem_angle": "dudas personales, pérdida de confianza, versiones contradictorias o necesidad de aclarar un hecho concreto dentro de una relación",
            "consequence_angle": "tensión emocional, deterioro de la comunicación, decisiones personales difíciles y riesgo de confrontaciones repetidas sin avance real",
            "investigation_angle": "las conversaciones privadas, mensajes o explicaciones pueden no resolver la duda si las partes mantienen versiones contradictorias",
            "process_angle": "formular preguntas limitadas, claras y aceptadas previamente por la persona examinada sobre hechos específicos",
            "faq_angle": "confidencialidad, consentimiento, número de preguntas, preparación, límites y utilidad para aclarar una situación concreta",
            "typical_evidence_sources": ["statements_from_the_people_involved", "messages_or_communications_if_voluntarily_provided", "timeline_of_the_relationship_concern", "agreed_relevant_questions"],
            "typical_missing_information": ["whether_the_question_can_be_defined_as_a_specific_event", "whether_both_parties_understand_the_limits", "whether_the_exam_is_appropriate_for_the_situation"],
            "common_limitations": ["relationship_questions_must_be_specific_and_limited", "the_exam_does_not_resolve_every_relationship_conflict", "consent_and_confidentiality_are_essential"],
            "common_mistakes": ["asking_broad_or_emotional_questions", "using_the_exam_as_pressure", "expecting_the_result_to_replace_communication_or_legal_advice"],
            "visitor_questions": ["what_questions_can_be_asked", "is_the_process_confidential", "does_the_person_need_to_consent", "what_are_the_limits"],
            "common_objections": ["privacy", "emotional_pressure", "number_of_questions", "limits_of_the_exam"],
        },
        {
            "topic_family": "pre_employment",
            "terms": ["pre-empleo", "pre empleo", "selección", "seleccion", "contratación", "contratacion", "integridad"],
            "problem_angle": "riesgos de contratación, dudas sobre integridad, antecedentes no declarados o funciones sensibles que requieren mayor confianza",
            "consequence_angle": "contrataciones inadecuadas, exposición a fraude interno, daños reputacionales y costes derivados de decisiones de selección mal informadas",
            "investigation_angle": "las entrevistas, referencias o comprobaciones documentales pueden no aclarar ciertos riesgos de integridad cuando la información depende de la declaración del candidato",
            "process_angle": "usar preguntas previamente revisadas, relevantes para el puesto y limitadas a aspectos profesionales permitidos y éticos",
            "faq_angle": "legalidad, consentimiento, tipos de preguntas, confidencialidad, adecuación al puesto y límites del examen",
            "typical_evidence_sources": ["job_role_requirements", "candidate_disclosures", "integrity_risk_areas", "employment_screening_documents", "role_sensitivity_information"],
            "typical_missing_information": ["whether_questions_are_relevant_to_the_role", "whether_the_candidate_has_given_informed_consent", "whether_screening_scope_is_professional_and_proportionate"],
            "common_limitations": ["screening_questions_must_be_role_relevant", "the_exam_must_not_replace_hiring_due_diligence", "results_should_be_used_with_professional_caution"],
            "common_mistakes": ["asking_irrelevant_personal_questions", "using_the_exam_without_clear_consent", "treating_the_result_as_the_only_hiring_factor"],
            "visitor_questions": ["when_is_pre_employment_polygraph_appropriate", "what_questions_can_be_asked", "how_is_confidentiality_handled", "how_are_results_used"],
            "common_objections": ["legality", "consent", "privacy", "job_relevance"],
        },
    ]

    profiles.append(
        {
            "topic_family": "internal_theft",
            "terms": ["robo interno", "hurto interno", "internal theft", "herramientas", "tools", "mantenimiento", "maintenance"],
            "problem_angle": "sospechas de robo interno, desaparición de herramientas, uso no autorizado de material de empresa o diferencias entre registros de entrega y devolución",
            "consequence_angle": "pérdidas económicas, interrupciones operativas, tensión entre empleados, deterioro de la confianza interna y dificultad para tomar decisiones disciplinarias justas",
            "investigation_angle": "los registros de herramientas, cámaras, controles de acceso o entrevistas pueden indicar irregularidades sin confirmar claramente responsabilidad individual",
            "process_angle": "preparar preguntas claras sobre acceso, autorización, conocimiento, participación, devolución de herramientas y posible sustracción de material",
            "faq_angle": "utilidad en casos de robo de herramientas, consentimiento del empleado, confidencialidad, relación con auditorías internas, límites y próximos pasos",
            "typical_evidence_sources": ["tool_assignment_records", "delivery_and_return_logs", "access_records", "maintenance_team_schedules", "inventory_or_asset_registers", "employee_statements"],
            "typical_missing_information": ["who_last_had_authorized_access", "whether_tools_were_lost_misused_or_stolen", "whether_records_explain_the_disappearance", "whether_participation_or_knowledge_can_be_clarified"],
            "common_limitations": ["asset_records_may_confirm_loss_without_identifying_participation", "shared_access_can_limit_individual_attribution", "polygraph_results_must_be interpreted_with_other_case_information"],
            "common_mistakes": ["assuming_missing_tools_always_mean_theft", "not_reviewing_assignment_and_return_records", "accusing_employees_without_clear_chronology", "using_the_polygraph_as_standalone_proof"],
            "visitor_questions": ["when_can_a_polygraph_support_a_tool_theft_investigation", "what_records_should_be_reviewed_first", "can_the_exam_help_clarify_access_or_participation", "how_should_results_be_combined_with_internal_records"],
            "common_objections": ["employee_consent", "confidentiality", "disciplinary_use", "limits_of_the_exam"],
        }
    )

    for profile in profiles:
        if any(term in haystack for term in profile["terms"]):
            clean_profile = {k: v for k, v in profile.items() if k != "terms"}
            clean_profile["professional_knowledge_model"] = build_professional_knowledge_model(clean_profile)
            return clean_profile

    general_profile = {
        "topic_family": "general_polygraph_service",
        "problem_angle": "una duda concreta, una sospecha o una situación que requiere evaluación profesional y preguntas específicas",
        "consequence_angle": "incertidumbre, pérdida de confianza, decisiones difíciles y necesidad de actuar con prudencia",
        "investigation_angle": "la información disponible puede ser incompleta, contradictoria o insuficiente para orientar una decisión responsable",
        "process_angle": "definir preguntas claras, revisar el caso previamente y respetar consentimiento, confidencialidad y límites profesionales",
        "faq_angle": "proceso, confidencialidad, consentimiento, límites, preparación y siguientes pasos",
        "typical_evidence_sources": ["available_case_information", "statements", "documents", "timeline", "relevant_questions"],
        "typical_missing_information": ["what_specific_fact_must_be_clarified", "whether_the_question_is_verifiable", "whether_the_exam_is_appropriate", "what_other_information_should_be_reviewed"],
        "common_limitations": ["available_information_may_be_incomplete", "questions_must_be_specific", "the_exam_does_not_replace_a_broader_professional_review"],
        "common_mistakes": ["asking_questions_that_are_too_broad", "expecting_absolute_certainty", "using_the_exam_without_reviewing_the_case_context"],
        "visitor_questions": ["when_is_a_polygraph_appropriate", "what_information_is_needed_before_the_exam", "what_are_the_limits", "how_is_confidentiality_handled"],
        "common_objections": ["confidentiality", "consent", "limits", "next_steps"],
    }

    general_profile["professional_knowledge_model"] = build_professional_knowledge_model(general_profile)
    return general_profile



def build_professional_knowledge_model(profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a structured professional knowledge model from the topic profile.

    This keeps Sofia language-agnostic and workspace-agnostic:
    it stores investigation concepts, not final visitor-facing wording.
    """
    topic_family = profile.get("topic_family", "")

    return {
        "professional_situation": {
            "client_problem": profile.get("problem_angle", ""),
            "business_or_personal_consequence": profile.get("consequence_angle", ""),
            "decision_pressure": (
                "The visitor needs to understand whether the available information is sufficient "
                "or whether a complementary professional evaluation may be appropriate."
            ),
            "professional_goal": (
                "Help the visitor understand the issue as an investigation problem, not only as a service request."
            ),
        },
        "investigation": {
            "why_case_is_complex": profile.get("investigation_angle", ""),
            "existing_information": profile.get("typical_evidence_sources", []),
            "remaining_questions": profile.get("typical_missing_information", []),
            "common_limitations": profile.get("common_limitations", []),
            "common_mistakes": profile.get("common_mistakes", []),
        },
        "polygraph": {
            "role": profile.get("process_angle", ""),
            "responsible_positioning": (
                "The polygraph should be presented as a complementary professional tool, "
                "not as proof, certainty, or a replacement for the broader investigation."
            ),
        },
        "faq": {
            "focus": profile.get("faq_angle", ""),
            "visitor_questions": profile.get("visitor_questions", []),
            "common_objections": profile.get("common_objections", []),
        },
        "topic_family": topic_family,
    }


def select_professional_context_for_section(section_type: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    model = profile.get("professional_knowledge_model") or {}
    section_type = str(section_type or "")

    if section_type in ("problem", "hero", "introduction", "definition", "main_content"):
        return {
            "professional_situation": model.get("professional_situation", {}),
        }

    if section_type == "consequences":
        return {
            "professional_situation": model.get("professional_situation", {}),
            "decision_context": (model.get("professional_situation") or {}).get("decision_pressure", ""),
        }

    if section_type in ("investigation_challenges", "professional_context"):
        return {
            "investigation": model.get("investigation", {}),
        }

    if section_type in ("process", "polygraph_role"):
        return {
            "investigation": model.get("investigation", {}),
            "polygraph": model.get("polygraph", {}),
        }

    if section_type == "faq":
        return {
            "faq": model.get("faq", {}),
            "investigation": model.get("investigation", {}),
        }

    if section_type in ("limitations", "trust"):
        return {
            "polygraph": model.get("polygraph", {}),
            "investigation": {
                "common_limitations": (model.get("investigation") or {}).get("common_limitations", []),
                "common_mistakes": (model.get("investigation") or {}).get("common_mistakes", []),
            },
        }

    if section_type in ("cta", "soft_cta"):
        return {
            "next_step_context": (model.get("professional_situation") or {}).get("decision_pressure", ""),
            "professional_goal": (model.get("professional_situation") or {}).get("professional_goal", ""),
        }

    return {}



SECTION_SEMANTIC_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "hero": {
        "purpose": "frame_primary_intent",
        "visitor_state": "needs_orientation",
        "conversion_stage": "awareness",
        "writing_objective": "confirm_relevance_and_set_expectation",
        "content_priority": "critical",
        "image_role": "context_scene",
        "image_priority": "high",
        "internal_link_intent": "none",
        "cta_intent": "none",
    },
    "introduction": {
        "purpose": "answer_initial_query",
        "visitor_state": "seeking_answer",
        "conversion_stage": "awareness",
        "writing_objective": "answer_search_intent_early",
        "content_priority": "critical",
        "image_role": "context_scene",
        "image_priority": "medium",
        "internal_link_intent": "supporting_context",
        "cta_intent": "none",
    },
    "problem": {
        "purpose": "define_problem",
        "visitor_state": "concerned_or_uncertain",
        "conversion_stage": "awareness",
        "writing_objective": "make_problem_specific_and_recognizable",
        "content_priority": "critical",
        "image_role": "problem_scene",
        "image_priority": "high",
        "internal_link_intent": "related_service",
        "cta_intent": "none",
    },
    "consequences": {
        "purpose": "explain_risk_or_impact",
        "visitor_state": "evaluating_seriousness",
        "conversion_stage": "awareness",
        "writing_objective": "show_why_the_issue_should_be_handled_responsibly",
        "content_priority": "high",
        "image_role": "impact_or_context_scene",
        "image_priority": "medium",
        "internal_link_intent": "related_service_or_case_type",
        "cta_intent": "none",
    },
    "investigation_challenges": {
        "purpose": "explain_complexity",
        "visitor_state": "looking_for_clarity",
        "conversion_stage": "consideration",
        "writing_objective": "explain_why_normal_methods_may_be_insufficient",
        "content_priority": "high",
        "image_role": "investigation_scene",
        "image_priority": "high",
        "internal_link_intent": "methodology_or_process",
        "cta_intent": "none",
    },
    "professional_context": {
        "purpose": "build_professional_relevance",
        "visitor_state": "comparing_options",
        "conversion_stage": "consideration",
        "writing_objective": "connect_topic_to_professional_decision_making",
        "content_priority": "high",
        "image_role": "professional_context_scene",
        "image_priority": "medium",
        "internal_link_intent": "authority_or_methodology",
        "cta_intent": "soft",
    },
    "polygraph_role": {
        "purpose": "explain_service_role",
        "visitor_state": "evaluating_solution",
        "conversion_stage": "consideration",
        "writing_objective": "explain_how_polygraph_fits_without_overclaiming",
        "content_priority": "critical",
        "image_role": "analysis_scene",
        "image_priority": "high",
        "internal_link_intent": "methodology_or_limitations",
        "cta_intent": "soft",
    },
    "process": {
        "purpose": "explain_process",
        "visitor_state": "preparing_to_act",
        "conversion_stage": "decision",
        "writing_objective": "make_next_steps_clear_and_low_friction",
        "content_priority": "critical",
        "image_role": "process_scene",
        "image_priority": "medium",
        "internal_link_intent": "faq_or_contact",
        "cta_intent": "soft",
    },
    "limitations": {
        "purpose": "set_responsible_limits",
        "visitor_state": "needs_reassurance",
        "conversion_stage": "consideration",
        "writing_objective": "explain_consent_confidentiality_limits_and_ethics",
        "content_priority": "critical",
        "image_role": "trust_scene",
        "image_priority": "low",
        "internal_link_intent": "authority_or_ethics",
        "cta_intent": "soft",
    },
    "trust": {
        "purpose": "build_trust",
        "visitor_state": "needs_reassurance",
        "conversion_stage": "decision",
        "writing_objective": "support_confidence_without_guarantees",
        "content_priority": "high",
        "image_role": "trust_scene",
        "image_priority": "medium",
        "internal_link_intent": "authority_or_about",
        "cta_intent": "soft",
    },
    "faq": {
        "purpose": "resolve_objections",
        "visitor_state": "has_practical_questions",
        "conversion_stage": "decision",
        "writing_objective": "answer_specific_questions_and_reduce_uncertainty",
        "content_priority": "critical",
        "image_role": "none",
        "image_priority": "none",
        "internal_link_intent": "authority_or_related_topics",
        "cta_intent": "soft",
    },
    "cta": {
        "purpose": "invite_next_step",
        "visitor_state": "ready_or_nearly_ready",
        "conversion_stage": "conversion",
        "writing_objective": "invite_contact_without_pressure",
        "content_priority": "critical",
        "image_role": "consultation_scene",
        "image_priority": "low",
        "internal_link_intent": "contact",
        "cta_intent": "primary",
    },
    "soft_cta": {
        "purpose": "offer_gentle_next_step",
        "visitor_state": "still_evaluating",
        "conversion_stage": "decision",
        "writing_objective": "offer_guidance_without_sales_pressure",
        "content_priority": "high",
        "image_role": "consultation_scene",
        "image_priority": "low",
        "internal_link_intent": "contact_or_related_topic",
        "cta_intent": "soft",
    },
    "strategic_links": {
        "purpose": "guide_next_navigation",
        "visitor_state": "needs_path_forward",
        "conversion_stage": "navigation",
        "writing_objective": "connect_reader_to_relevant_next_pages",
        "content_priority": "supporting",
        "image_role": "none",
        "image_priority": "none",
        "internal_link_intent": "semantic_navigation",
        "cta_intent": "none",
    },
    "related_services": {
        "purpose": "connect_related_services",
        "visitor_state": "comparing_service_options",
        "conversion_stage": "consideration",
        "writing_objective": "help_reader_choose_related_service_path",
        "content_priority": "high",
        "image_role": "none",
        "image_priority": "none",
        "internal_link_intent": "related_services",
        "cta_intent": "soft",
    },
    "local_context": {
        "purpose": "establish_local_relevance",
        "visitor_state": "checking_availability",
        "conversion_stage": "consideration",
        "writing_objective": "explain_local_relevance_without_inventing_presence",
        "content_priority": "critical",
        "image_role": "local_context_scene",
        "image_priority": "medium",
        "internal_link_intent": "city_or_service",
        "cta_intent": "soft",
    },
    "client_situations": {
        "purpose": "show_use_cases",
        "visitor_state": "matching_own_case",
        "conversion_stage": "consideration",
        "writing_objective": "describe_realistic_situations_where_topic_applies",
        "content_priority": "high",
        "image_role": "case_situation_scene",
        "image_priority": "medium",
        "internal_link_intent": "related_service",
        "cta_intent": "soft",
    },
    "definition": {
        "purpose": "define_topic",
        "visitor_state": "learning",
        "conversion_stage": "awareness",
        "writing_objective": "define_clearly_and_responsibly",
        "content_priority": "critical",
        "image_role": "educational_concept_scene",
        "image_priority": "high",
        "internal_link_intent": "pillar_or_supporting_article",
        "cta_intent": "none",
    },
    "applications": {
        "purpose": "explain_applications",
        "visitor_state": "learning_practical_use",
        "conversion_stage": "consideration",
        "writing_objective": "connect_concept_to_real_practice",
        "content_priority": "high",
        "image_role": "application_scene",
        "image_priority": "medium",
        "internal_link_intent": "related_services",
        "cta_intent": "soft",
    },
    "main_content": {
        "purpose": "develop_main_explanation",
        "visitor_state": "seeking_depth",
        "conversion_stage": "awareness",
        "writing_objective": "develop_topic_with_specific_useful_detail",
        "content_priority": "critical",
        "image_role": "supporting_context_scene",
        "image_priority": "medium",
        "internal_link_intent": "supporting_article_or_authority",
        "cta_intent": "none",
    },
    "pricing": {
        "purpose": "explain_price_information",
        "visitor_state": "checking_cost",
        "conversion_stage": "decision",
        "writing_objective": "present_price_context_transparently",
        "content_priority": "critical",
        "image_role": "none",
        "image_priority": "none",
        "internal_link_intent": "service_or_contact",
        "cta_intent": "soft",
    },
    "pricing_factors": {
        "purpose": "explain_price_variables",
        "visitor_state": "checking_cost_conditions",
        "conversion_stage": "decision",
        "writing_objective": "explain_what_affects_cost_without_confusion",
        "content_priority": "high",
        "image_role": "none",
        "image_priority": "none",
        "internal_link_intent": "faq_or_contact",
        "cta_intent": "soft",
    },
    "included_services": {
        "purpose": "clarify_service_scope",
        "visitor_state": "checking_value",
        "conversion_stage": "decision",
        "writing_objective": "explain_what_is_normally_included",
        "content_priority": "high",
        "image_role": "process_scene",
        "image_priority": "low",
        "internal_link_intent": "process_or_contact",
        "cta_intent": "soft",
    },
    "benefits": {
        "purpose": "explain_benefits_cautiously",
        "visitor_state": "evaluating_value",
        "conversion_stage": "consideration",
        "writing_objective": "explain_possible_benefits_without_absolute_claims",
        "content_priority": "high",
        "image_role": "benefit_context_scene",
        "image_priority": "medium",
        "internal_link_intent": "related_services",
        "cta_intent": "soft",
    },
}


def infer_topic_focus_for_section(section_type: str, profile: Dict[str, Any]) -> str:
    if section_type in ("problem", "hero", "introduction", "definition", "main_content"):
        return profile.get("problem_angle", "")
    if section_type == "consequences":
        return profile.get("consequence_angle", "")
    if section_type in ("investigation_challenges", "professional_context"):
        return profile.get("investigation_angle", "")
    if section_type in ("process", "polygraph_role"):
        return profile.get("process_angle", "")
    if section_type == "faq":
        return profile.get("faq_angle", "")
    if section_type in ("limitations", "trust"):
        return "responsible_limits_consent_confidentiality_ethics"
    if section_type in ("cta", "soft_cta"):
        return "confidential_next_step_without_pressure"
    return profile.get("problem_angle", "")


def build_section_semantic_contract(section: Dict[str, Any]) -> Dict[str, Any]:
    section_type = section.get("type", "") or "main_content"
    defaults = SECTION_SEMANTIC_DEFAULTS.get(
        section_type,
        {
            "purpose": "support_page_intent",
            "visitor_state": "needs_information",
            "conversion_stage": "awareness",
            "writing_objective": "support_the_page_goal",
            "content_priority": "supporting",
            "image_role": "supporting_context_scene",
            "image_priority": "low",
            "internal_link_intent": "supporting_context",
            "cta_intent": "none",
        },
    )

    return {
        "semantic_version": "1.0",
        "section_type": section_type,
        "section_required": bool(section.get("required")),
        "section_min_words": int(section.get("min_words") or 0),
        **defaults,
        "quality_risk_flags": [
            "generic_filler",
            "off_intent_content",
            "unsupported_absolute_claims",
            "missing_responsible_limits",
        ],
    }


def build_section_intelligence(required_sections: list, profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Attach language-agnostic semantic intelligence keyed by required section id.

    This is the Phase 4.1 section intent contract.
    It describes purpose, visitor state, conversion stage, image role,
    internal-link intent, and CTA intent without localized wording.

    Existing topic-specific drafting_focus is preserved for backward
    compatibility with the current generator prompt.
    """
    result = {}

    for section in required_sections or []:
        section_id = section.get("id", "")
        section_type = section.get("type", "")

        if not section_id:
            continue

        semantic_contract = build_section_semantic_contract(section)
        topic_focus = infer_topic_focus_for_section(section_type, profile)

        result[section_id] = {
            **semantic_contract,
            "topic_family": profile.get("topic_family", ""),
            "drafting_focus": topic_focus,
            "topic_focus_source": "topic_intelligence_profile",
            "professional_context": select_professional_context_for_section(section_type, profile),
            "avoid": [
                "generic_filler",
                "encyclopedic_content_not_connected_to_page_intent",
                "certainty_or_guarantee_claims",
                "polygraph_as_absolute_proof",
            ],
        }

    return result


def build_page_plan(
    source: Dict[str, Any],
    workspace_id: str,
    explicit_page_type: str = "",
    explicit_blueprint_id: str = "",
) -> Dict[str, Any]:
    """
    Build locked page_plan.

    source can be an opportunity, intake, draft metadata, or manual dict.
    """
    source = source or {}

    title = extract_source_value(source, "title", "headline", "name")
    topic = extract_source_value(source, "topic_label", "topic", "idea", "description")
    keyword = extract_source_value(source, "target_keyword", "focus_keyphrase", "keyword")
    content_type = extract_source_value(source, "content_type", "type")
    requested_page_type = extract_source_value(
        source,
        "requested_page_type",
        "page_type",
        default=explicit_page_type,
    )

    if explicit_page_type:
        requested_page_type = explicit_page_type

    classification = classify_page_type(
        title=title,
        topic=topic,
        keyword=keyword,
        content_type=content_type,
        user_requested_type=requested_page_type,
    )

    blueprint_id = explicit_blueprint_id or classification.get("blueprint_id")

    topic_key = infer_topic_key(source)

    package_source = {
        **source,
        "page_type": classification.get("page_type"),
        "blueprint_id": blueprint_id,
        "topic_key": topic_key,
        "title": title,
        "target_keyword": keyword,
    }

    package = build_page_blueprint_package(
        package_source,
        workspace_id=workspace_id,
    )

    required_sections = [
        compact_section(section)
        for section in package.get("required_sections") or []
    ]

    optional_sections = [
        compact_section(section)
        for section in package.get("optional_sections") or []
    ]

    validation_requirements = package.get("validation_requirements") or {}
    presentation_preferences = package.get("presentation_preferences") or {}

    source_id = extract_source_value(
        source,
        "opportunity_id",
        "intake_id",
        "draft_id",
        "id",
        default="",
    )

    semantic_entities = infer_semantic_entities(
        source=source,
        title=title,
        topic=topic,
        keyword=keyword,
    )

    topic_intelligence_profile = infer_topic_intelligence_profile(
        source=source,
        title=title,
        topic=topic,
        keyword=keyword,
    )

    section_intelligence = build_section_intelligence(
        required_sections=required_sections,
        profile=topic_intelligence_profile,
    )

    #
    # Phase 4.2
    # Build deterministic semantic visitor navigation.
    #
    navigation_plan = build_navigation_plan(
        {
            "required_sections": required_sections
        }
    )

    page_plan = {
        "version": PAGE_PLAN_VERSION,
        "locked": True,
        "created_at": utc_now(),
        "created_by": "page_plan_builder",
        "workspace_id": workspace_id,
        "created_from": {
            "source_id": source_id,
            "source_type": extract_source_value(source, "source_type", default="unknown"),
        },
        "classification": classification,
        "blueprint_id": package.get("blueprint_id"),
        "page_type": classification.get("page_type"),
        "topic_key": topic_key,
        "topic_label": (package.get("topic_intelligence") or {}).get("label", ""),
        "title": title,
        "target_keyword": keyword,
        "search_intent": (
            classification.get("intent_type")
            or (package.get("blueprint") or {})
            .get("drafting_instructions", {})
            .get("search_intent", "")
        ),
        "required_sections": required_sections,
        "optional_sections": optional_sections,
        "semantic_entities": semantic_entities,
        "topic_intelligence_profile": topic_intelligence_profile,
        "section_intelligence": section_intelligence,

        #
        # Phase 4.2
        # Semantic navigation contract.
        #
        "navigation_plan": navigation_plan,

        "validation_requirements": {
            "minimum_word_count": validation_requirements.get("minimum_word_count"),
            "minimum_faq_items": validation_requirements.get("minimum_faq_items"),
            "required_section_ids": validation_requirements.get("required_section_ids", []),
            "required_internal_link_count": validation_requirements.get(
                "required_internal_link_count"
            ),
            "requires_cta": validation_requirements.get("requires_cta"),
            "requires_trust_block": validation_requirements.get("requires_trust_block"),
            "requires_featured_image": validation_requirements.get(
                "requires_featured_image"
            ),
            "requires_hero_image": validation_requirements.get("requires_hero_image"),
        },
        "block_requirements": build_block_requirements(package),
        "image_slots": build_image_slots(package),
        "presentation": {
            "faq": presentation_preferences.get("faq") or {},
            "cta_strategy": presentation_preferences.get("cta_strategy") or {},
            "trust_blocks": presentation_preferences.get("trust_blocks") or {},
            "strategic_links": presentation_preferences.get("strategic_links") or {},
            "layout_preferences": presentation_preferences.get("layout_preferences") or {},
            "image_strategy": presentation_preferences.get("image_strategy") or {},
            "rendering": presentation_preferences.get("rendering") or {},
            "validation_preferences": presentation_preferences.get(
                "validation_preferences"
            )
            or {},
        },
        "generation_contract": {
            "must_follow_required_sections": True,
            "must_not_remove_required_sections": True,
            "must_generate_faq_if_required": True,
            "must_generate_cta_if_required": True,
            "must_respect_limits_and_ethics": True,
            "must_not_invent_addresses": True,
            "must_not_invent_prices": True,
            "must_not_invent_wordpress_block_ids": True,
        },
        "repair_contract": {
            "repair_must_follow_page_plan": True,
            "repair_must_not_overwrite_page_plan": True,
            "repair_missing_sections_instead_of_replanning": True,
        },
        "validation_contract": {
            "validate_against_page_plan": True,
            "page_plan_is_source_of_truth": True,
        },
    }

    return page_plan


def save_page_plan(page_plan: Dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(page_plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_source_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing source file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a Sofia page_plan.")
    parser.add_argument("--workspace", required=True, help="Workspace ID, e.g. local.es")
    parser.add_argument("--source-json", help="Path to source JSON file")
    parser.add_argument("--title", help="Manual title/topic text")
    parser.add_argument("--topic-key", help="Optional taxonomy topic key")
    parser.add_argument("--keyword", help="Optional target keyword")
    parser.add_argument("--page-type", help="Optional explicit page type")
    parser.add_argument("--blueprint-id", help="Optional explicit blueprint ID")
    parser.add_argument("--output", help="Optional output JSON path")

    args = parser.parse_args()

    if args.source_json:
        source = load_source_file(Path(args.source_json))
    else:
        source = {
            "title": args.title or "",
            "topic_key": args.topic_key or "",
            "target_keyword": args.keyword or "",
            "requested_page_type": args.page_type or "",
            "source_type": "manual_cli",
        }

    if args.topic_key:
        source["topic_key"] = args.topic_key

    if args.keyword:
        source["target_keyword"] = args.keyword

    page_plan = build_page_plan(
        source=source,
        workspace_id=args.workspace,
        explicit_page_type=args.page_type or "",
        explicit_blueprint_id=args.blueprint_id or "",
    )

    if args.output:
        save_page_plan(page_plan, Path(args.output))
        print(f"Saved page_plan: {args.output}")
    else:
        print(json.dumps(page_plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()