#!/usr/bin/env python3
import argparse
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = ROOT / "data" / "workspaces.json"
LOGS_PATH = ROOT / "logs"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def timestamp_slug():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def load_json(path, default):
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_workspace(workspace_id):
    data = load_json(WORKSPACES_PATH, {"workspaces": []})

    for workspace in data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace

    return None


def get_workspace_path(workspace):
    folder_path = workspace.get("folder_path") or workspace.get("workspace_path")

    if not folder_path:
        raise SystemExit("Workspace has no folder_path/workspace_path configured.")

    return ROOT / folder_path


def expand_range(start_id, end_id):
    """
    Expand IDs like OPP-ES-0001 → OPP-ES-0010.
    Only supports IDs with the same prefix and numeric suffix length.
    """
    start_prefix, start_num = start_id.rsplit("-", 1)
    end_prefix, end_num = end_id.rsplit("-", 1)

    if start_prefix != end_prefix:
        raise SystemExit("Range IDs must have the same prefix.")

    width = len(start_num)
    start = int(start_num)
    end = int(end_num)

    if end < start:
        raise SystemExit("Range end must be greater than or equal to range start.")

    return {
        f"{start_prefix}-{str(num).zfill(width)}"
        for num in range(start, end + 1)
    }


def infer_numbered_ids(prefix, opportunities):
    """
    Infer DRAFT/INTAKE IDs from opportunity numeric suffixes.
    OPP-ES-0007 -> DRAFT-0007 and INTAKE-0007.
    """
    ids = set()

    for opp_id in opportunities:
        try:
            number = int(str(opp_id).rsplit("-", 1)[1])
        except Exception:
            continue

        ids.add(f"{prefix}-{number:04d}")

    return ids


def backup_files(workspace_path, backup_dir):
    workspace_files = [
        "draft_registry.json",
        "local_review_queue.json",
        "site_content_memory.json",
        "content_inventory.json",
        "market_opportunity_queue.json",
        "content_opportunities.json",
        "external_opportunities.json",
        "job_registry.json",
    ]

    backed_up = []

    backup_dir.mkdir(parents=True, exist_ok=True)

    for filename in workspace_files:
        src = workspace_path / filename

        if src.exists():
            shutil.copy2(src, backup_dir / filename)
            backed_up.append(str(src.relative_to(ROOT)))

    global_log_files = [
        LOGS_PATH / "telegram_pending_contexts.json",
        LOGS_PATH / "telegram_button_actions.json",
    ]

    for src in global_log_files:
        if src.exists():
            shutil.copy2(src, backup_dir / src.name)
            backed_up.append(str(src.relative_to(ROOT)))

    return backed_up


def reset_draft_registry(path, draft_ids):
    data = load_json(path, {"drafts": []})
    before = len(data.get("drafts", []))

    data["drafts"] = [
        draft for draft in data.get("drafts", [])
        if draft.get("draft_id") not in draft_ids
    ]

    save_json(path, data)
    return before - len(data["drafts"])


def reset_review_queue(path, opportunity_ids, draft_ids):
    data = load_json(path, {"review_items": []})
    before = len(data.get("review_items", []))

    data["review_items"] = [
        item for item in data.get("review_items", [])
        if item.get("draft_id") not in draft_ids
        and item.get("opportunity_id") not in opportunity_ids
        and item.get("source_opportunity_id") not in opportunity_ids
    ]

    save_json(path, data)
    return before - len(data["review_items"])


def reset_intakes(workspace_path, opportunity_ids, intake_ids):
    removed = {}

    for filename in ["intake_registry.json", "content_intake.json"]:
        path = workspace_path / filename

        if not path.exists():
            continue

        data = load_json(path, {})
        key = "content_ideas" if "content_ideas" in data else "intakes"
        before = len(data.get(key, []))

        data[key] = [
            item for item in data.get(key, [])
            if item.get("intake_id") not in intake_ids
            and item.get("opportunity_id") not in opportunity_ids
            and item.get("source_opportunity_id") not in opportunity_ids
            and item.get("created_from_opportunity_id") not in opportunity_ids
        ]

        save_json(path, data)
        removed[filename] = before - len(data[key])

    return removed


def reset_list_file(path, opportunity_ids, draft_ids, list_keys):
    data = load_json(path, {})
    removed = {}

    for key in list_keys:
        if not isinstance(data.get(key), list):
            continue

        before = len(data[key])

        data[key] = [
            item for item in data[key]
            if item.get("draft_id") not in draft_ids
            and item.get("opportunity_id") not in opportunity_ids
            and item.get("source_opportunity_id") not in opportunity_ids
            and item.get("created_from_opportunity_id") not in opportunity_ids
        ]

        removed[key] = before - len(data[key])

    save_json(path, data)
    return removed


