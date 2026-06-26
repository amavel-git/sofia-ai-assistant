#!/usr/bin/env python3
"""
Sofia Assemble WordPress Content

Deterministic post-generation assembly step.

Purpose:
- Clean generated HTML
- Inject internal links
- Apply reusable Gutenberg blocks
- Apply Yoast FAQ block formatting
- Save final assembled HTML before validation/upload

No AI calls.
No WordPress API calls.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def run_step(command: list[str], required_text: str | None = None) -> str:
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
    )

    output = (result.stdout or "") + (result.stderr or "")

    if result.returncode != 0:
        print(output)
        raise RuntimeError(f"Step failed: {' '.join(command)}")

    if required_text and required_text not in output:
        print(output)
        raise RuntimeError(
            f"Step did not confirm expected output: {required_text}"
        )

    print(output.strip())
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assemble Sofia generated HTML into final WordPress-ready content."
    )
    parser.add_argument("workspace_id", help="Workspace ID, e.g. local.es")
    parser.add_argument("draft_id", help="Draft ID, e.g. DRAFT-0001")
    parser.add_argument(
        "--skip-links",
        action="store_true",
        help="Skip internal link injection.",
    )

    args = parser.parse_args()

    workspace_id = args.workspace_id
    draft_id = args.draft_id

    print("=== Sofia: Assemble WordPress Content ===\n")
    print(f"Workspace: {workspace_id}")
    print(f"Draft: {draft_id}\n")

    run_step(
        [
            sys.executable,
            "app/clean_generated_html.py",
            workspace_id,
            draft_id,
        ],
        required_text="Content cleaned successfully.",
    )

    if not args.skip_links:
        link_output = run_step(
            [
                sys.executable,
                "app/inject_internal_links.py",
                draft_id,
            ]
        )

        if (
            "Internal links added" not in link_output
            and "No suitable links found" not in link_output
            and "No internal links were inserted" not in link_output
            and "Draft must be in one of these statuses" not in link_output
        ):
            raise RuntimeError("Internal link step returned unexpected output.")

        if "Draft must be in one of these statuses" in link_output:
            print("Internal link injection skipped because draft is already assembled. Continuing.")

        run_step(
            [
                sys.executable,
                "app/clean_generated_html.py",
                workspace_id,
                draft_id,
            ],
            required_text="Content cleaned successfully.",
        )

    run_step(
        [
            sys.executable,
            "app/apply_gutenberg_blocks.py",
            workspace_id,
            draft_id,
        ],
        required_text=None,
    )

    print("\nWordPress content assembled successfully.")


if __name__ == "__main__":
    main()
