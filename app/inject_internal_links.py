import json
import sys
import re
from pathlib import Path

from workspace_paths import (
    find_draft_any_workspace,
    get_workspace_draft_registry_path,
)


SOFIA_ROOT = Path(__file__).resolve().parents[1]

DRAFT_REGISTRY_FILE = SOFIA_ROOT / "sites" / "draft_registry.json"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_draft_registry_for_draft(draft_id):
    workspace_id, draft = find_draft_any_workspace(draft_id)

    if not workspace_id or not draft:
        raise RuntimeError(f"Draft not found in any workspace registry: {draft_id}")

    registry_path = get_workspace_draft_registry_path(workspace_id)
    registry_data = load_json(registry_path)

    return workspace_id, registry_path, registry_data, draft


def load_internal_links(workspace_path: str):
    file_path = SOFIA_ROOT / workspace_path / "internal_link_suggestions.json"
    if not file_path.exists():
        raise FileNotFoundError(f"Missing internal links file: {file_path}")
    return load_json(file_path)["internal_link_suggestions"]


def find_relevant_links(suggestions):
    """
    Select top links:
    - max 1 conversion
    - max 1 supporting info
    - max 1 topic_related
    """

    selected = []

    types_used = set()

    for s in suggestions:
        link_type = s.get("link_type")

        if link_type not in ["conversion", "supporting_information", "topic_related"]:
            continue

        if link_type in types_used:
            continue

        selected.append(s)
        types_used.add(link_type)

        if len(selected) >= 5:
            break

    return selected


def insert_link_once(content: str, keyword: str, url: str):
    """
    Replace first occurrence of keyword with anchor link.
    Returns:
    - updated content
    - boolean (whether insertion happened)
    """
    pattern = re.compile(rf"\b({re.escape(keyword)})\b", re.IGNORECASE)

    def replacer(match):
        return f'<a href="{url}">{match.group(1)}</a>'

    new_content, count = pattern.subn(replacer, content, count=1)

    return new_content, count > 0


def inject_links_into_html(content: str, links):
    """
    Smart linking:
    - derive keyword from target URL
    - try keyword match
    - fallback to paragraph injection
    """

    for link in links:
        url = link.get("target_url", "")

        if not url:
            continue

        keyword = derive_keyword_from_url(url)

        content, inserted = insert_link_once(content, keyword, url)

        if not inserted:
            content = inject_fallback_link(content, keyword, url)

    return content


def derive_keyword_from_url(url: str):
    slug = url.strip("/").split("/")[-1]

    slug = slug.replace("-", " ")
    slug = slug.replace("_", " ")

    replacements = {
        "poligrafo": "teste de polígrafo",
        "polygraph": "polygraph test",
        "infidelidade": "teste de polígrafo para infidelidade",
        "furto": "teste de polígrafo para furto",
        "roubo": "teste de polígrafo para roubo",
        "empresas": "testes de polígrafo para empresas",
        "pre emprego": "teste de polígrafo pré-emprego",
        "sexual": "teste de polígrafo para assédio sexual",
        "legal": "teste de polígrafo para questões legais",
    }

    keyword = slug.lower()

    for source, replacement in replacements.items():
        if source in keyword:
            return replacement

    return slug
    slug = url.strip("/").split("/")[-1]
    slug = slug.replace("-", " ")
    return slug


def inject_fallback_link(content: str, keyword: str, url: str):
    paragraphs = re.split(r"(</p>)", content)

    inserted = False

    for i in range(0, len(paragraphs), 2):
        paragraph = paragraphs[i]

        if "<p>" not in paragraph:
            continue

        # Avoid injecting into FAQ answers repeatedly.
        if "faq" in paragraph.lower():
            continue

        # Avoid injecting into already linked paragraphs.
        if "<a " in paragraph.lower():
            continue

        paragraphs[i] = paragraph.replace(
            "</p>",
            f' Para mais informações, consulte também <a href="{url}">{keyword}</a>.</p>',
            1
        )

        inserted = True
        break

    if not inserted:
        content += f'\n<p>Para mais informações, consulte também <a href="{url}">{keyword}</a>.</p>'

        return content

    return "".join(paragraphs)


def main():
    print("=== Sofia: Inject Internal Links ===\n")

    if len(sys.argv) != 2:
        print("Usage:")
        print("python app/inject_internal_links.py DRAFT-0005")
        return

    draft_id = sys.argv[1]

    try:
        workspace_id, draft_registry_file, draft_data, draft = load_draft_registry_for_draft(draft_id)
    except Exception as e:
        print(f"ERROR: {e}")
        return

    if not draft:
        print(f"Draft not found: {draft_id}")
        return

    allowed_statuses = [
        "content_generated",
        "internal_links_added",
        "ai_internal_links_added",
        "approved",
    ]

    if draft.get("draft_status") not in allowed_statuses:
        print(f"Draft must be in one of these statuses: {allowed_statuses}")
        print(f"Current status: {draft.get('draft_status')}")
        return

    content_block = draft.get("generated_content", {})
    content = content_block.get("content", "")

    if not content:
        print("No content to process.")
        return

    try:
        suggestions = load_internal_links(draft.get("workspace_path"))
    except Exception as e:
        print(f"Error loading suggestions: {e}")
        return

    selected_links = find_relevant_links(suggestions)

    if not selected_links:
        print("No suitable links found.")
        return

    updated_content = inject_links_into_html(content, selected_links)

    if "generated_content" not in draft or not isinstance(draft["generated_content"], dict):
        draft["generated_content"] = {}

    draft["generated_content"]["content"] = updated_content
    draft["html_content"] = updated_content
    draft["draft_status"] = "internal_links_added"

    draft_data["scope"] = "workspace"
    draft_data["workspace_id"] = workspace_id
    save_json(draft_registry_file, draft_data)

    print(f"Internal links added to {draft_id}")
    print(f"Links injected: {len(selected_links)}")
    print(f"Workspace registry: {draft_registry_file}")


if __name__ == "__main__":
    main()