def reset_site_content_memory(path, opportunity_ids, draft_ids):
    """
    Remove Sofia test-run memory so reset behaves like the generated
    drafts/pages never existed.

    Handles both object lists and plain keyword/topic string lists.
    """
    data = load_json(path, {})
    removed = {}

    # First remove object-based memory records.
    for key in [
        "content_items",
        "items",
        "topics",
        "pages",
        "draft_content",
        "published_content",
    ]:
        if not isinstance(data.get(key), list):
            continue

        before = len(data[key])

        kept = []
        removed_terms = set()

        for item in data[key]:
            if not isinstance(item, dict):
                kept.append(item)
                continue

            should_remove = (
                item.get("draft_id") in draft_ids
                or item.get("opportunity_id") in opportunity_ids
                or item.get("source_opportunity_id") in opportunity_ids
                or item.get("created_from_opportunity_id") in opportunity_ids
            )

            if should_remove:
                for term_key in [
                    "title",
                    "target_keyword",
                    "focus_keyphrase",
                    "keyword",
                    "slug",
                ]:
                    value = item.get(term_key)
                    if value:
                        removed_terms.add(str(value).strip().lower())
                continue

            kept.append(item)

        data[key] = kept
        removed[key] = before - len(kept)

        if removed_terms:
            data.setdefault("_reset_removed_terms", [])
            for term in sorted(removed_terms):
                if term and term not in data["_reset_removed_terms"]:
                    data["_reset_removed_terms"].append(term)

    removed_terms = set(data.get("_reset_removed_terms", []))

    # Also infer common pilot terms from opportunity IDs.
    # This keeps reset deterministic for old records that do not carry IDs.
    inferred_terms_by_opp = {
        "OPP-ES-0001": [
            "metodología del polígrafo",
            "polígrafo metodología",
            "metodologia poligrafo",
        ],
        "OPP-ES-0002": [
            "solicitud de una prueba de polígrafo",
            "appointment_booking",
            "appointment booking",
        ],
        "OPP-ES-0003": [
            "córdoba",
            "cordoba",
            "city_cordoba",
            "city cordoba",
            "prueba de polígrafo en córdoba",
            "prueba de poligrafo en cordoba",
        ],
        "OPP-ES-0004": [
            "granada",
            "prueba de polígrafo granada",
            "prueba de polígrafo en granada",
            "prueba poligrafo granada",
        ],
        "OPP-ES-0005": [
            "toledo",
            "prueba de polígrafo toledo",
            "prueba de polígrafo en toledo",
        ],
        "OPP-ES-0006": [
            "zaragoza",
            "prueba de polígrafo zaragoza",
            "prueba de polígrafo en zaragoza",
        ],
        "OPP-ES-0007": [
            "alicante",
            "prueba de polígrafo alicante",
            "prueba de polígrafo en alicante",
            "prueba poligrafo alicante",
        ],
        "OPP-ES-0008": [
            "cádiz",
            "cadiz",
            "prueba de polígrafo cádiz",
            "prueba de polígrafo cadiz",
            "prueba de polígrafo en cádiz",
            "prueba poligrafo cadiz",
        ],
        "OPP-ES-0009": [
            "las palmas",
            "prueba de polígrafo las palmas",
            "prueba de polígrafo en las palmas",
            "prueba poligrafo las palmas",
            "prueba de polígrafo las",
        ],
        "OPP-ES-0010": [
            "tenerife",
            "prueba de polígrafo tenerife",
            "prueba de polígrafo en tenerife",
        ],
    }

    for opp_id in opportunity_ids:
        for term in inferred_terms_by_opp.get(opp_id, []):
            removed_terms.add(term.strip().lower())

    # Remove plain string memory lists.
    for key in ["keyword_index", "content_topics"]:
        if not isinstance(data.get(key), list):
            continue

        before = len(data[key])

        data[key] = [
            value for value in data[key]
            if str(value).strip().lower() not in removed_terms
        ]

        removed[key] = before - len(data[key])

    data.pop("_reset_removed_terms", None)
    data["last_reset_at"] = now_iso()

    save_json(path, data)
    return removed


def reset_market_queue(path, opportunity_ids):
    data = load_json(path, {"items": []})
    changed = 0

    for item in data.get("items", []):
        oid = item.get("opportunity_id") or item.get("candidate_id")

        if oid not in opportunity_ids:
            continue

        item["status"] = "pending"

        for field in [
            "queued_at",
            "approved_at",
            "completed_at",
            "rejected_at",
            "completed_from_draft_id",
            "completed_from_intake_id",
            "approved_from_draft_id",
            "approved_from_intake_id",
            "review_status",
        ]:
            item.pop(field, None)

        changed += 1

    save_json(path, data)
    return changed


