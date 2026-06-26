#!/usr/bin/env python3
"""
Sofia Critic Agent

Phase 6.2A

The Critic Agent evaluates generated content against the Editorial Package.

This first version is deterministic scaffolding only.

It does not call an LLM.
It does not rewrite content.
It only defines the structured finding/report format.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


CRITIC_AGENT_VERSION = "1.0"


VALID_SEVERITIES = {
    "info",
    "warning",
    "needs_repair",
    "blocker",
}


VALID_FINDING_TYPES = {
    "purpose_not_fulfilled",
    "writing_objective_not_fulfilled",
    "visitor_state_mismatch",
    "transition_issue",
    "heading_issue",
    "repetition",
    "internal_link_issue",
    "cta_timing_issue",
    "semantic_inconsistency",
    "image_section_mismatch",
    "conversion_flow_issue",
    "content_quality",
    "editorial_quality",
    "missing_section",
    "section_too_short",
    "other",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_empty_critic_report(
    *,
    editorial_package: Dict[str, Any],
    generated_html: str = "",
) -> Dict[str, Any]:
    """
    Build an empty critic report.

    This is the stable structure future Critic Agent logic will populate.
    """

    section_contracts = (
        editorial_package
        .get("section_contracts", {})
        .get("section_contracts", [])
    )

    return {
        "version": CRITIC_AGENT_VERSION,
        "created_at": utc_now_iso(),

        "draft_id": editorial_package.get("draft_id", ""),
        "workspace_id": editorial_package.get("workspace_id", ""),
        "page_type": editorial_package.get("page_type", ""),

        "input_summary": {
            "section_contract_count": len(section_contracts),
            "generated_html_length": len(generated_html or ""),
        },

        "status": "not_evaluated",

        "summary": {
            "total_findings": 0,
            "blockers": 0,
            "needs_repair": 0,
            "warnings": 0,
            "info": 0,
            "sections_with_findings": 0,
        },

        "findings": [],
    }


def add_critic_finding(
    *,
    critic_report: Dict[str, Any],
    section_id: str,
    section_type: str = "",
    finding_type: str,
    severity: str,
    message: str,
    evidence: str = "",
    recommendation: str = "",
) -> Dict[str, Any]:
    """
    Add one structured finding to a critic report.
    """

    if severity not in VALID_SEVERITIES:
        severity = "warning"

    if finding_type not in VALID_FINDING_TYPES:
        finding_type = "other"

    finding = {
        "section_id": section_id,
        "section_type": section_type,
        "finding_type": finding_type,
        "severity": severity,
        "message": message,
        "evidence": evidence,
        "recommendation": recommendation,
    }

    critic_report.setdefault("findings", []).append(finding)
    update_critic_summary(critic_report)

    return critic_report


def update_critic_summary(
    critic_report: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Recalculate critic report summary after findings are added.
    """

    findings: List[Dict[str, Any]] = critic_report.get("findings") or []

    sections_with_findings = {
        finding.get("section_id", "")
        for finding in findings
        if finding.get("section_id")
    }

    summary = {
        "total_findings": len(findings),
        "blockers": len([
            finding for finding in findings
            if finding.get("severity") == "blocker"
        ]),
        "needs_repair": len([
            finding for finding in findings
            if finding.get("severity") == "needs_repair"
        ]),
        "warnings": len([
            finding for finding in findings
            if finding.get("severity") == "warning"
        ]),
        "info": len([
            finding for finding in findings
            if finding.get("severity") == "info"
        ]),
        "sections_with_findings": len(sections_with_findings),
    }

    critic_report["summary"] = summary

    if summary["blockers"] > 0:
        critic_report["status"] = "blocked"
    elif summary["needs_repair"] > 0:
        critic_report["status"] = "needs_repair"
    elif summary["warnings"] > 0:
        critic_report["status"] = "warnings"
    else:
        critic_report["status"] = "passed"

    return critic_report


