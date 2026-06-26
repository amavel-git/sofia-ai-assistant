#!/usr/bin/env python3
"""
Sofia Critic Empty Findings Test

Ensures clean critic output produces a passed advisory report.
"""

from __future__ import annotations

from pprint import pprint

from app.core_intelligence.editorial_package_builder import build_editorial_package
from app.agents.editorial_task_builder import build_critic_task
from app.agents.critic_agent import (
    execute_critic_task_advisory,
    summarize_critic_report,
)
from app.core_intelligence.critic_decision_builder import (
    build_critic_decision,
    summarize_critic_decision,
)


def main() -> None:
    editorial_package = build_editorial_package(
        content_architecture={
            "draft_id": "DRAFT-TEST-CLEAN",
            "workspace_id": "local.test",
            "page_type": "test_page",
            "sections": [],
        },
        section_contracts={
            "section_contracts": []
        },
    )

    critic_task = build_critic_task(
        editorial_package=editorial_package,
        generated_html="<h2>Test</h2><p>Good content.</p>",
    )

    critic_report = execute_critic_task_advisory(
        editorial_task=critic_task,
        ai_result={"findings": []},
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
