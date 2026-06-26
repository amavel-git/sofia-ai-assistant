#!/usr/bin/env python3
"""
Sofia Editorial Task Builder

Builds deterministic task objects for Editorial AI Agents.

Tasks are the execution interface for agents such as:

- Writer Agent
- Critic Agent
- Repair Agent
- future Maintenance Agent

This module contains no AI logic and no localized text.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4


EDITORIAL_TASK_BUILDER_VERSION = "1.0"


VALID_TASK_TYPES = {
    "write_page",
    "critique_page",
    "repair_sections",
    "maintain_page",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_editorial_task(
    *,
    task_type: str,
    editorial_package: Dict[str, Any],
    payload: Dict[str, Any] | None = None,
    expected_output: str = "",
) -> Dict[str, Any]:
    """
    Build a generic Editorial AI task.
    """

    if task_type not in VALID_TASK_TYPES:
        raise ValueError(f"Unsupported editorial task type: {task_type}")

    return {
        "version": EDITORIAL_TASK_BUILDER_VERSION,
        "task_id": f"EDITORIAL-TASK-{uuid4().hex[:8].upper()}",
        "task_type": task_type,
        "created_at": utc_now_iso(),

        "draft_id": editorial_package.get("draft_id", ""),
        "workspace_id": editorial_package.get("workspace_id", ""),
        "page_type": editorial_package.get("page_type", ""),

        "editorial_package": editorial_package,
        "payload": payload or {},

        "expected_output": expected_output,
        "status": "created",
    }


def build_writer_task(
    *,
    editorial_package: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build a task for full-page writing.
    """

    return build_editorial_task(
        task_type="write_page",
        editorial_package=editorial_package,
        payload={},
        expected_output="generated_html",
    )


def build_critic_task(
    *,
    editorial_package: Dict[str, Any],
    generated_html: str,
) -> Dict[str, Any]:
    """
    Build a task for page critique.
    """

    return build_editorial_task(
        task_type="critique_page",
        editorial_package=editorial_package,
        payload={
            "generated_html": generated_html,
        },
        expected_output="critic_report",
    )


def build_repair_task(
    *,
    editorial_package: Dict[str, Any],
    generated_html: str,
    critic_report: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build a task for section repair.
    """

    return build_editorial_task(
        task_type="repair_sections",
        editorial_package=editorial_package,
        payload={
            "generated_html": generated_html,
            "critic_report": critic_report,
        },
        expected_output="repaired_html",
    )


def summarize_editorial_task(
    editorial_task: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return a compact task summary.
    """

    return {
        "version": editorial_task.get("version", ""),
        "task_id": editorial_task.get("task_id", ""),
        "task_type": editorial_task.get("task_type", ""),
        "draft_id": editorial_task.get("draft_id", ""),
        "workspace_id": editorial_task.get("workspace_id", ""),
        "page_type": editorial_task.get("page_type", ""),
        "expected_output": editorial_task.get("expected_output", ""),
        "status": editorial_task.get("status", ""),
    }


if __name__ == "__main__":
    print("Editorial Task Builder module.")
