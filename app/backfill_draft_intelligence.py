#!/usr/bin/env python3
"""
Backfill Sofia draft intelligence from matching intake records.

Purpose:
- Allows testing downstream intelligence patches on existing drafts.
- Does not create WordPress pages.
- Does not regenerate content.
- Copies opportunity_intelligence/intake_intelligence and related fields
  from intake into the matching workspace draft.

Usage:
python app/backfill_draft_intelligence.py local.es DRAFT-0011
python app/backfill_draft_intelligence.py local.es DRAFT-0011 --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

from workspace_paths import get_workspace_draft_registry_path
from opportunity_intelligence import analyze_opportunity


ROOT = Path(__file__).resolve().parents[1]
GLOBAL_INTAKE_PATH = ROOT / "sites" / "content_intake.json"


COPY_FIELDS = [
    "normalized_title",
    "page_h1",
    "issue",
    "sector",
    "sector_id",
    "service_angle",
    "topic_family",
    "visual_topic_family",
    "recommended_seo_title",
    "recommended_meta_description",
    "opportunity_intelligence",
    "intake_intelligence",
]


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_draft(registry: Dict[str, Any], draft_id: str) -> Optional[Dict[str, Any]]:
    for draft in registry.get("drafts", []):
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def find_matching_intake(intake_data: Dict[str, Any], draft: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    draft_intake_id = draft.get("intake_id")
    if draft_intake_id:
        for item in intake_data.get("content_ideas", []):
            if item.get("intake_id") == draft_intake_id:
                return item

    # Fallback match by target keyword / slug.
    draft_keyword = str(draft.get("target_keyword") or draft.get("focus_keyphrase") or "").strip().lower()
    draft_slug = str(draft.get("suggested_slug") or draft.get("slug") or "").strip().lower()

    for item in reversed(intake_data.get("content_ideas", [])):
        item_keyword = str(item.get("target_keyword") or "").strip().lower()
        item_slug = str(item.get("suggested_slug") or "").strip().lower()

        if draft_keyword and item_keyword and draft_keyword == item_keyword:
            return item

        if draft_slug and item_slug and draft_slug == item_slug:
            return item

    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace_id")
    parser.add_argument("draft_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    registry_path = get_workspace_draft_registry_path(args.workspace_id)
    registry = load_json(registry_path, {})
    intake_data = load_json(GLOBAL_INTAKE_PATH, {})

    draft = find_draft(registry, args.draft_id)
    if not draft:
        raise SystemExit(f"Draft not found: {args.draft_id}")

    intake = find_matching_intake(intake_data, draft)
    if not intake:
        raise SystemExit("No matching intake found.")

    changes = {}

    # Refresh opportunity_intelligence using the current analyzer so older intakes
    # receive newly added fields such as visual_scenarios and content_angles.
    refreshed_opportunity_intelligence = analyze_opportunity(
        {
            "topic_label": intake.get("idea_title") or intake.get("raw_opportunity_text") or intake.get("topic") or "",
            "content_type": intake.get("content_type") or "landing_page",
            "workspace_id": args.workspace_id,
        },
        {
            "workspace_id": args.workspace_id,
        },
    )

    if refreshed_opportunity_intelligence:
        intake["opportunity_intelligence"] = refreshed_opportunity_intelligence
        intake["topic_family"] = refreshed_opportunity_intelligence.get("topic_family", intake.get("topic_family"))
        intake["visual_topic_family"] = refreshed_opportunity_intelligence.get("visual_topic_family", intake.get("visual_topic_family"))

    for field in COPY_FIELDS:
        value = intake.get(field)
        if value not in (None, "", {}, []):
            old = draft.get(field)
            if old != value:
                changes[field] = {
                    "old": old,
                    "new": value,
                }
                draft[field] = value

    # Also align visible draft fields if intelligence provides better source.
    if draft.get("page_h1"):
        changes["title"] = {"old": draft.get("title"), "new": draft.get("page_h1")}
        changes["working_title"] = {"old": draft.get("working_title"), "new": draft.get("page_h1")}
        draft["title"] = draft.get("page_h1")
        draft["working_title"] = draft.get("page_h1")

    if draft.get("opportunity_intelligence", {}).get("recommended_focus_keyphrase"):
        value = draft["opportunity_intelligence"]["recommended_focus_keyphrase"]
        changes["target_keyword"] = {"old": draft.get("target_keyword"), "new": value}
        changes["focus_keyphrase"] = {"old": draft.get("focus_keyphrase"), "new": value}
        draft["target_keyword"] = value
        draft["focus_keyphrase"] = value

    if draft.get("opportunity_intelligence", {}).get("recommended_slug"):
        value = draft["opportunity_intelligence"]["recommended_slug"]
        changes["suggested_slug"] = {"old": draft.get("suggested_slug"), "new": value}
        changes["slug"] = {"old": draft.get("slug"), "new": value}
        draft["suggested_slug"] = value
        draft["slug"] = value

    print(json.dumps({
        "workspace_id": args.workspace_id,
        "draft_id": args.draft_id,
        "matched_intake_id": intake.get("intake_id"),
        "dry_run": args.dry_run,
        "changed_fields": list(changes.keys()),
        "changes": changes,
    }, ensure_ascii=False, indent=2))

    if not args.dry_run:
        save_json(registry_path, registry)
        print(f"Updated {registry_path}")


if __name__ == "__main__":
    main()
