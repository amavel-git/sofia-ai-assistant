#!/usr/bin/env python3
"""
Sofia Prompt Builder

Compatibility wrapper.

The prompt rendering implementation has moved to:

    app/renderers/prompt_renderer.py

Keep this module temporarily so older imports continue to work.
"""

from __future__ import annotations

from app.renderers.prompt_renderer import (
    PROMPT_BUILDER_VERSION,
    build_full_page_prompt,
    build_full_page_prompt_from_editorial_package,
    format_section_architecture_for_prompt,
    format_section_contracts_for_prompt,
)


if __name__ == "__main__":
    print("Prompt Builder compatibility wrapper.")
