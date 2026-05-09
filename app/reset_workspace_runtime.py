#!/usr/bin/env python3
"""
Sofia Runtime Reset Helper

Purpose:
- Reset runtime/test workflow data for one workspace.
- Keep structural workspace files intact.
- Useful before real Telegram end-to-end tests.

This script does NOT delete:
- site_structure.json
- country_profile.json
- language_profile.json
- local_topic_overrides.json
- internal_link_rules.json
- internal_link_suggestions.json
- market_intelligence.json
- workspace configuration files

It resets:
- workspace external opportunities
- workspace local review queue
- workspace draft registry
- workspace job registry
- workspace content inventory
- workspace draft/content memory runtime entries
- global content_intake entries for the selected workspace only
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
WORKSPACES_FILE = ROOT_DIR / "data" / "workspaces.json"
GLOBAL_INTAKE_FILE = ROOT_DIR / "sites" / "content_intake.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_json(path: Path, default):
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_workspace(workspaces_data, workspace_id: str):
    for workspace in workspaces_data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace

    return None


def get_workspace_path(workspace) -> Path:
    folder_path = workspace.get("folder_path") or workspace.get("workspace_path")

    if not folder_path:
        raise RuntimeError(
            "Workspace is missing folder_path/workspace_path in data/workspaces.json"
        )

    path = Path(folder_path)

    if not path.is_absolute():
        path = ROOT_DIR / path

    return path


def reset_external_opportunities(workspace_path: Path) -> None:
    path = workspace_path / "external_opportunities.json"

    data = {
        "version": "1.0",
        "last_reset_at": now_iso(),
        "opportunities": [],
    }

    save_json(path, data)
    print(f"Reset: {path}")


def reset_review_queue(workspace, workspace_path: Path) -> None:
    review_queue_path = workspace.get("review_queue_path")

    if review_queue_path:
        path = Path(review_queue_path)
        if not path.is_absolute():
            path = ROOT_DIR / path
    else:
        path = workspace_path / "local_review_queue.json"

    data = {
        "version": "1.0",
        "last_reset_at": now_iso(),
        "review_items": [],
    }

    save_json(path, data)
    print(f"Reset: {path}")


def reset_draft_registry(workspace_id: str, workspace_path: Path) -> None:
    path = workspace_path / "draft_registry.json"

    data = {
        "version": "1.0",
        "scope": "workspace",
        "workspace_id": workspace_id,
        "last_reset_at": now_iso(),
        "drafts": [],
    }

    save_json(path, data)
    print(f"Reset: {path}")


def reset_job_registry(workspace_id: str, workspace_path: Path) -> None:
    path = workspace_path / "job_registry.json"

    data = {
        "version": "1.0",
        "workspace_id": workspace_id,
        "last_reset_at": now_iso(),
        "last_updated": now_iso(),
        "jobs": [],
    }

    save_json(path, data)
    print(f"Reset: {path}")


def reset_content_inventory(workspace_id: str, workspace_path: Path) -> None:
    path = workspace_path / "content_inventory.json"

    data = {
        "version": "1.0",
        "workspace_id": workspace_id,
        "last_reset_at": now_iso(),
        "items": [],
    }

    save_json(path, data)
    print(f"Reset: {path}")


def reset_site_content_memory(workspace_id: str, workspace_path: Path) -> None:
    path = workspace_path / "site_content_memory.json"

    existing = load_json(path, {})

    data = {
        "version": existing.get("version", "1.0"),
        "workspace_id": workspace_id,
        "last_reset_at": now_iso(),

        # Runtime/generated memory
        "keyword_index": [],
        "draft_content": [],
        "published_content": [],

        # Keep optional non-runtime notes if they exist
        "notes": existing.get("notes", ""),
        "manual_topics_to_preserve": existing.get("manual_topics_to_preserve", []),
    }

    save_json(path, data)
    print(f"Reset: {path}")


def reset_global_intake_for_workspace(workspace_id: str) -> None:
    data = load_json(GLOBAL_INTAKE_FILE, {"content_ideas": []})

    content_ideas = data.get("content_ideas", [])

    if not isinstance(content_ideas, list):
        content_ideas = []

    before = len(content_ideas)

    kept = [
        item for item in content_ideas
        if item.get("workspace_id") != workspace_id
    ]

    removed = before - len(kept)

    data["content_ideas"] = kept
    data["last_runtime_reset_at"] = now_iso()

    save_json(GLOBAL_INTAKE_FILE, data)

    print(f"Reset intake entries for workspace: {workspace_id}")
    print(f"Removed intake items: {removed}")
    print(f"Updated: {GLOBAL_INTAKE_FILE}")


def main() -> None:
    print("=== Sofia: Reset Workspace Runtime Data ===\n")

    if len(sys.argv) != 2:
        print("Usage:")
        print("python app/reset_workspace_runtime.py local.ao")
        return

    workspace_id = sys.argv[1].strip()

    workspaces_data = load_json(WORKSPACES_FILE, {"workspaces": []})
    workspace = find_workspace(workspaces_data, workspace_id)

    if not workspace:
        print(f"ERROR: Workspace not found: {workspace_id}")
        return

    workspace_path = get_workspace_path(workspace)

    print(f"Workspace: {workspace_id}")
    print(f"Workspace path: {workspace_path}\n")

    reset_external_opportunities(workspace_path)
    reset_review_queue(workspace, workspace_path)
    reset_draft_registry(workspace_id, workspace_path)
    reset_job_registry(workspace_id, workspace_path)
    reset_content_inventory(workspace_id, workspace_path)
    reset_site_content_memory(workspace_id, workspace_path)
    reset_global_intake_for_workspace(workspace_id)

    print("\nRuntime reset completed.")
    print("Structural files were not deleted.")


if __name__ == "__main__":
    main()