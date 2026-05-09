import json
import shutil
from pathlib import Path
from datetime import datetime, timezone

from workspace_paths import (
    SOFIA_ROOT,
    GLOBAL_DRAFT_REGISTRY_PATH,
    get_all_workspaces,
    get_workspace_draft_registry_path,
    load_json,
    save_json,
    empty_draft_registry,
)


def now_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_drafts(data):
    if isinstance(data, dict) and isinstance(data.get("drafts"), list):
        return data["drafts"]

    if isinstance(data, list):
        return data

    return []


def find_workspace_by_id(workspaces, workspace_id):
    for workspace in workspaces:
        if workspace.get("workspace_id") == workspace_id:
            return workspace

    return None


def merge_drafts(existing_drafts, new_drafts):
    merged = []
    seen = {}

    for draft in existing_drafts:
        draft_id = draft.get("draft_id")
        if not draft_id:
            continue

        merged.append(draft)
        seen[draft_id] = len(merged) - 1

    added = 0
    updated = 0

    for draft in new_drafts:
        draft_id = draft.get("draft_id")
        if not draft_id:
            continue

        if draft_id in seen:
            idx = seen[draft_id]
            merged[idx] = {
                **merged[idx],
                **draft,
                "registry_migrated_at": now_iso()
            }
            updated += 1
        else:
            new_draft = {
                **draft,
                "registry_migrated_at": now_iso()
            }
            merged.append(new_draft)
            seen[draft_id] = len(merged) - 1
            added += 1

    return merged, added, updated


def main():
    print("=== Sofia: Migrate Draft Registry to Workspace Registries ===\n")

    if not GLOBAL_DRAFT_REGISTRY_PATH.exists():
        print(f"ERROR: Global draft registry not found: {GLOBAL_DRAFT_REGISTRY_PATH}")
        return

    workspaces = get_all_workspaces()

    if not workspaces:
        print("ERROR: No workspaces found in data/workspaces.json")
        return

    global_data = load_json(GLOBAL_DRAFT_REGISTRY_PATH, {"drafts": []})
    global_drafts = get_drafts(global_data)

    if not global_drafts:
        print("No drafts found in global registry.")
        return

    backup_path = GLOBAL_DRAFT_REGISTRY_PATH.with_name(
        f"draft_registry.backup-before-workspace-migration-{now_stamp()}.json"
    )

    shutil.copy2(GLOBAL_DRAFT_REGISTRY_PATH, backup_path)

    print(f"Backup created:")
    print(f"  {backup_path}\n")

    drafts_by_workspace = {}
    skipped = []

    for draft in global_drafts:
        workspace_id = draft.get("workspace_id", "")

        if not workspace_id:
            skipped.append({
                "draft_id": draft.get("draft_id", ""),
                "reason": "missing workspace_id"
            })
            continue

        workspace = find_workspace_by_id(workspaces, workspace_id)

        if not workspace:
            skipped.append({
                "draft_id": draft.get("draft_id", ""),
                "workspace_id": workspace_id,
                "reason": "workspace_id not found in workspaces.json"
            })
            continue

        drafts_by_workspace.setdefault(workspace_id, []).append(draft)

    total_added = 0
    total_updated = 0

    for workspace_id, drafts in sorted(drafts_by_workspace.items()):
        registry_path = get_workspace_draft_registry_path(workspace_id)

        existing_data = load_json(registry_path, empty_draft_registry(workspace_id))
        existing_drafts = get_drafts(existing_data)

        merged_drafts, added, updated = merge_drafts(existing_drafts, drafts)

        output_data = {
            "version": existing_data.get("version", "1.0"),
            "scope": "workspace",
            "workspace_id": workspace_id,
            "last_migrated_at": now_iso(),
            "drafts": merged_drafts
        }

        save_json(registry_path, output_data)

        total_added += added
        total_updated += updated

        print(f"Workspace: {workspace_id}")
        print(f"  Registry: {registry_path}")
        print(f"  Drafts migrated from global: {len(drafts)}")
        print(f"  Added: {added}")
        print(f"  Updated: {updated}")
        print(f"  Total workspace drafts: {len(merged_drafts)}\n")

    if skipped:
        skipped_path = SOFIA_ROOT / "logs" / f"draft_registry_migration_skipped_{now_stamp()}.json"
        save_json(skipped_path, {"skipped": skipped})

        print("Skipped drafts:")
        for item in skipped:
            print(f"  - {item}")
        print(f"\nSkipped report saved to: {skipped_path}\n")

    print("Migration completed.")
    print(f"Total added: {total_added}")
    print(f"Total updated: {total_updated}")
    print("\nImportant:")
    print("The global registry was NOT deleted.")
    print("Next step is to update scripts to use workspace-level draft_registry.json as the source of truth.")


if __name__ == "__main__":
    main()