def reset_content_opportunities(path, opportunity_ids):
    data = load_json(path, [])
    items = data if isinstance(data, list) else data.get("opportunities", [])
    changed = 0

    for item in items:
        if item.get("opportunity_id") not in opportunity_ids:
            continue

        item["status"] = "pending"
        item["review_status"] = None

        for field in [
            "queued_at",
            "approved_at",
            "completed_at",
            "rejected_at",
            "completed_from_draft_id",
            "completed_from_intake_id",
            "converted_to_intake_id",
            "converted_at",
        ]:
            item.pop(field, None)

        changed += 1

    save_json(path, data)
    return changed


def reset_external_opportunities(path, opportunity_ids, reset_telegram):
    data = load_json(path, {"opportunities": []})
    changed = 0

    for item in data.get("opportunities", []):
        if item.get("opportunity_id") not in opportunity_ids:
            continue

        # Restore opportunity to clean pre-review state.
        # queue_market_candidates.py --promote-next is responsible for
        # making exactly one opportunity reviewable/notifier-ready.
        item["status"] = "pending"
        item["review_status"] = None

        if reset_telegram:
            item["telegram_notified"] = False
            item["telegram_notified_at"] = None

        for field in [
            "queued_at",
            "approved_at",
            "completed_at",
            "rejected_at",
            "converted_to_intake_id",
            "converted_at",
            "completed_from_draft_id",
            "completed_from_intake_id",

            # examiner workflow
            "examiner_decision",
            "examiner_comment",
            "examiner_decision_at",

            # intake conversion
            "ready_for_intake",
            "intake_id",
            "converted_to_intake_at",

            # downstream artifacts
            "completed_from_draft_id",
            "completed_from_intake_id",
            "approved_from_draft_id",
            "approved_from_intake_id",
        ]:
            item.pop(field, None)

        changed += 1

    save_json(path, data)
    return changed


def reset_job_registry(path, opportunity_ids, draft_ids, archive_jobs=False, archive_path=None):
    data = load_json(path, {"jobs": []})
    jobs = data.get("jobs", [])

    removed_jobs = [
        job for job in jobs
        if job.get("item_id") in opportunity_ids
        or job.get("item_id") in draft_ids
    ]

    remaining_jobs = [
        job for job in jobs
        if job not in removed_jobs
    ]

    if archive_jobs and archive_path and removed_jobs:
        archive_data = {
            "archived_at": now_iso(),
            "jobs": removed_jobs,
        }
        save_json(archive_path, archive_data)

    data["jobs"] = remaining_jobs
    save_json(path, data)

    return len(removed_jobs)


def reset_telegram_state(opportunity_ids, draft_ids):
    removed_actions = 0
    cleared_contexts = False

    pending_path = LOGS_PATH / "telegram_pending_contexts.json"

    if pending_path.exists():
        save_json(pending_path, {"revision": {}})
        cleared_contexts = True

    actions_path = LOGS_PATH / "telegram_button_actions.json"

    if actions_path.exists():
        data = load_json(actions_path, {"actions": {}})
        before = len(data.get("actions", {}))

        data["actions"] = {
            key: value
            for key, value in data.get("actions", {}).items()
            if value.get("item_id") not in opportunity_ids
            and value.get("item_id") not in draft_ids
        }

        removed_actions = before - len(data["actions"])
        save_json(actions_path, data)

    return cleared_contexts, removed_actions


