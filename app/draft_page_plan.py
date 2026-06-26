#!/usr/bin/env python3
"""
Attach locked page_plan objects to Sofia draft records.

This module does not generate content.
It only ensures draft metadata can carry the deterministic page_plan.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from page_plan_builder import build_page_plan


SOFIA_ROOT = Path(__file__).resolve().parents[1]
LOCAL_SITES_ROOT = SOFIA_ROOT / "sites" / "local_sites"


def workspace_slug(workspace_id: str) -> str:
    value = str(workspace_id or "").strip()
    if value.startswith("local."):
        return value.split(".", 1)[1]
    return value


def workspace_path(workspace_id: str) -> Path:
    return LOCAL_SITES_ROOT / workspace_slug(workspace_id)


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def get_draft_registry_path(workspace_id: str) -> Path:
    return workspace_path(workspace_id) / "draft_registry.json"


def find_draft_record(registry: Dict[str, Any], draft_id: str) -> Dict[str, Any] | None:
    drafts = registry.get("drafts")

    if isinstance(drafts, list):
        for draft in drafts:
            if draft.get("draft_id") == draft_id or draft.get("id") == draft_id:
                return draft

    if isinstance(drafts, dict):
        return drafts.get(draft_id)

    if draft_id in registry and isinstance(registry[draft_id], dict):
        return registry[draft_id]

    return None


def attach_page_plan_to_draft_record(
    draft: Dict[str, Any],
    workspace_id: str,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """
    Attach page_plan to a draft record.

    Existing locked page_plan is preserved unless overwrite=True.
    """
    existing_plan = draft.get("page_plan")

    if existing_plan and existing_plan.get("locked") and not overwrite:
        return draft

    source = {
        **draft,
        "source_type": "draft",
        "draft_id": draft.get("draft_id") or draft.get("id", ""),
        "opportunity_id": draft.get("opportunity_id", ""),
        "intake_id": draft.get("intake_id", ""),
        "title": draft.get("title") or draft.get("headline") or draft.get("topic") or "",
        "topic": draft.get("topic") or draft.get("idea") or "",
        "topic_key": draft.get("topic_key") or draft.get("taxonomy_topic") or "",
        "target_keyword": draft.get("target_keyword") or draft.get("focus_keyphrase") or "",
        "page_type": draft.get("page_type") or draft.get("content_type") or "",
        "requested_page_type": draft.get("requested_page_type") or draft.get("page_type") or "",
    }

    draft["page_plan"] = build_page_plan(
        source=source,
        workspace_id=workspace_id,
    )

    draft["page_plan_status"] = "locked"

    return draft


def attach_page_plan_to_draft(
    workspace_id: str,
    draft_id: str,
    overwrite: bool = False,
) -> Dict[str, Any]:
    registry_path = get_draft_registry_path(workspace_id)
    registry = load_json(registry_path)

    draft = find_draft_record(registry, draft_id)

    if not draft:
        raise ValueError(f"Draft not found: {draft_id} in {registry_path}")

    attach_page_plan_to_draft_record(
        draft=draft,
        workspace_id=workspace_id,
        overwrite=overwrite,
    )

    save_json(registry_path, registry)

    return draft


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Attach page_plan to a draft.")
    parser.add_argument("--workspace", required=True, help="Workspace ID, e.g. local.es")
    parser.add_argument("--draft-id", required=True, help="Draft ID, e.g. DRAFT-0001")
    parser.add_argument("--overwrite", action="store_true")

    args = parser.parse_args()

    updated = attach_page_plan_to_draft(
        workspace_id=args.workspace,
        draft_id=args.draft_id,
        overwrite=args.overwrite,
    )

    print("Attached page_plan")
    print("draft_id:", updated.get("draft_id") or updated.get("id"))
    print("blueprint_id:", updated.get("page_plan", {}).get("blueprint_id"))
    print("locked:", updated.get("page_plan", {}).get("locked"))