#!/usr/bin/env python3
"""
Sofia Examiner Intent Intelligence.

Phase 11.1

Structural, language-agnostic module.

Purpose:
- Convert an examiner-originated request into a deterministic intent model.
- Keep language-specific patterns in workspace/profile JSON.
- Do not create opportunities here.
- Do not generate SEO copy here.
- Do not call AI here.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List


EXAMINER_INTENT_VERSION = "1.0"


def strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", value or "")
        if unicodedata.category(ch) != "Mn"
    )


def normalize(value: str) -> str:
    value = strip_accents(value or "").lower()
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def clean_examiner_request(text: str, profile: Dict[str, Any]) -> str:
    cleaned = text or ""

    for pattern in profile.get("command_patterns", []) or []:
        cleaned = re.sub(str(pattern), "", cleaned, flags=re.I)

    for pattern in profile.get("leading_cleanup_patterns", []) or []:
        cleaned = re.sub(str(pattern), "", cleaned, flags=re.I)

    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;-")
    return cleaned


def score_matches(text: str, items: List[Dict[str, Any]], key: str = "matches") -> Dict[str, Any]:
    haystack = normalize(text)
    best: Dict[str, Any] = {}
    best_score = 0

    for item in items or []:
        if not isinstance(item, dict):
            continue

        score = 0
        for term in item.get(key, []) or []:
            if normalize(str(term)) in haystack:
                score += 1

        if score > best_score:
            best = item
            best_score = score

    return {
        "item": best,
        "score": best_score,
    }


def confidence_from_score(score: int, profile: Dict[str, Any]) -> str:
    thresholds = profile.get("confidence_thresholds") or {}

    high = int(thresholds.get("high", 4))
    medium = int(thresholds.get("medium", 2))

    if score >= high:
        return "high"
    if score >= medium:
        return "medium"
    return "low"


def build_examiner_intent_model(
    examiner_request: str,
    *,
    profile: Dict[str, Any] | None = None,
    workspace_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Build a deterministic model of what the examiner is asking Sofia to create.

    All language-specific and workspace-specific patterns must come from profile.
    """

    profile = profile or {}
    workspace_context = workspace_context or {}

    defaults = profile.get("defaults") or {}

    cleaned_request = clean_examiner_request(examiner_request, profile)

    intent_match = score_matches(
        cleaned_request,
        profile.get("intent_patterns") or [],
    )
    issue_match = score_matches(
        cleaned_request,
        profile.get("issue_patterns") or [],
    )

    intent = intent_match.get("item") or {}
    issue = issue_match.get("item") or {}

    confidence_score = int(intent_match.get("score") or 0) + int(issue_match.get("score") or 0)
    confidence = confidence_from_score(confidence_score, profile)

    business_domain = (
        intent.get("business_domain")
        or defaults.get("business_domain")
        or "general_polygraph_services"
    )
    investigation_type = (
        issue.get("investigation_type")
        or defaults.get("investigation_type")
        or "general_polygraph_evaluation"
    )
    visitor_profile = (
        intent.get("visitor_profile")
        or defaults.get("visitor_profile")
        or "visitor_with_specific_question"
    )

    clarification_questions = []
    if confidence == "low":
        clarification_questions = (
            profile.get("clarification_questions")
            or defaults.get("clarification_questions")
            or []
        )

    return {
        "version": EXAMINER_INTENT_VERSION,
        "source": "examiner_intelligence_v1",
        "raw_request": examiner_request,
        "cleaned_request": cleaned_request,
        "workspace_id": workspace_context.get("workspace_id", ""),
        "business_domain": business_domain,
        "intent_id": intent.get("intent_id", defaults.get("intent_id", "general_request")),
        "issue_id": issue.get("issue_id", defaults.get("issue_id", "general_topic")),
        "investigation_type": investigation_type,
        "visitor_profile": visitor_profile,
        "client_problem": issue.get("client_problem") or cleaned_request,
        "decision_to_be_made": (
            issue.get("decision_to_be_made")
            or defaults.get("decision_to_be_made", "")
        ),
        "existing_evidence": issue.get("likely_evidence", []),
        "missing_information": (
            issue.get("missing_information")
            or defaults.get("missing_information", "")
        ),
        "professional_objective": (
            intent.get("professional_objective")
            or issue.get("professional_objective")
            or defaults.get("professional_objective", "")
        ),
        "commercial_intent": (
            intent.get("commercial_intent")
            or defaults.get("commercial_intent", "")
        ),
        "recommended_page_type": (
            intent.get("recommended_page_type")
            or defaults.get("recommended_page_type", "landing_page")
        ),
        "recommended_blueprint": (
            intent.get("recommended_blueprint")
            or defaults.get("recommended_blueprint", "landing_page")
        ),
        "authority_level": (
            intent.get("authority_level")
            or defaults.get("authority_level", "medium")
        ),
        "seo_intent": (
            intent.get("seo_intent")
            or defaults.get("seo_intent", "")
        ),
        "needs_clarification": confidence == "low",
        "clarification_questions": clarification_questions,
        "confidence": confidence,
        "debug_scores": {
            "intent_score": intent_match.get("score", 0),
            "issue_score": issue_match.get("score", 0),
            "confidence_score": confidence_score,
        },
    }


if __name__ == "__main__":
    import sys

    request = " ".join(sys.argv[1:]).strip()
    profile_path = Path("sites/local_sites/es/examiner_intelligence_profile.json")
    profile = load_json(profile_path)

    print(json.dumps(
        build_examiner_intent_model(
            request,
            profile=profile,
            workspace_context={"workspace_id": "local.es"},
        ),
        indent=2,
        ensure_ascii=False,
    ))
