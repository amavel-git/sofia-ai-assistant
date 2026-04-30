import json
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = ROOT / "data" / "workspaces.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def find_workspace(workspaces, workspace_id):
    for workspace in workspaces.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def get_drafts(draft_registry):
    if isinstance(draft_registry, dict) and "drafts" in draft_registry:
        return draft_registry["drafts"]
    if isinstance(draft_registry, list):
        return draft_registry
    return []


def run_content_expansion(workspace_id, draft_id):
    result = subprocess.run(
        [
            sys.executable,
            "app/generate_content_variants.py",
            workspace_id,
            draft_id
        ],
        cwd=ROOT,
        text=True,
        capture_output=True
    )

    print(result.stdout)

    if result.stderr:
        print(result.stderr)

    return result.returncode == 0


def main():
    if len(sys.argv) < 2:
        print("Usage: python app/move_approved_to_publishing.py WORKSPACE_ID")
        print("Example: python app/move_approved_to_publishing.py local.ao")
        return

    workspace_id = sys.argv[1]

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, workspace_id)

    if not workspace:
        print(f"Workspace not found: {workspace_id}")
        sys.exit(1)

    draft_registry_path = ROOT / workspace["draft_registry_path"]
    draft_registry = load_json(draft_registry_path)
    drafts = get_drafts(draft_registry)

    moved_count = 0
    expansion_count = 0
    timestamp = now_iso()

    for draft in drafts:
        if draft.get("status") == "approved_by_examiner":
            draft["status"] = "ready_for_publishing"
            draft["ready_for_publishing"] = True
            draft["publishing_gate_passed"] = True
            draft["publishing_gate_passed_at"] = timestamp
            draft["updated_at"] = timestamp
            moved_count += 1

            if not draft.get("content_expansion_generated"):
                save_json(draft_registry_path, draft_registry)

                print(f"\nGenerating content expansion for {draft.get('draft_id')}...")
                expansion_ok = run_content_expansion(workspace_id, draft.get("draft_id"))

                if expansion_ok:
                    draft["content_expansion_generated"] = True
                    draft["content_expansion_generated_at"] = now_iso()
                    expansion_count += 1
                else:
                    draft["content_expansion_generated"] = False
                    draft["content_expansion_error"] = True

    save_json(draft_registry_path, draft_registry)

    print("Publishing gate completed.")
    print(f"Workspace: {workspace_id}")
    print(f"Approved drafts moved: {moved_count}")
    print(f"Content expansions generated: {expansion_count}")


if __name__ == "__main__":
    main()