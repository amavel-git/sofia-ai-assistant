#!/usr/bin/env python3
"""
Sofia Critic Decision Builder

Converts Critic Reports into deterministic Sofia decisions.

Principle:

AI agents produce observations.
Sofia Core makes decisions.

This module contains no AI logic and no localized text.
"""

from __future__ import annotations

from typing import Any, Dict, List


CRITIC_DECISION_BUILDER_VERSION = "1.0"


DEFAULT_CRITIC_POLICY = {
    "advisory_only": True,
    "allow_publication_with_warnings": True,
    "allow_publication_with_needs_repair": True,
    "block_publication_on_blocker": False,
    "auto_repair": False,
    "repair_threshold": "needs_repair",
    "notify_examiner": True,
}


SEVERITY_RANK = {
    "info": 1,
    "warning": 2,
    "needs_repair": 3,
    "blocker": 4,
}


def merge_critic_policy(
    critic_policy: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Merge workspace/job critic policy with safe defaults.
    """

    merged = dict(DEFAULT_CRITIC_POLICY)

    if isinstance(critic_policy, dict):
        merged.update(critic_policy)

    return merged


def severity_meets_threshold(
    *,
    severity: str,
    threshold: str,
) -> bool:
    """
    Return True if severity is equal to or stronger than threshold.
    """

    return SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK.get(threshold, 999)


def collect_repair_sections(
    *,
    critic_report: Dict[str, Any],
    threshold: str,
) -> List[str]:
    """
    Collect unique section IDs that meet the repair threshold.
    """

    findings = critic_report.get("findings") or []
    section_ids: List[str] = []

    for finding in findings:
        section_id = finding.get("section_id", "")
        severity = finding.get("severity", "")

        if not section_id:
            continue

        if severity_meets_threshold(
            severity=severity,
            threshold=threshold,
        ):
            if section_id not in section_ids:
                section_ids.append(section_id)

    return section_ids


def build_critic_decision(
    *,
    critic_report: Dict[str, Any],
    critic_policy: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Build a deterministic decision from a Critic Report.

    The default decision is non-blocking and advisory.
    """

    policy = merge_critic_policy(critic_policy)

    summary = critic_report.get("summary") or {}
    status = critic_report.get("status", "")

    repair_threshold = policy.get("repair_threshold", "needs_repair")

    repair_sections = collect_repair_sections(
        critic_report=critic_report,
        threshold=repair_threshold,
    )

    has_blockers = int(summary.get("blockers", 0) or 0) > 0
    has_needs_repair = int(summary.get("needs_repair", 0) or 0) > 0
    has_warnings = int(summary.get("warnings", 0) or 0) > 0

    allow_publication = True

    if has_blockers and policy.get("block_publication_on_blocker") is True:
        allow_publication = False

    if has_needs_repair and policy.get("allow_publication_with_needs_repair") is False:
        allow_publication = False

    if has_warnings and policy.get("allow_publication_with_warnings") is False:
        allow_publication = False

    if policy.get("advisory_only", True):
        allow_publication = True

    decision = "passed"

    if repair_sections:
        if policy.get("auto_repair", False):
            decision = "auto_repair_recommended"
        else:
            decision = "repair_recommended"
    elif has_warnings:
        decision = "warnings_only"
    elif status == "passed":
        decision = "passed"

    examiner_attention = bool(
        policy.get("notify_examiner", True)
        and (
            has_blockers
            or has_needs_repair
            or has_warnings
        )
    )

    return {
        "version": CRITIC_DECISION_BUILDER_VERSION,
        "draft_id": critic_report.get("draft_id", ""),
        "workspace_id": critic_report.get("workspace_id", ""),
        "page_type": critic_report.get("page_type", ""),

        "decision": decision,
        "allow_publication": allow_publication,
        "advisory_only": bool(policy.get("advisory_only", True)),

        "repair_sections": repair_sections,
        "auto_repair": bool(policy.get("auto_repair", False)),

        "examiner_attention": examiner_attention,

        "critic_status": status,
        "critic_summary": summary,
        "policy": policy,
    }


def summarize_critic_decision(
    critic_decision: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return a compact decision summary.
    """

    return {
        "version": critic_decision.get("version", ""),
        "draft_id": critic_decision.get("draft_id", ""),
        "workspace_id": critic_decision.get("workspace_id", ""),
        "decision": critic_decision.get("decision", ""),
        "allow_publication": critic_decision.get("allow_publication", True),
        "advisory_only": critic_decision.get("advisory_only", True),
        "repair_sections": critic_decision.get("repair_sections", []),
        "examiner_attention": critic_decision.get("examiner_attention", False),
    }


if __name__ == "__main__":
    print("Critic Decision Builder module.")
