#!/usr/bin/env python3
"""
Sofia Editorial Package Builder

Combines deterministic Core Intelligence outputs into a single
Editorial Package consumed by AI agents.

This module contains no AI logic, no prompt logic, and no localized text.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


EDITORIAL_PACKAGE_VERSION = "1.0"


def build_editorial_package(
    *,
    content_architecture: Dict[str, Any],
    section_contracts: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build the stable interface between Sofia Core Intelligence
    and the Editorial AI layer.
    """

    return {
        "version": EDITORIAL_PACKAGE_VERSION,
        "draft_id": content_architecture.get("draft_id", ""),
        "workspace_id": content_architecture.get("workspace_id", ""),
        "page_type": content_architecture.get("page_type", ""),
        "content_architecture": deepcopy(content_architecture),
        "section_contracts": deepcopy(section_contracts),
    }


def summarize_editorial_package(
    editorial_package: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return a lightweight debug summary of the editorial package.
    """

    contracts = (
        editorial_package
        .get("section_contracts", {})
        .get("section_contracts", [])
    )

    architecture = editorial_package.get("content_architecture", {})

    return {
        "version": editorial_package.get("version", ""),
        "draft_id": editorial_package.get("draft_id", ""),
        "workspace_id": editorial_package.get("workspace_id", ""),
        "page_type": editorial_package.get("page_type", ""),
        "section_count": len(contracts),
        "critical_sections": len([
            c for c in contracts
            if (c.get("writing", {}).get("content_priority") == "critical")
        ]),
        "image_sections": len([
            c for c in contracts
            if c.get("images")
        ]),
        "navigation_sections": len([
            c for c in contracts
            if (c.get("navigation", {}).get("navigation_goal"))
        ]),
        "architecture_sections": len(
            architecture.get("sections", [])
        ),
    }


if __name__ == "__main__":
    print("Editorial Package Builder module.")
