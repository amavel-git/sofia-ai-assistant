import json
from pathlib import Path

from cannibalization_checker import check_workspace_cannibalization


BASE_DIR = Path(__file__).resolve().parent.parent

WORKSPACES_FILE = BASE_DIR / "data" / "workspaces.json"
INTAKE_FILE = BASE_DIR / "sites" / "content_intake.json"


def load_json(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def find_workspace(workspaces_data, workspace_id: str):
    for workspace in workspaces_data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def keyword_exists_in_memory(memory_data, target_keyword: str) -> bool:
    target_keyword = target_keyword.strip().lower()

    keyword_index = memory_data.get("keyword_index", [])
    for keyword in keyword_index:
        if isinstance(keyword, str) and keyword.strip().lower() == target_keyword:
            return True

    published_content = memory_data.get("published_content", [])
    for item in published_content:
        if isinstance(item, dict):
            keyword = str(item.get("target_keyword", "")).strip().lower()
            if keyword == target_keyword:
                return True

    draft_content = memory_data.get("draft_content", [])
    for item in draft_content:
        if isinstance(item, dict):
            keyword = str(item.get("target_keyword", "")).strip().lower()
            if keyword == target_keyword:
                return True

    return False


def main():
    print("=== Sofia Phase 1: Intake Check ===\n")

    if not WORKSPACES_FILE.exists():
        print(f"ERROR: workspaces.json not found: {WORKSPACES_FILE}")
        return

    if not INTAKE_FILE.exists():
        print(f"ERROR: content_intake.json not found: {INTAKE_FILE}")
        return

    try:
        workspaces_data = load_json(WORKSPACES_FILE)
    except Exception as e:
        print(f"ERROR: Could not read workspaces.json: {e}")
        return

    try:
        intake_data = load_json(INTAKE_FILE)
    except Exception as e:
        print(f"ERROR: Could not read content_intake.json: {e}")
        return

    content_ideas = intake_data.get("content_ideas", [])
    if not content_ideas:
        print("No content ideas found in content_intake.json")
        return

    intake_item = content_ideas[0]

    intake_id = intake_item.get("intake_id", "")
    workspace_id = intake_item.get("workspace_id", "")
    target_keyword = intake_item.get("target_keyword", "")
    idea_title = intake_item.get("idea_title", "")

    print(f"Intake ID: {intake_id}")
    print(f"Idea Title: {idea_title}")
    print(f"Workspace ID: {workspace_id}")
    print(f"Target Keyword: {target_keyword}\n")

    workspace = find_workspace(workspaces_data, workspace_id)
    if not workspace:
        print(f"ERROR: Workspace '{workspace_id}' not found in workspaces.json")
        return

    folder_path = workspace.get("folder_path", "")
    review_mode = workspace.get("review_mode", "")
    domain = workspace.get("domain", "")

    memory_file = BASE_DIR / folder_path / "site_content_memory.json"

    print("Resolved Workspace:")
    print(f"  Domain: {domain}")
    print(f"  Folder Path: {folder_path}")
    print(f"  Review Mode: {review_mode}")
    print(f"  Memory File: {memory_file}\n")

    if not memory_file.exists():
        print(f"ERROR: site_content_memory.json not found: {memory_file}")
        return

    try:
        memory_data = load_json(memory_file)
    except Exception as e:
        print(f"ERROR: Could not read site_content_memory.json: {e}")
        return

    cannibalization = check_workspace_cannibalization(
        workspace=workspace,
        topic=target_keyword,
        extra_terms=[idea_title]
    )

    overlap_found = cannibalization.get("result") in [
        "strong_overlap",
        "possible_overlap"
    ]

    print("Cannibalization Check Result:")
    print(f"  Result: {cannibalization.get('result')}")
    print(f"  Risk score: {cannibalization.get('risk_score')}")
    print(f"  Notes: {cannibalization.get('notes')}")

    matches = cannibalization.get("matches", [])
    if matches:
        print("\nTop matches:")
        for match in matches[:5]:
            print(
                f"  - {match.get('risk')} | score={match.get('score')} | "
                f"{match.get('source_file')} | {match.get('label')}"
            )
            if match.get("url"):
                print(f"    URL: {match.get('url')}")


if __name__ == "__main__":
    main()