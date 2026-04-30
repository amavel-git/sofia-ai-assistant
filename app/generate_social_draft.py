import json
import requests
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

WORKSPACES_FILE = BASE_DIR / "data" / "workspaces.json"
PROMPT_FILE = BASE_DIR / "prompts" / "social_post_prompt.md"

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b"


def load_json(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path: Path, data):
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_text(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return f.read()


def find_workspace(workspaces_data, workspace_id: str):
    for workspace in workspaces_data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def find_pending_social_item(social_items):
    for item in social_items:
        if item.get("status") == "pending_review":
            return item
    return None


def fill_prompt(template, social_item):
    link_back = social_item.get("link_back", {})

    replacements = {
        "{{language}}": social_item.get("language", ""),
        "{{locale}}": social_item.get("locale", social_item.get("language", "")),
        "{{market}}": social_item.get("workspace_id", ""),
        "{{platform}}": social_item.get("platform", ""),
        "{{idea_title}}": social_item.get("idea_title", ""),
        "{{idea_summary}}": social_item.get("idea_summary", ""),
        "{{target_keyword}}": social_item.get("target_keyword", ""),
        "{{secondary_keywords}}": ", ".join(social_item.get("secondary_keywords", [])),
        "{{site_target}}": social_item.get("site_target", ""),
        "{{link_back_recommended}}": str(link_back.get("recommended", False)),
        "{{link_back_url}}": link_back.get("target_url", "")
    }

    prompt = template
    for key, value in replacements.items():
        prompt = prompt.replace(key, value)

    return prompt


def call_ollama(prompt):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False
    }

    response = requests.post(OLLAMA_URL, json=payload, timeout=180)
    response.raise_for_status()

    data = response.json()
    return data.get("response", "").strip()


def main():
    print("=== Sofia: Generate Social Draft ===\n")

    if not WORKSPACES_FILE.exists():
        print(f"ERROR: workspaces.json not found: {WORKSPACES_FILE}")
        return

    if not PROMPT_FILE.exists():
        print(f"ERROR: social_post_prompt.md not found: {PROMPT_FILE}")
        return

    try:
        workspaces_data = load_json(WORKSPACES_FILE)
        prompt_template = load_text(PROMPT_FILE)
    except Exception as e:
        print(f"ERROR: Could not read required files: {e}")
        return

    # For now, process Angola social queue.
    workspace_id = "local.ao"
    workspace = find_workspace(workspaces_data, workspace_id)

    if not workspace:
        print(f"ERROR: Workspace not found: {workspace_id}")
        return

    folder_path = workspace.get("folder_path", "")
    social_queue_file = BASE_DIR / folder_path / "social_review_queue.json"

    if not social_queue_file.exists():
        print(f"ERROR: social_review_queue.json not found: {social_queue_file}")
        return

    try:
        social_queue_data = load_json(social_queue_file)
    except Exception as e:
        print(f"ERROR: Could not read social queue: {e}")
        return

    social_items = social_queue_data.get("social_items", [])
    social_item = find_pending_social_item(social_items)

    if not social_item:
        print("No pending social items found.")
        return

    social_id = social_item.get("social_id", "")
    print(f"Processing social item: {social_id}")
    print(f"Platform: {social_item.get('platform', '')}")
    print(f"Topic: {social_item.get('idea_title', '')}\n")

    prompt = fill_prompt(prompt_template, social_item)

    try:
        draft_text = call_ollama(prompt)
    except Exception as e:
        print(f"ERROR: Ollama generation failed: {e}")
        return

    if not draft_text:
        print("ERROR: Ollama returned empty draft.")
        return

    social_item["draft_text"] = draft_text
    social_item["status"] = "drafted"

    try:
        save_json(social_queue_file, social_queue_data)
    except Exception as e:
        print(f"ERROR: Could not save social queue: {e}")
        return

    print("Social draft generated successfully.\n")
    print("Draft:")
    print(draft_text)


if __name__ == "__main__":
    main()