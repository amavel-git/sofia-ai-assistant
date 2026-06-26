#!/usr/bin/env python3
"""
Sofia Editorial Critic AI Pipeline Test

Standalone test. Does not touch production generation.

Run from Sofia root:

    PYTHONPATH=. python tests/editorial/test_critic_pipeline_ai.py

Optional:

    OLLAMA_MODEL=qwen2.5:14b PYTHONPATH=. python tests/editorial/test_critic_pipeline_ai.py
"""

from __future__ import annotations

import json
import os
import urllib.request
from pprint import pprint

from app.core_intelligence.editorial_package_builder import build_editorial_package
from app.agents.editorial_task_builder import build_critic_task
from app.renderers.editorial_renderer import render_critic_prompt
from app.agents.critic_agent import (
    execute_critic_task_from_model_text_advisory,
    summarize_critic_report,
)
from app.core_intelligence.critic_decision_builder import (
    build_critic_decision,
    summarize_critic_decision,
)


OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")


def call_ollama(prompt: str) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_ctx": 8192,
        },
    }

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.loads(response.read().decode("utf-8"))

    return result.get("response", "")


def main() -> None:
    content_architecture = {
        "draft_id": "DRAFT-TEST-CRITIC-AI",
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
                    "visitor_state": "curious but skeptical",
                    "conversion_stage": "trust_building",
                    "content_priority": "critical",
                    "topic_focus": "clear explanation of process and limits",
                    "cta_intent": "none",
                    "internal_link_intent": "none",
                    "must_avoid": [
                        "absolute claims",
                        "guaranteed accuracy",
                        "legal certainty"
                    ],
                },
                "transition": {
                    "previous_section_id": "problem",
                    "previous_section_type": "problem_context",
                    "next_section_id": "limitations",
                    "next_section_type": "limitations",
                },
                "images": [],
                "navigation": {},
            }
        ]
    }

    generated_html = """
    <h2>Methodology</h2>
    <p>
    Our polygraph method is advanced and helps identify the truth.
    It is useful in many cases and can help companies and private clients
    decide what happened.
    </p>
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

    print("\nCALLING OLLAMA")
    print(f"Model: {OLLAMA_MODEL}")

    model_text = call_ollama(critic_prompt)

    print("\nMODEL OUTPUT PREVIEW")
    print(model_text[:1200])

    critic_report = execute_critic_task_from_model_text_advisory(
        editorial_task=critic_task,
        model_text=model_text,
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
