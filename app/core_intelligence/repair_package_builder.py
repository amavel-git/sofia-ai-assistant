#!/usr/bin/env python3
"""
Sofia Repair Package Builder

Builds deterministic Repair Packages for the Repair Agent.

The Repair Package converts Critic output into
section-level repair work items.

No AI logic belongs in this module.
"""

from __future__ import annotations

from typing import Any, Dict, List


REPAIR_PACKAGE_BUILDER_VERSION = "1.0"


def build_repair_package(
    *,
    editorial_package: Dict[str, Any],
    critic_report: Dict[str, Any],
    critic_decision: Dict[str, Any],
    generated_html: str,
) -> Dict[str, Any]:
    """
    Build a deterministic Repair Package.

    Initial implementation:
    - one repair item per section
    - preserves all findings
    - leaves prioritization deterministic
    """

    section_contracts = (
        editorial_package
        .get("section_contracts", {})
        .get("section_contracts", [])
    )

    contract_lookup = {
        contract.get("section_id"): contract
        for contract in section_contracts
    }

    findings = critic_report.get("findings") or []

    repair_sections: List[Dict[str, Any]] = []

    for section_id in critic_decision.get("repair_sections", []):

        section_findings = [
            finding
            for finding in findings
            if finding.get("section_id") == section_id
        ]

        repair_sections.append({
            "section_id": section_id,
            "section_contract": contract_lookup.get(section_id, {}),
            "generated_html": generated_html,
            "supporting_findings": section_findings,
            "repair_priority": "normal",
            "repair_scope": "section_only",
            "preserve_navigation": True,
            "preserve_heading": False,
        })

    return {
        "version": REPAIR_PACKAGE_BUILDER_VERSION,
        "repair_sections": repair_sections,
    }


if __name__ == "__main__":
    print("Repair Package Builder module.")
