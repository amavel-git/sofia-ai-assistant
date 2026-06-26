#!/usr/bin/env python3
"""
Sofia Editorial Critic Pipeline Test

This test exercises the Phase 6 critic pipeline without calling an LLM.

Pipeline:

Editorial Package
↓
Critic Task
↓
Simulated AI JSON
↓
Critic Report
↓
Critic Decision

Run from Sofia root:

    python tests/editorial/test_critic_pipeline.py
"""

from __future__ import annotations

from pprint import pprint

from app.core_intelligence.editorial_package_builder import build_editorial_package
from app.agents.editorial_task_builder import build_critic_task
from app.agents.critic_agent import (
    execute_critic_task_advisory,
    summarize_critic_report,
)
from app.renderers.editorial_renderer import render_critic_prompt
from app.core_intelligence.critic_decision_builder import (
    build_critic_decision,
    summarize_critic_decision,
)


def main() -> None:
    content_architecture = {
        "draft_id": "DRAFT-TEST-CRITIC",
        "workspace_id": "local.test",
        "page_type": "test_page",
        "sections": [],
    }

    section_contracts = {
        "section_contracts": [
            {
                "section_id": "methodology",
                "section_type": "methodology",
                "writing": {
                    "purpose": "Explain the method clearly.",
                    "objective": "Build trust.",
                    "visitor_state": "curious",
                    "content_priority": "critical",
                },
            }
        ]
    }

    generated_html = """
    <h2>Methodology</h2>
    <p>This section is too generic and does not explain the method clearly.</p>
    """

    editorial_package = build_editorial_package(
        content_architecture=content_architecture,
        section_contracts=section_contracts,
    )

    critic_task = build_critic_task(
        editorial_package=editorial_package,
        generated_html=generated_html,
    )

    critic_prompt = render_critic_prompt(
        editorial_task=critic_task,
    )

    print("\nCRITIC PROMPT PREVIEW")
    print(critic_prompt[:800])

    simulated_ai_result = {
        "findings": [
            {
                "section_id": "methodology",
                "section_type": "methodology",
                "finding_type": "writing_objective_not_fulfilled",
                "severity": "needs_repair",
                "message": "The section does not sufficiently build trust.",
                "evidence": "The content is generic and does not explain the method clearly.",
                "recommendation": "Expand the section with clearer process explanation.",
            }
        ]
    }

    critic_report = execute_critic_task_advisory(
        editorial_task=critic_task,
        ai_result=simulated_ai_result,
    )

    critic_decision = build_critic_decision(
        critic_report=critic_report,
    )

    print("\nCRITIC REPORT SUMMARY")
    pprint(summarize_critic_report(critic_report))

    print("\nCRITIC DECISION SUMMARY")
    pprint(summarize_critic_decision(critic_decision))


if __name__ == "__main__":
    main()
