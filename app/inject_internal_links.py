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
    workspace_id, _ = find_draft_any_workspace(draft_id)

    if not workspace_id:
        raise RuntimeError(f"Draft not found in any workspace registry: {draft_id}")

    registry_path = get_workspace_draft_registry_path(workspace_id)
    registry_data = load_json(registry_path)

    draft = None

    for item in registry_data.get("drafts", []):
        if item.get("draft_id") == draft_id:
            draft = item
            break

    if not draft:
        raise RuntimeError(f"Draft not found in workspace registry: {draft_id}")

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
    Avoid inserting links inside existing anchor tags.
    """
    pattern = re.compile(rf"\b({re.escape(keyword)})\b", re.IGNORECASE)

    parts = re.split(r"(<a\b[^>]*>.*?</a>)", content, flags=re.IGNORECASE | re.DOTALL)

    for index, part in enumerate(parts):
        if part.lower().startswith("<a "):
            continue

        new_part, count = pattern.subn(
            f'<a href="{url}">\\1</a>',
            part,
            count=1,
        )

        if count > 0:
            parts[index] = new_part
            return "".join(parts), True

    return content, False


def remove_existing_internal_links(content: str):
    """
    Remove previously injected internal links while keeping their visible text.
    This prevents duplicate and nested anchors when the script is re-run.
    """
    return re.sub(
        r'<a\s+href="https?://[^"]+">(.*?)</a>',
        r"\1",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )


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
            content = inject_fallback_link(content, keyword, url, language)

    return content


def derive_keyword_from_url(url: str):
    slug = url.strip("/").split("/")[-1]
    keyword = slug.replace("-", " ").replace("_", " ").lower()

    replacements = {
        "perguntas": "secção de perguntas frequentes",
        "respostas": "secção de perguntas frequentes",
        "faq": "secção de perguntas frequentes",
        "contacto": "entre em contacto connosco",
        "contato": language_aware_contact_anchor(language),
        "contact": "contact us",
        "sobre": "sobre a nossa equipa",
        "about": "about our team",
        "poligrafo": "teste de polígrafo",
        "polygraph": "polygraph test",
        "infidelidade": "testes de polígrafo para infidelidade",
        "furto": "testes de polígrafo para roubo ou furto",
        "roubo": "testes de polígrafo para roubo ou furto",
        "empresas": "testes de polígrafo para empresas",
        "pre emprego": "testes de polígrafo pré-emprego",
        "sexual": "testes de polígrafo para assédio sexual",
        "legal": "testes de polígrafo para questões legais",
    }

    for source, replacement in replacements.items():
        if source in keyword:
            return replacement

    return keyword


def inject_fallback_link(content: str, keyword: str, url: str, language: str = "pt"):
    url_lower = url.lower()
    language = (language or "pt").lower()

    if language.startswith("es"):

        if "faq" in url_lower or "preguntas" in url_lower:
            sentence = (
                f' También puede consultar nuestra '
                f'<a href="{url}">sección de preguntas frecuentes</a> '
                f'para resolver dudas generales sobre el proceso.'
            )

        elif "contacto" in url_lower or "contact" in url_lower:
            sentence = (
                f' Si desea comentar un caso concreto, '
                f'<a href="{url}">puede contactar con nosotros</a> '
                f'para recibir orientación inicial.'
            )

        else:
            sentence = (
                f' Para información relacionada, consulte también '
                f'<a href="{url}">{keyword}</a>.'
            )

    elif language.startswith("fr"):

        if "faq" in url_lower:
            sentence = (
                f' Vous pouvez également consulter notre '
                f'<a href="{url}">foire aux questions</a> '
                f'pour obtenir des informations générales sur le processus.'
            )

        elif "contact" in url_lower:
            sentence = (
                f' Si vous souhaitez discuter d’un cas particulier, '
                f'<a href="{url}">vous pouvez nous contacter</a> '
                f'pour recevoir une première orientation.'
            )

        else:
            sentence = (
                f' Pour des informations complémentaires, consultez également '
                f'<a href="{url}">{keyword}</a>.'
            )

    elif language.startswith("en"):

        if "faq" in url_lower:
            sentence = (
                f' You may also consult our '
                f'<a href="{url}">frequently asked questions</a> '
                f'for general information about the process.'
            )

        elif "contact" in url_lower:
            sentence = (
                f' If you would like to discuss a specific case, '
                f'<a href="{url}">you can contact us</a> '
                f'for initial guidance.'
            )

        else:
            sentence = (
                f' For related information, see also '
                f'<a href="{url}">{keyword}</a>.'
            )

    else:

        if "perguntas" in url_lower or "respostas" in url_lower or "faq" in url_lower:
            sentence = (
                f' Também pode consultar a nossa '
                f'<a href="{url}">secção de perguntas frequentes</a> '
                f'para esclarecer dúvidas gerais sobre o processo.'
            )

        elif "contacto" in url_lower or "contato" in url_lower or "contact" in url_lower:
            sentence = (
                f' Se deseja discutir um caso específico, '
                f'<a href="{url}">entre em contacto connosco</a> '
                f'para receber orientação inicial.'
            )

        else:
            sentence = (
                f' Para informações relacionadas, consulte também '
                f'<a href="{url}">{keyword}</a>.'
            )

    matches = list(re.finditer(r"</p>", content, flags=re.IGNORECASE))

    if matches:
        insert_index = min(len(matches) - 1, 2)
        position = matches[insert_index].start()
        return content[:position] + sentence + content[position:]

    return content + f"\n<p>{sentence.strip()}</p>"



def language_aware_contact_anchor(language: str) -> str:
    language = (language or "").lower()

    if language.startswith("es"):
        return "contactar con nosotros"
    if language.startswith("fr"):
        return "nous contacter"
    if language.startswith("en"):
        return "contact us"
    if language.startswith("pt"):
        return "entre em contacto connosco"

    return "contact us"


def language_aware_faq_anchor(language: str) -> str:
    language = (language or "").lower()

    if language.startswith("es"):
        return "preguntas frecuentes sobre el polígrafo"
    if language.startswith("fr"):
        return "questions fréquentes sur le polygraphe"
    if language.startswith("en"):
        return "polygraph frequently asked questions"
    if language.startswith("pt"):
        return "perguntas frequentes sobre o polígrafo"

    return "frequently asked questions"


def is_forbidden_workspace_link(url: str, workspace_id: str) -> bool:
    url = (url or "").lower()
    workspace_id = (workspace_id or "").lower()

    if workspace_id == "local.es":
        forbidden = [
            "/poligrafo-ao/",
            "/perguntas-respostas/",
            "/contato/",
            "poligrafoangola.com",
            "poligrafoportugal.com"
        ]
        return any(item in url for item in forbidden)

    return False

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
        "wordpress_review",
    ]

    if draft.get("draft_status") not in allowed_statuses:
        print(f"Draft must be in one of these statuses: {allowed_statuses}")
        print(f"Current status: {draft.get('draft_status')}")
        return

    content_block = draft.get("generated_content", {})
    content = content_block.get("content", "")
    content = remove_existing_internal_links(content)

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