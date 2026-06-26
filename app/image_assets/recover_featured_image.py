#!/usr/bin/env python3
"""
Recover a skipped/missing featured image without failing the draft workflow.

Use when featured_image.warning == stale_featured_image_mismatch_skipped
or when featured image preparation says generation_needed.

Steps:
1. prepare draft image assets
2. generate/optimize/register pending image jobs for this draft
3. prepare draft image assets again
4. upload featured image to WordPress
5. update WordPress draft
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(cmd):
    print("\nRunning:")
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print(f"Warning: command returned {result.returncode}. Continuing recovery flow where possible.")
    return result.returncode


def main():
    if len(sys.argv) < 3:
        print("Usage: python -m app.image_assets.recover_featured_image WORKSPACE_ID DRAFT_ID")
        raise SystemExit(1)

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]
    py = sys.executable

    print("=== Sofia: Recover Featured Image ===")
    print(f"Workspace: {workspace_id}")
    print(f"Draft: {draft_id}")

    run([py, "-m", "app.image_assets.prepare_draft_image_assets", workspace_id, draft_id])
    run([py, "-m", "app.image_assets.generate_pending_images", workspace_id, draft_id])
    run([py, "-m", "app.image_assets.image_worker", workspace_id, "--draft-id", draft_id, "--execute"])
    run([py, "-m", "app.image_assets.prepare_draft_image_assets", workspace_id, draft_id])
    run([py, "-m", "app.image_assets.upload_featured_image_to_wordpress", workspace_id, draft_id])
    run([py, "app/update_wordpress_draft.py", draft_id])

    print("\nFeatured image recovery completed.")


if __name__ == "__main__":
    main()
