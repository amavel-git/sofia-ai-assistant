#!/usr/bin/env python3
"""
Sofia Writer Agent

Phase 7 compatible.

The Writer Agent coordinates writing.

Responsibilities:

- consume Sofia Core Intelligence
- build the Editorial Package
- invoke the Prompt Renderer
- later invoke the selected LLM

The Writer Agent contains no business logic.
"""

from __future__ import annotations

from typing import Any, Dict

try:
    from app.core_intelligence.editorial_package_builder import (
        build_editorial_package,
        summarize_editorial_package,
    )
    from app.renderers.prompt_renderer import (
        build_full_page_prompt,
        build_full_page_prompt_from_editorial_package,
    )
except ModuleNotFoundError:
    from core_intelligence.editorial_package_builder import (
        build_editorial_package,
        summarize_editorial_package,
    )
    from renderers.prompt_renderer import (
        build_full_page_prompt,
        build_full_page_prompt_from_editorial_package,
    )


WRITER_AGENT_VERSION = "2.2"


def build_full_page_writer_prompt(
    *,
    base_prompt: str,
    content_architecture: Dict[str, Any],
    section_contracts: Dict[str, Any] | None = None,
) -> str:
    """
    Build the prompt used by the Writer.

    New code follows the Editorial Package path.

    The legacy Prompt Builder remains available only for backward
    compatibility during the migration.
    """

    if section_contracts is None:
        return build_full_page_prompt(
            base_prompt=base_prompt,
            content_architecture=content_architecture,
        )

    editorial_package = build_editorial_package(
        content_architecture=content_architecture,
        section_contracts=section_contracts,
    )

    return build_full_page_prompt_from_editorial_package(
        base_prompt=base_prompt,
        editorial_package=editorial_package,
    )


def summarize_writer_input(
    content_architecture: Dict[str, Any],
    section_contracts: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Return a lightweight summary of the Writer input.

    Signature accepts positional content_architecture for legacy callers.
    """

    if section_contracts is None:
        section_contracts = {}

    editorial_package = build_editorial_package(
        content_architecture=content_architecture,
        section_contracts=section_contracts,
    )

    summary = summarize_editorial_package(editorial_package)
    summary["writer_agent_version"] = WRITER_AGENT_VERSION

    return summary


if __name__ == "__main__":
    print("Writer Agent module.")