def parse_args():
    parser = argparse.ArgumentParser(
        description="Reset Sofia workspace test-run artifacts while preserving opportunity definitions and intelligence files."
    )

    parser.add_argument("workspace_id")

    parser.add_argument(
        "--opportunities",
        nargs="*",
        default=[],
        help="Opportunity IDs to reset, e.g. OPP-ES-0001 OPP-ES-0002",
    )

    parser.add_argument(
        "--from-opportunities",
        nargs=2,
        metavar=("START_OPP", "END_OPP"),
        help="Inclusive opportunity range, e.g. OPP-ES-0001 OPP-ES-0010",
    )

    parser.add_argument(
        "--drafts",
        nargs="*",
        default=[],
        help="Draft IDs to remove. If omitted, inferred from opportunity numeric suffixes.",
    )

    parser.add_argument(
        "--intakes",
        nargs="*",
        default=[],
        help="Intake IDs to remove. If omitted, inferred from opportunity numeric suffixes.",
    )

    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create backup under workspace/test_runs before modifying files.",
    )

    parser.add_argument(
        "--archive-jobs",
        action="store_true",
        help="Archive removed jobs into backup folder if --backup is enabled.",
    )

    parser.add_argument(
        "--keep-telegram-notified",
        action="store_true",
        help="Do not reset telegram_notified fields in external_opportunities.json.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be reset. Does not modify files.",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    workspace = find_workspace(args.workspace_id)

    if not workspace:
        raise SystemExit(f"Workspace not found: {args.workspace_id}")

    workspace_path = get_workspace_path(workspace)

    if not workspace_path.exists():
        raise SystemExit(f"Workspace path not found: {workspace_path}")

    opportunity_ids = set(args.opportunities or [])

    if args.from_opportunities:
        opportunity_ids.update(
            expand_range(
                args.from_opportunities[0],
                args.from_opportunities[1],
            )
        )

    if not opportunity_ids:
        raise SystemExit("No opportunities supplied. Use --opportunities or --from-opportunities.")

    draft_ids = set(args.drafts or []) or infer_numbered_ids("DRAFT", opportunity_ids)
    intake_ids = set(args.intakes or []) or infer_numbered_ids("INTAKE", opportunity_ids)

    print("=== Sofia Workspace Test Reset ===")
    print(f"Workspace: {args.workspace_id}")
    print(f"Workspace path: {workspace_path.relative_to(ROOT)}")
    print(f"Opportunities: {', '.join(sorted(opportunity_ids))}")
    print(f"Drafts: {', '.join(sorted(draft_ids))}")
    print(f"Intakes: {', '.join(sorted(intake_ids))}")

    if args.dry_run:
        print("\nDRY RUN ONLY — no files modified.")
        return

    backup_dir = None

    if args.backup:
        backup_dir = workspace_path / "test_runs" / f"reset_{timestamp_slug()}"
        backed_up = backup_files(workspace_path, backup_dir)
        print(f"\nBackup: {backup_dir.relative_to(ROOT)}")
        for item in backed_up:
            print(f"- backed up {item}")

    print("\nResetting files...")

    removed_drafts = reset_draft_registry(
        workspace_path / "draft_registry.json",
        draft_ids,
    )
    print(f"Drafts removed: {removed_drafts}")

    removed_reviews = reset_review_queue(
        workspace_path / "local_review_queue.json",
        opportunity_ids,
        draft_ids,
    )
    print(f"Review items removed: {removed_reviews}")

    removed_intakes = reset_intakes(
        workspace_path,
        opportunity_ids,
        intake_ids,
    )
    for filename, count in removed_intakes.items():
        print(f"Intakes removed from {filename}: {count}")

    # Global intake registry used by process_next_intake.py
    global_intake_path = ROOT / "sites" / "content_intake.json"

    if global_intake_path.exists():
        global_removed = reset_intakes(
            ROOT / "sites",
            opportunity_ids,
            intake_ids,
        )

        for filename, count in global_removed.items():
            print(f"Global intakes removed from {filename}: {count}")

    removed_memory = reset_site_content_memory(
        workspace_path / "site_content_memory.json",
        opportunity_ids,
        draft_ids,
    )
    for key, count in removed_memory.items():
        print(f"Memory items removed from {key}: {count}")

    removed_inventory = reset_list_file(
        workspace_path / "content_inventory.json",
        opportunity_ids,
        draft_ids,
        ["content_items", "items", "inventory"],
    )
    for key, count in removed_inventory.items():
        print(f"Inventory items removed from {key}: {count}")

    reset_queue_count = reset_market_queue(
        workspace_path / "market_opportunity_queue.json",
        opportunity_ids,
    )
    print(f"Queue items reset: {reset_queue_count}")

    reset_content_count = reset_content_opportunities(
        workspace_path / "content_opportunities.json",
        opportunity_ids,
    )
    print(f"Content opportunities reset: {reset_content_count}")

    reset_external_count = reset_external_opportunities(
        workspace_path / "external_opportunities.json",
        opportunity_ids,
        reset_telegram=not args.keep_telegram_notified,
    )
    print(f"External opportunities reset: {reset_external_count}")

    archive_path = None
    if args.archive_jobs and backup_dir:
        archive_path = backup_dir / "archived_jobs.json"

    removed_jobs = reset_job_registry(
        workspace_path / "job_registry.json",
        opportunity_ids,
        draft_ids,
        archive_jobs=args.archive_jobs,
        archive_path=archive_path,
    )
    print(f"Jobs removed: {removed_jobs}")

    cleared_contexts, removed_actions = reset_telegram_state(
        opportunity_ids,
        draft_ids,
    )
    print(f"Telegram pending contexts cleared: {cleared_contexts}")
    print(f"Telegram button actions removed: {removed_actions}")

    print("\nReset completed.")
    print("Manual WordPress page deletion remains separate.")


if __name__ == "__main__":
    main()
