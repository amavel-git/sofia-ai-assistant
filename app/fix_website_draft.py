import json
import requests
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

DRAFT_REGISTRY_FILE = BASE_DIR / "sites" / "draft_registry.json"

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b"


def load_json(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path: Path, data):
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_draft_to_fix(drafts):
    for draft in drafts:
        if draft.get("draft_status") == "needs_quality_review":
            return draft
    return None


def build_fix_prompt(content, issues):
    issues_text = "\n".join([f"- {issue}" for issue in issues])

    prompt = f"""
You are an expert SEO and content editor.

Your task is to FIX the existing website content based on specific issues.

IMPORTANT RULES:
- Do NOT rewrite the entire content
- Do NOT change structure unless necessary
- Keep headings, sections, and formatting intact
- Only fix the issues listed
- Maintain professional tone
- Follow polygraph ethical rules:
  - No claims of 100% accuracy
  - No guarantees
  - No "proves truth" statements

Issues to fix:
{issues_text}

Original Content:
{content}

Return ONLY the corrected content.
Do NOT add explanations.
Do NOT add comments.
"""

    return prompt.strip()


def call_ollama(prompt):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2
        }
    }

    response = requests.post(OLLAMA_URL, json=payload, timeout=300)
    response.raise_for_status()

    data = response.json()
    return data.get("response", "").strip()


def main():
    print("=== Sofia: Fix Website Draft ===\n")

    if not DRAFT_REGISTRY_FILE.exists():
        print(f"ERROR: draft_registry.json not found")
        return

    try:
        draft_registry_data = load_json(DRAFT_REGISTRY_FILE)
    except Exception as e:
        print(f"ERROR: Could not read file: {e}")
        return

    drafts = draft_registry_data.get("drafts", [])
    draft = find_draft_to_fix(drafts)

    if not draft:
        print("No draft needing quality review found.")
        return

    draft_id = draft.get("draft_id", "")
    print(f"Fixing draft: {draft_id}")

    content = draft.get("draft_content", {}).get("content", "")
    issues = draft.get("validation", {}).get("issues", [])

    if not content or not issues:
        print("Nothing to fix.")
        return

    prompt = build_fix_prompt(content, issues)

    try:
        fixed_content = call_ollama(prompt)
    except Exception as e:
        print(f"ERROR: Ollama failed: {e}")
        return

    if not fixed_content:
        print("ERROR: Empty response from model.")
        return

    draft["draft_content"]["content"] = fixed_content
    draft["draft_status"] = "fixed"

    try:
        save_json(DRAFT_REGISTRY_FILE, draft_registry_data)
    except Exception as e:
        print(f"ERROR: Could not save file: {e}")
        return

    print("Draft fixed successfully.")
    print(f"Draft ID: {draft_id}")
    print("Status updated to: fixed\n")


if __name__ == "__main__":
    main()