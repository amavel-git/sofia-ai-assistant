import json
import requests
from pathlib import Path
from datetime import datetime


BASE_DIR = Path(__file__).resolve().parent.parent

WORKSPACES_FILE = BASE_DIR / "data" / "workspaces.json"
DRAFT_REGISTRY_FILE = BASE_DIR / "sites" / "draft_registry.json"
PROMPT_FILE = BASE_DIR / "prompts" / "website_content_prompt.md"

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


def find_draft_ready_for_content(drafts):
    for draft in drafts:
        if draft.get("draft_status") in ["draft_created", "in_review"]:
            if not draft.get("draft_content"):
                return draft
    return None


def infer_locale(language: str, workspace_id: str, site_target: str):
    language = (language or "").lower()
    workspace_id = (workspace_id or "").lower()
    site_target = (site_target or "").lower()

    if language == "pt":
        if "br" in workspace_id or "brasil" in site_target:
            return "pt-BR"
        return "pt-PT"

    if language == "en":
        return "en-US"

    if language == "es":
        return "es-ES"

    if language == "fr":
        return "fr-FR"

    return language


def load_internal_links(workspace_folder: Path):
    structure_file = workspace_folder / "site_structure.json"

    if not structure_file.exists():
        return []

    try:
        structure = load_json(structure_file)
    except Exception:
        return []

    links = []

    for page in structure.get("pages", []):
        url = page.get("url", "")
        slug = page.get("slug", "")
        page_type = page.get("page_type", "")

        if url:
            links.append({
                "url": url,
                "slug": slug,
                "page_type": page_type
            })

    return links[:8]


def format_internal_links(internal_links):
    if not internal_links:
        return "No internal links available."

    lines = []

    for link in internal_links:
        lines.append(
            f"- {link.get('url', '')} "
            f"(slug: {link.get('slug', '')}, type: {link.get('page_type', '')})"
        )

    return "\n".join(lines)


def fill_prompt(template: str, draft: dict, workspace: dict, internal_links_text: str):
    language = draft.get("language", "")
    workspace_id = draft.get("workspace_id", "")
    site_target = draft.get("site_target", workspace.get("domain", ""))
    locale = draft.get("locale") or infer_locale(language, workspace_id, site_target)

    replacements = {
        "{{language}}": language,
        "{{locale}}": locale,
        "{{market}}": workspace.get("market_code", ""),
        "{{content_type}}": draft.get("content_type", ""),
        "{{idea_title}}": draft.get("working_title", ""),
        "{{idea_summary}}": draft.get("notes", ""),
        "{{target_keyword}}": draft.get("target_keyword", ""),
        "{{secondary_keywords}}": ", ".join(draft.get("secondary_keywords", [])),
        "{{search_intent}}": draft.get("search_intent", ""),
        "{{suggested_slug}}": draft.get("suggested_slug", ""),
        "{{site_target}}": site_target,
        "{{internal_links}}": internal_links_text
    }

    prompt = template

    for key, value in replacements.items():
        prompt = prompt.replace(key, str(value))

    return prompt


def call_ollama(prompt: str):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.4,
            "num_ctx": 8192
        }
    }

    response = requests.post(OLLAMA_URL, json=payload, timeout=600)
    response.raise_for_status()

    data = response.json()
    return data.get("response", "").strip()


def main():
    print("=== Sofia: Generate Website Draft ===\n")

    for required_file in [WORKSPACES_FILE, DRAFT_REGISTRY_FILE, PROMPT_FILE]:
        if not required_file.exists():
            print(f"ERROR: Required file not found: {required_file}")
            return

    try:
        workspaces_data = load_json(WORKSPACES_FILE)
        draft_registry_data = load_json(DRAFT_REGISTRY_FILE)
        prompt_template = load_text(PROMPT_FILE)
    except Exception as e:
        print(f"ERROR: Could not read required files: {e}")
        return

    drafts = draft_registry_data.get("drafts", [])

    draft = find_draft_ready_for_content(drafts)

    if not draft:
        print("No draft found that is ready for website content generation.")
        return

    draft_id = draft.get("draft_id", "")
    workspace_id = draft.get("workspace_id", "")

    print(f"Processing draft: {draft_id}")
    print(f"Workspace: {workspace_id}")
    print(f"Title: {draft.get('working_title', '')}")
    print(f"Target keyword: {draft.get('target_keyword', '')}\n")

    workspace = find_workspace(workspaces_data, workspace_id)

    if not workspace:
        print(f"ERROR: Workspace not found in workspaces.json: {workspace_id}")
        return

    workspace_folder = BASE_DIR / workspace.get("folder_path", "")
    internal_links = load_internal_links(workspace_folder)
    internal_links_text = format_internal_links(internal_links)

    prompt = fill_prompt(
        template=prompt_template,
        draft=draft,
        workspace=workspace,
        internal_links_text=internal_links_text
    )

    try:
        generated_content = call_ollama(prompt)
    except Exception as e:
        print(f"ERROR: Ollama generation failed: {e}")
        return

    if not generated_content:
        print("ERROR: Ollama returned empty content.")
        return

    today = datetime.now().strftime("%Y-%m-%d")

    draft["draft_content"] = {
        "generated_at": today,
        "model": OLLAMA_MODEL,
        "content_format": "structured_text_with_html_body",
        "content": generated_content
    }

    draft["draft_status"] = "content_generated"

    try:
        save_json(DRAFT_REGISTRY_FILE, draft_registry_data)
    except Exception as e:
        print(f"ERROR: Could not save draft_registry.json: {e}")
        return

    print("Website draft generated successfully.")
    print(f"Draft ID: {draft_id}")
    print("Draft status updated to: content_generated\n")
    print("Generated content preview:")
    print(generated_content[:1200])


if __name__ == "__main__":
    main()