"""
Sofia Opportunity Intelligence v1.

Workspace-agnostic structural layer.
Localized labels, templates and classifier terms must live in each workspace's
opportunity_intelligence_profile.json.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from app.workspace_paths import get_workspace_folder_path
except Exception:
    from workspace_paths import get_workspace_folder_path


ROOT = Path(__file__).resolve().parents[1]
GLOBAL_ISSUE_PROFILES_PATH = ROOT / "data" / "opportunity_intelligence_profiles.json"


COMMAND_PATTERNS = [
    r"\bsof[ií]a\b[,:\s-]*",
    r"\bcrea(?:r)?\s+(?:una\s+)?p[aá]gina\s+(?:para\s+empresas\s+)?(?:sobre\s+)?",
    r"\bgenera(?:r)?\s+(?:una\s+)?p[aá]gina\s+(?:sobre\s+)?",
    r"\bhaz(?:me)?\s+(?:una\s+)?p[aá]gina\s+(?:sobre\s+)?",
    r"\bescribe(?:me)?\s+(?:una\s+)?p[aá]gina\s+(?:sobre\s+)?",
    r"\bseo\s+sobre\s+",
]


def strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", value or "")
        if unicodedata.category(ch) != "Mn"
    )


def normalize(value: str) -> str:
    value = strip_accents(value or "").lower()
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def slugify(value: str) -> str:
    value = normalize(value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:90].strip("-")


def clean_request(text: str) -> str:
    cleaned = text or ""
    for pattern in COMMAND_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.I)

    cleaned = re.sub(r"^\s*(sobre|para|acerca de)\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;-")
    return cleaned


def load_global_issue_profiles() -> Dict[str, Any]:
    if not GLOBAL_ISSUE_PROFILES_PATH.exists():
        return {}

    try:
        return json.loads(GLOBAL_ISSUE_PROFILES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_issue_profile(issue_id: str) -> Dict[str, Any]:
    data = load_global_issue_profiles()
    profiles = data.get("issue_profiles") or {}

    profile = profiles.get(issue_id) or {}
    return profile if isinstance(profile, dict) else {}


def load_profile(workspace_id: str) -> Dict[str, Any]:
    workspace_folder = get_workspace_folder_path(workspace_id)
    path = ROOT / workspace_folder / "opportunity_intelligence_profile.json"

    if not path.exists():
        return {}

    return json.loads(path.read_text(encoding="utf-8"))


def source_text_from_opportunity(opportunity: Dict[str, Any]) -> str:
    seo_brief = opportunity.get("seo_brief") or {}

    return (
        opportunity.get("localized_topic")
        or opportunity.get("topic_label")
        or opportunity.get("workspace_language_topic")
        or opportunity.get("raw_signal")
        or opportunity.get("title")
        or opportunity.get("topic")
        or seo_brief.get("page_title")
        or ""
    )


def score_patterns(text: str, patterns_by_id: Dict[str, List[str]]) -> Tuple[str, int]:
    haystack = normalize(text)
    best_id = ""
    best_score = 0

    for item_id, terms in (patterns_by_id or {}).items():
        score = 0
        for term in terms or []:
            if normalize(term) in haystack:
                score += 1

        if score > best_score:
            best_id = item_id
            best_score = score

    return best_id, best_score


def render_template(template: str, values: Dict[str, str]) -> str:
    try:
        return (template or "").format(**values)
    except KeyError:
        return template or ""


def build_recommended_fields(profile: Dict[str, Any], values: Dict[str, str]) -> Dict[str, str]:
    templates = profile.get("templates") or {}
    fallback_templates = profile.get("fallback_templates") or {}

    has_issue = bool(values.get("issue"))
    source = templates if has_issue else fallback_templates

    result = {
        "recommended_title": render_template(source.get("recommended_title", ""), values),
        "recommended_h1": render_template(source.get("recommended_h1", ""), values),
        "recommended_focus_keyphrase": render_template(
            source.get("recommended_focus_keyphrase", ""), values
        ),
        "recommended_slug_basis": render_template(
            source.get("recommended_slug_basis", ""), values
        ),
        "recommended_seo_title": render_template(
            source.get("recommended_seo_title", ""), values
        )[:65].rstrip(),
        "recommended_meta_description": render_template(
            source.get("recommended_meta_description", ""), values
        )[:155].rstrip(),
    }

    result["recommended_slug"] = slugify(
        result.get("recommended_slug_basis")
        or result.get("recommended_focus_keyphrase")
        or result.get("recommended_title")
    )

    return result



def build_professional_opportunity_model(
    *,
    issue_profile: Dict[str, Any],
    issue: str,
    sector: str,
) -> Dict[str, Any]:
    """
    Build deterministic professional opportunity intelligence.

    This is not SEO metadata and not visitor-facing copy.
    It explains the real investigation context behind the opportunity so
    downstream systems can make better content decisions.
    """

    content_angles = issue_profile.get("content_angles") or []
    primary_angle = content_angles[0] if content_angles and isinstance(content_angles[0], dict) else {}

    if primary_angle:
        client_problem = primary_angle.get("problem_angle") or issue
        investigation_trigger = primary_angle.get("process_angle") or issue
        faq_angle = primary_angle.get("faq_angle") or issue
    else:
        angle_terms = [str(item) for item in content_angles if isinstance(item, str)]
        angle_summary = ", ".join(angle_terms[:5])

        # Keep this model mostly structural. Avoid mixing languages with
        # generated fragments such as "{issue} in {sector}".
        client_problem = issue
        investigation_trigger = angle_summary or issue
        faq_angle = angle_summary or issue

    evidence_question = (
        f"What evidence should normally be reviewed before considering a polygraph in {sector}?"
        if sector
        else "What evidence should normally be reviewed before considering a polygraph?"
    )

    return {
        "version": "1.0",
        "source": "professional_opportunity_model_v1",
        "issue": issue,
        "sector": sector,
        "content_angle_terms": [
            str(item) for item in content_angles
            if isinstance(item, str) and str(item).strip()
        ],
        "client_problem": client_problem,
        "investigation_trigger": investigation_trigger,
        "existing_evidence": (
            "Documents, interviews, operational records or internal controls may indicate "
            "irregularities without fully explaining what happened."
        ),
        "missing_information": (
            "Available evidence may not clarify knowledge, participation, authorization or intent."
        ),
        "decision_pressure": (
            "The visitor needs to decide whether additional professional evaluation may help before "
            "disciplinary, operational or legal decisions are taken."
        ),
        "professional_objective": (
            "Explain how a professional polygraph examination may provide complementary information "
            "within a broader investigation."
        ),
        "authority_position": (
            "Write as an experienced investigative professional, not as a salesperson."
        ),
        "editorial_angle": (
            "Help the visitor understand the investigation problem before presenting the polygraph "
            "as one possible professional tool."
        ),
        "visitor_questions": [
            f"When can a polygraph assist with {issue}?" if issue else "When can a polygraph assist with this type of investigation?",
            evidence_question,
            "Can the examination replace documentary evidence?",
            "What limitations should be considered?",
            "When is a professional evaluation appropriate?",
        ],
        "faq_editorial_angle": faq_angle,
    }



def analyze_opportunity(opportunity: Dict[str, Any], workspace: Dict[str, Any]) -> Dict[str, Any]:
    workspace_id = (
        workspace.get("workspace_id")
        or workspace.get("id")
        or opportunity.get("workspace_id")
        or ""
    )

    profile = load_profile(workspace_id)
    raw_text = source_text_from_opportunity(opportunity)
    cleaned = clean_request(raw_text)

    issue_id, issue_score = score_patterns(cleaned, profile.get("issue_patterns") or {})
    sector_id, sector_score = score_patterns(cleaned, profile.get("sector_patterns") or {})

    issue_labels = profile.get("issue_labels") or {}
    sector_labels = profile.get("sector_labels") or {}

    issue = issue_labels.get(issue_id, "")
    sector = sector_labels.get(sector_id, "")

    country = profile.get("country_localized") or workspace.get("country") or ""
    service_angle = "polygraph_investigation"

    values = {
        "issue": issue,
        "sector": sector,
        "country": country,
        "service_term": (profile.get("service_terms") or {}).get("polygraph", ""),
        "polygraph_test": (profile.get("service_terms") or {}).get("polygraph_test", ""),
    }

    recommended = build_recommended_fields(profile, values)

    topic_family = issue_id or "general_polygraph_service"
    visual_topic_family = issue_id or "general_polygraph_service"

    issue_profile = get_issue_profile(issue_id)
    professional_opportunity_model = build_professional_opportunity_model(
        issue_profile=issue_profile,
        issue=issue,
        sector=sector,
    )
    image_strategy = profile.get("image_strategy") or {}

    confidence_score = issue_score + sector_score
    confidence = "high" if issue_score and sector_score else "medium" if issue_score else "low"

    return {
        "version": "1.0",
        "source": "opportunity_intelligence_v1",
        "workspace_id": workspace_id,
        "language": profile.get("language", ""),
        "raw_opportunity_text": raw_text,
        "cleaned_request": cleaned,
        "issue_id": issue_id,
        "issue": issue,
        "sector_id": sector_id,
        "sector": sector,
        "country_localized": country,
        "service_angle": service_angle,
        "page_type": opportunity.get("content_type") or "landing_page",
        "search_intent": "commercial_investigation",
        "topic_family": topic_family,
        "visual_topic_family": visual_topic_family,
        "recommended_title": recommended.get("recommended_title", ""),
        "recommended_h1": recommended.get("recommended_h1", ""),
        "recommended_focus_keyphrase": recommended.get("recommended_focus_keyphrase", ""),
        "recommended_slug": recommended.get("recommended_slug", ""),
        "recommended_seo_title": recommended.get("recommended_seo_title", ""),
        "recommended_meta_description": recommended.get("recommended_meta_description", ""),
        "image_strategy": image_strategy,
        "professional_opportunity_model": professional_opportunity_model,
        "content_angles": issue_profile.get("content_angles", []),
        "visual_scenarios": issue_profile.get("visual_scenarios", {}),
        "faq_topics": issue_profile.get("faq_topics") or [
            item for item in [issue, sector, service_angle, "confidentiality", "process", "limits"]
            if item
        ],
        "internal_link_topics": issue_profile.get("internal_link_topics") or [
            item for item in [issue, sector, service_angle, topic_family]
            if item
        ],
        "needs_ai_enrichment": confidence == "low",
        "confidence": confidence,
        "debug_scores": {
            "issue_score": issue_score,
            "sector_score": sector_score,
            "confidence_score": confidence_score
        }
    }
