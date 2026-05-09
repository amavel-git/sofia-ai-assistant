import json
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]

WORKSPACES_PATH = SOFIA_ROOT / "data" / "workspaces.json"
GLOBAL_DRAFT_REGISTRY_PATH = SOFIA_ROOT / "sites" / "draft_registry.json"


def load_json(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_all_workspaces():
    data = load_json(WORKSPACES_PATH, {"workspaces": []})
    return data.get("workspaces", [])


def get_workspace(workspace_id: str):
    for workspace in get_all_workspaces():
        if workspace.get("workspace_id") == workspace_id:
            return workspace

    return None


def get_workspace_folder_path(workspace_id: str) -> Path:
    workspace = get_workspace(workspace_id)

    if not workspace:
        raise RuntimeError(f"Workspace not found: {workspace_id}")

    folder_path = workspace.get("folder_path")

    if not folder_path:
        raise RuntimeError(f"Workspace has no folder_path: {workspace_id}")

    return SOFIA_ROOT / folder_path


def get_workspace_draft_registry_path(workspace_id: str) -> Path:
    return get_workspace_folder_path(workspace_id) / "draft_registry.json"


def empty_draft_registry(workspace_id: str = ""):
    return {
        "version": "1.0",
        "scope": "workspace",
        "workspace_id": workspace_id,
        "drafts": []
    }


def load_workspace_draft_registry(workspace_id: str):
    path = get_workspace_draft_registry_path(workspace_id)
    return load_json(path, empty_draft_registry(workspace_id))


def save_workspace_draft_registry(workspace_id: str, data):
    path = get_workspace_draft_registry_path(workspace_id)

    if "version" not in data:
        data["version"] = "1.0"

    data["scope"] = "workspace"
    data["workspace_id"] = workspace_id

    if "drafts" not in data or not isinstance(data["drafts"], list):
        data["drafts"] = []

    save_json(path, data)


def get_drafts_from_registry(registry_data):
    if isinstance(registry_data, dict) and isinstance(registry_data.get("drafts"), list):
        return registry_data["drafts"]

    if isinstance(registry_data, list):
        return registry_data

    return []


def find_draft_in_workspace(workspace_id: str, draft_id: str):
    registry = load_workspace_draft_registry(workspace_id)

    for draft in get_drafts_from_registry(registry):
        if draft.get("draft_id") == draft_id:
            return draft

    return None


def find_draft_any_workspace(draft_id: str):
    for workspace in get_all_workspaces():
        workspace_id = workspace.get("workspace_id")

        if not workspace_id:
            continue

        try:
            draft = find_draft_in_workspace(workspace_id, draft_id)
        except Exception:
            continue

        if draft:
            return workspace_id, draft

    return None, None


def resolve_draft_registry_path(workspace_id: str = "") -> Path:
    if workspace_id:
        return get_workspace_draft_registry_path(workspace_id)

    return GLOBAL_DRAFT_REGISTRY_PATH