def summarize_critic_report(
    critic_report: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return a compact summary of the critic report.
    """

    return {
        "version": critic_report.get("version", ""),
        "draft_id": critic_report.get("draft_id", ""),
        "workspace_id": critic_report.get("workspace_id", ""),
        "page_type": critic_report.get("page_type", ""),
        "status": critic_report.get("status", ""),
        "summary": critic_report.get("summary", {}),
    }


if __name__ == "__main__":
    print("Critic Agent module.")


def normalize_ai_critic_findings(
    ai_result: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Normalize raw AI critic JSON into safe Sofia finding objects.

    This function is defensive:
    - invalid severities become warnings
    - invalid finding types become other
    - missing fields become empty strings
    """

    raw_findings = ai_result.get("findings") or []

    if not isinstance(raw_findings, list):
        return []

    normalized: List[Dict[str, Any]] = []

    for item in raw_findings:
        if not isinstance(item, dict):
            continue

        severity = item.get("severity", "warning")
        if severity not in VALID_SEVERITIES:
            severity = "warning"

        finding_type = item.get("finding_type", "other")
        if finding_type not in VALID_FINDING_TYPES:
            finding_type = "other"

        normalized.append({
            "section_id": str(item.get("section_id", "") or ""),
            "section_type": str(item.get("section_type", "") or ""),
            "finding_type": finding_type,
            "severity": severity,
            "message": str(item.get("message", "") or ""),
            "evidence": str(item.get("evidence", "") or ""),
            "recommendation": str(item.get("recommendation", "") or ""),
        })

    return normalized


def build_critic_report_from_ai_result(
    *,
    editorial_package: Dict[str, Any],
    generated_html: str,
    ai_result: Dict[str, Any],
    advisory_only: bool = True,
) -> Dict[str, Any]:
    """
    Build a Sofia critic report from AI-produced structured findings.

    advisory_only=True prevents the Critic from blocking generation.
    In advisory mode, AI blocker findings are downgraded to needs_repair.
    """

    critic_report = build_empty_critic_report(
        editorial_package=editorial_package,
        generated_html=generated_html,
    )

    normalized_findings = normalize_ai_critic_findings(ai_result)

    for finding in normalized_findings:
        severity = finding["severity"]

        if advisory_only and severity == "blocker":
            severity = "needs_repair"

        add_critic_finding(
            critic_report=critic_report,
            section_id=finding["section_id"],
            section_type=finding["section_type"],
            finding_type=finding["finding_type"],
            severity=severity,
            message=finding["message"],
            evidence=finding["evidence"],
            recommendation=finding["recommendation"],
        )

    critic_report["advisory_only"] = advisory_only

    if advisory_only and critic_report.get("status") == "blocked":
        critic_report["status"] = "needs_repair"

    return critic_report


def execute_critic_task_advisory(
    *,
    editorial_task: Dict[str, Any],
    ai_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute an advisory Critic task using already-produced AI JSON.

    This does not call an LLM.
    It converts AI structured output into Sofia's critic report format.

    The Critic is advisory by default and must not stop draft generation.
    """

    if editorial_task.get("task_type") != "critique_page":
        raise ValueError("execute_critic_task_advisory requires a critique_page task.")

    editorial_package = editorial_task.get("editorial_package") or {}
    payload = editorial_task.get("payload") or {}
    generated_html = payload.get("generated_html", "")

    return build_critic_report_from_ai_result(
        editorial_package=editorial_package,
        generated_html=generated_html,
        ai_result=ai_result,
        advisory_only=True,
    )


def extract_json_object_from_text(text: str) -> Dict[str, Any]:
    """
    Extract the first JSON object from model output.

    Local models may return prose before or after JSON.
    This helper attempts to recover the first top-level JSON object.

    Returns an empty dict if parsing fails.
    """

    import json

    if not text:
        return {}

    stripped = text.strip()

    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
        return {}
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")

    if start == -1 or end == -1 or end <= start:
        return {}

    candidate = stripped[start:end + 1]

    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
        return {}
    except json.JSONDecodeError:
        return {}


def execute_critic_task_from_model_text_advisory(
    *,
    editorial_task: Dict[str, Any],
    model_text: str,
) -> Dict[str, Any]:
    """
    Execute an advisory Critic task from raw model text.

    This function is intentionally non-blocking:
    malformed model output becomes an empty critic report with a warning.
    """

    ai_result = extract_json_object_from_text(model_text)

    if not ai_result:
        ai_result = {
            "findings": [
                {
                    "section_id": "",
                    "section_type": "",
                    "finding_type": "other",
                    "severity": "warning",
                    "message": "Critic model output could not be parsed as JSON.",
                    "evidence": "",
                    "recommendation": "Review critic model output manually if needed.",
                }
            ]
        }

    return execute_critic_task_advisory(
        editorial_task=editorial_task,
        ai_result=ai_result,
    )
