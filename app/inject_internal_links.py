import json
import sys
import re
from pathlib import Path

from workspace_paths import (
    find_draft_any_workspace,
    get_workspace_draft_registry_path,
)

try:
    from internal_link_intelligence import get_internal_link_suggestions
except Exception:
    get_internal_link_suggestions = None

try:
    from gutenberg_blocks import render_strategic_links_block
except Exception:
    render_strategic_links_block = None


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



def infer_topic_key_from_draft(draft: dict) -> str:
    """
    Infer a structural topic key from draft metadata only.

    Do not hardcode language-specific anchor text here.
    The actual anchor labels belong in:
    - language_profile.json
    - page_presentation.json
    - data/page_blueprints.json
    """
    candidates = []

    page_plan = draft.get("page_plan") or {}
    strategy = draft.get("strategy") or {}
    generated_content = draft.get("generated_content") or {}

    for container in (draft, page_plan, strategy, generated_content):
        if not isinstance(container, dict):
            continue
        for key in [
            "topic_key",
            "primary_topic_key",
            "market_topic_key",
            "content_topic",
            "topic",
            "service_key",
            "intent_key",
        ]:
            value = container.get(key)
            if value:
                candidates.append(str(value).strip())

    for value in candidates:
        if value:
            return value

    return ""


def infer_page_type_from_draft(draft: dict) -> str:
    """
    Infer page type from draft metadata without language-specific assumptions.
    """
    page_plan = draft.get("page_plan") or {}
    strategy = draft.get("strategy") or {}

    for container in (draft, page_plan, strategy):
        if not isinstance(container, dict):
            continue
        for key in ["page_type", "content_type", "template_type", "blueprint_type"]:
            value = container.get(key)
            if value:
                return str(value).strip()

    return ""


def convert_intelligence_link_to_legacy_format(item: dict, draft: dict, topic_key: str = "") -> dict:
    """
    Convert internal_link_intelligence.py output into the legacy suggestion shape
    expected by this script.

    This allows Phase 1B integration without breaking the current Spain pilot.
    """
    url = str(item.get("url") or "").strip()
    anchor = str(item.get("anchor") or "").strip()

    if not url:
        return {}

    if not anchor:
        anchor = humanize_link_anchor_from_url(url)

    link_type = "supporting_information"

    url_lower = url.lower()
    if "contact" in url_lower or "contacto" in url_lower:
        link_type = "conversion"

    return {
        "target_url": url,
        "anchor_text": anchor,
        "target_title": anchor,
        "target_topic": topic_key or str(item.get("reason") or "").strip(),
        "source_topic": str(draft.get("target_keyword") or draft.get("working_title") or "").strip(),
        "relationship": "semantic_internal_link",
        "link_type": link_type,
        "source": item.get("source", "internal_link_intelligence"),
        "intelligence_score": item.get("score", 0),
    }


def load_intelligence_links_for_draft(workspace_id: str, draft: dict, limit: int = 6) -> list[dict]:
    """
    Optional Phase 1B source.

    Uses app/internal_link_intelligence.py when available.
    If unavailable or empty, returns [] and the old workflow continues.
    """
    if get_internal_link_suggestions is None:
        return []

    topic_key = infer_topic_key_from_draft(draft)
    page_type = infer_page_type_from_draft(draft)

    try:
        raw_links = get_internal_link_suggestions(
            workspace_id=workspace_id,
            topic_key=topic_key or None,
            page_type=page_type or None,
            limit=limit,
        )
    except Exception as e:
        print(f"Warning: internal link intelligence unavailable: {e}")
        return []

    converted = []
    for item in raw_links or []:
        converted_item = convert_intelligence_link_to_legacy_format(
            item=item,
            draft=draft,
            topic_key=topic_key,
        )
        if converted_item:
            converted.append(converted_item)

    return converted


def merge_internal_link_sources(primary_links: list[dict], fallback_links: list[dict]) -> list[dict]:
    """
    Prefer intelligence links, then append legacy links as fallback.
    Deduplicate by target_url.
    """
    merged = []
    used_urls = set()

    for link in list(primary_links or []) + list(fallback_links or []):
        url = str(link.get("target_url") or "").strip()
        if not url or url in used_urls:
            continue
        merged.append(link)
        used_urls.add(url)

    return merged



def load_internal_links(workspace_path: str):
    file_path = SOFIA_ROOT / workspace_path / "internal_link_suggestions.json"
    if not file_path.exists():
        raise FileNotFoundError(f"Missing internal links file: {file_path}")
    return load_json(file_path)["internal_link_suggestions"]


def load_language_profile(workspace_path: str):
    file_path = SOFIA_ROOT / workspace_path / "language_profile.json"
    if not file_path.exists():
        return {}
    return load_json(file_path)


def normalize_for_link_matching(value: str) -> str:
    value = str(value or "").lower()
    value = re.sub(r"https?://[^/]+", " ", value)
    value = re.sub(r"[^a-zA-ZÀ-ÿ0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def extract_link_terms(value: str, generic_terms: list[str]) -> set[str]:
    text = normalize_for_link_matching(value)
    generic = {normalize_for_link_matching(term) for term in generic_terms}
    terms = set()

    for term in text.split():
        if len(term) < 4:
            continue
        if term in generic:
            continue
        terms.add(term)

    return terms


def score_internal_link(link: dict, draft: dict, rules: dict) -> int:
    generic_terms = rules.get("generic_terms", [])

    draft_text = " ".join([
        str(draft.get("target_keyword", "")),
        str(draft.get("working_title", "")),
        str(draft.get("content_type", "")),
        str(draft.get("search_intent", "")),
        str(draft.get("suggested_slug", "")),
    ])

    link_text = " ".join([
        str(link.get("target_url", "")),
        str(link.get("source_url", "")),
        str(link.get("anchor_text", "")),
        str(link.get("source_topic", "")),
        str(link.get("target_topic", "")),
        str(link.get("relationship", "")),
        str(link.get("link_type", "")),
    ])

    draft_terms = extract_link_terms(draft_text, generic_terms)
    link_terms = extract_link_terms(link_text, generic_terms)

    overlap = draft_terms.intersection(link_terms)

    link_type_priority = rules.get("preferred_link_types", {})
    relationship_priority = rules.get("preferred_relationships", {})

    score = 0
    score += int(link_type_priority.get(link.get("link_type", ""), 0))
    score += int(relationship_priority.get(link.get("relationship", ""), 0))
    score += len(overlap) * 40

    # Topic-related links must have real semantic overlap with the draft.
    # Otherwise Sofia may insert unrelated service links into generic articles.
    if link.get("link_type") == "topic_related" and not overlap:
        return 0

    return score


def find_relevant_links(suggestions, draft=None, rules=None):
    """
    Select internal links structurally:
    - use workspace-defined link rules
    - prefer relevant source/target topic overlap
    - avoid unrelated topic_related links
    - keep conversion/supporting links when useful
    """

    draft = draft or {}
    rules = rules or {}

    max_links = int(rules.get("max_links", 3))
    if max_links < 1:
        max_links = 3

    scored = []

    workspace_id = str(rules.get("workspace_id", "") or rules.get("workspace", "") or "")

    for suggestion in suggestions:
        link_type = suggestion.get("link_type")

        target_url = suggestion.get("target_url", "")
        source_url = suggestion.get("source_url", "")

        if is_forbidden_workspace_link(target_url, workspace_id) or is_forbidden_workspace_link(source_url, workspace_id):
            continue

        if link_type not in ["conversion", "supporting_information", "topic_related"]:
            continue

        score = score_internal_link(suggestion, draft, rules)

        if score <= 0:
            continue

        scored.append((score, suggestion))

    scored.sort(key=lambda item: item[0], reverse=True)

    selected = []
    used_urls = set()
    used_types = set()

    for score, suggestion in scored:
        url = suggestion.get("target_url", "")
        link_type = suggestion.get("link_type", "")

        if not url or url in used_urls:
            continue

        # Keep variety: max 1 conversion, max 1 supporting, max 1 topic_related
        if link_type in used_types:
            continue

        selected.append(suggestion)
        used_urls.add(url)
        used_types.add(link_type)

        if len(selected) >= max_links:
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


def remove_old_fallback_sentences(content: str, link_rules: dict = None):
    """
    Remove stale fallback sentences from previous internal-link runs.

    Language-specific cleanup patterns must come from workspace JSON:
    language_profile.json -> internal_linking_rules.fallback_cleanup_patterns

    If no patterns are configured for the workspace/language, Sofia does not guess.
    This prevents the structural Python file from hardcoding Spanish, Portuguese,
    French, Turkish, Russian, Arabic, etc.
    """
    link_rules = link_rules or {}
    patterns = link_rules.get("fallback_cleanup_patterns", [])

    if not patterns:
        return content

    for pattern in patterns:
        if not pattern:
            continue

        content = re.sub(
            pattern,
            "",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )

    return re.sub(r"\s{2,}", " ", content)


def humanize_link_anchor_from_url(url: str) -> str:
    slug = str(url or "").strip("/").split("/")[-1]
    anchor = slug.replace("-", " ").replace("_", " ").strip()
    return anchor or str(url or "")


def remove_configured_strategic_links_block(content: str, heading: str, extra_headings=None) -> str:
    """
    Remove only configured strategic-link block headings from language_profile.
    No language-specific headings are hardcoded here.
    """
    headings = [str(heading or "").strip()]
    headings.extend([str(h or "").strip() for h in (extra_headings or [])])
    headings = [h for h in headings if h]

    for configured_heading in headings:
        pattern = (
            r'<h2>\\s*'
            + re.escape(configured_heading)
            + r'\\s*</h2>\\s*'
            + r'(?:<p>.*?</p>\\s*)*'
            + r'(?:<ul>.*?</ul>\\s*)?'
        )

        content = re.sub(
            pattern,
            "",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )

    return content



def remove_all_related_link_sections(content: str, link_rules: dict) -> str:
    """
    Remove all existing related/strategic link sections before injecting the controlled one.
    Headings come from workspace language_profile where possible.
    """
    headings = []

    configured = str(link_rules.get("strategic_links_heading") or "").strip()
    if configured:
        headings.append(configured)

    headings.extend(link_rules.get("strategic_links_cleanup_headings", []) or [])

    # Last-resort cleanup for already-generated Spanish pilot drafts.
    headings.extend([
        "Enlaces relacionados",
        "Enlaces Estratégicos",
        "Enlaces estratégicos",
        "Enlaces relevantes",
    ])

    headings = list(dict.fromkeys([h for h in headings if h]))

    if not headings:
        return content

    import re

    heading_pattern = "|".join(re.escape(h) for h in headings)

    pattern = (
        r'<h2>\s*(?:' + heading_pattern + r')\s*</h2>\s*'
        r'(?:<p>.*?</p>\s*)*'
        r'(?:<ul>.*?</ul>\s*)?'
    )

    return re.sub(pattern, "", content, flags=re.IGNORECASE | re.DOTALL).rstrip()


def append_strategic_links_block(content: str, links, link_rules: dict, already_used_urls=None):
    if not link_rules.get("allow_strategic_link_block_fallback"):
        return content, 0

    heading = str(link_rules.get("strategic_links_heading") or "").strip()
    if not heading:
        return content, 0

    required_links = int(
        link_rules.get("required_links")
        or link_rules.get("target_links")
        or link_rules.get("max_links")
        or 3
    )

    cleanup_headings = [heading]
    cleanup_headings.extend(link_rules.get("strategic_links_cleanup_headings", []) or [])

    content = remove_configured_strategic_links_block(
        content,
        heading,
        cleanup_headings,
    )

    already_used_urls = set(already_used_urls or [])
    used_urls = set(already_used_urls)
    items = []

    for link in links:
        url = str(link.get("target_url") or "").strip()
        if not url or url in used_urls:
            continue

        anchor = (
            str(link.get("target_title") or "").strip()
            or str(link.get("target_topic") or "").strip()
            or str(link.get("anchor_text") or "").strip()
            or humanize_link_anchor_from_url(url)
        )

        if not anchor or anchor.lower() == "auto":
            anchor = humanize_link_anchor_from_url(url)

        items.append({
            "url": url,
            "anchor": anchor,
        })
        used_urls.add(url)

        if len(items) >= required_links:
            break

    if not items:
        return content, 0

    content = remove_all_related_link_sections(content, link_rules)

    if render_strategic_links_block is not None:
        try:
            block = render_strategic_links_block(
                heading=heading,
                links=items,
            )
        except TypeError:
            block = render_strategic_links_block(heading, items)
        except Exception as e:
            print(f"Warning: Gutenberg strategic links block failed, using raw fallback: {e}")
            block = ""

        if block:
            return content.rstrip() + "\n" + block.strip() + "\n", len(items)

    raw_items = [
        f'<li><a href="{item.get("url")}">{item.get("anchor")}</a></li>'
        for item in items
        if item.get("url") and item.get("anchor")
    ]

    block = "\n".join([
        "",
        f"<h2>{heading}</h2>",
        "<ul>",
        *raw_items,
        "</ul>",
        "",
    ])

    return content.rstrip() + block, len(items)

def inject_links_into_html(content: str, links, language: str = '', link_rules: dict = None):
    link_rules = link_rules or {}
    """
    Smart linking:
    - derive keyword from target URL
    - try keyword match
    - fallback to paragraph injection
    Returns updated content and the number of links actually inserted.
    """

    inserted_count = 0

    for link in links:
        url = link.get("target_url", "")

        if not url:
            continue

        keyword = derive_keyword_from_link(link, language)

        if not keyword:
            continue

        before = content
        content, inserted = insert_link_once(content, keyword, url)

        if inserted:
            inserted_count += 1
            continue

        # Topic-related links should only be inserted when there is a natural
        # anchor in the text. Do not add generic fallback sentences for them.
        if link.get("link_type") == "topic_related":
            continue

        content = inject_fallback_link(content, keyword, url, language)

        if content != before:
            inserted_count += 1

    required_links = int(
        link_rules.get("required_links")
        or link_rules.get("target_links")
        or link_rules.get("max_links")
        or 3
    )

    if inserted_count < required_links:
        already_used_urls = []

        for link in links[:inserted_count]:
            url = link.get("target_url")
            if url:
                already_used_urls.append(url)

        content, block_count = append_strategic_links_block(
            content,
            links,
            link_rules,
            already_used_urls=already_used_urls,
        )
        inserted_count += block_count

    return content, inserted_count


def normalize_language_code(language: str) -> str:
    language = (language or "").lower()

    if language.startswith("pt"):
        return "pt"
    if language.startswith("es"):
        return "es"
    if language.startswith("fr"):
        return "fr"
    if language.startswith("en"):
        return "en"

    return ""


def derive_keyword_from_link(link: dict, language: str = ""):
    """
    Derive a non-generic anchor from suggestion metadata.
    Avoid generic anchors such as 'prueba del polígrafo'.
    """
    candidates = [
        link.get("anchor_text", ""),
        link.get("target_title", ""),
        link.get("target_topic", ""),
        link.get("target_slug", ""),
    ]

    generic_values = {
        "auto",
        "polígrafo",
        "poligrafo",
        "prueba del polígrafo",
        "teste de polígrafo",
        "test polygraphique",
        "polygraph test",
        "examen poligráfico",
        "prueba",
        "examen",
        "test",
        "servicio",
    }

    for candidate in candidates:
        candidate = str(candidate or "").strip()
        if not candidate:
            continue

        candidate = candidate.replace("-", " ").replace("_", " ").strip()
        if candidate.lower() in generic_values:
            continue

        if len(candidate.split()) < 2:
            continue

        return candidate.lower()

    return ""


def derive_keyword_from_url(url: str, language: str = ""):
    slug = url.strip("/").split("/")[-1]
    keyword = slug.replace("-", " ").replace("_", " ").lower()
    lang = normalize_language_code(language)

    replacements_by_language = {
        "es": {
            "faq": "preguntas frecuentes",
            "contact": "contacto",
            "contacto": "contacto",
            "contato": "contacto",
            "sobre": "sobre nosotros",
            "about": "sobre nosotros",
            "poligrafo": "prueba del polígrafo",
            "polygraph": "prueba del polígrafo",
            "infidelidade": "polígrafo por infidelidad",
            "furto": "polígrafo por robo o hurto",
            "roubo": "polígrafo por robo o hurto",
            "empresas": "polígrafo para empresas",
            "legal": "polígrafo en asuntos legales",
        },
        "pt": {
            "faq": "secção de perguntas frequentes",
            "perguntas": "secção de perguntas frequentes",
            "respostas": "secção de perguntas frequentes",
            "contact": "contacto",
            "contacto": "contacto",
            "contato": "contacto",
            "sobre": "sobre a nossa equipa",
            "about": "sobre a nossa equipa",
            "poligrafo": "teste de polígrafo",
            "polygraph": "polygraph test",
            "infidelidade": "testes de polígrafo para infidelidade",
            "furto": "testes de polígrafo para roubo ou furto",
            "roubo": "testes de polígrafo para roubo ou furto",
            "empresas": "testes de polígrafo para empresas",
            "legal": "testes de polígrafo para questões legais",
        },
        "fr": {
            "faq": "questions fréquentes",
            "contact": "contact",
            "contacto": "contact",
            "contato": "contact",
            "sobre": "à propos",
            "about": "à propos",
            "poligrafo": "test polygraphique",
            "polygraph": "test polygraphique",
            "infidelidade": "polygraphe pour infidélité",
            "furto": "polygraphe pour vol",
            "roubo": "polygraphe pour vol",
            "empresas": "polygraphe pour entreprises",
            "legal": "polygraphe dans un cadre juridique",
        },
        "en": {
            "faq": "frequently asked questions",
            "contact": "contact",
            "contacto": "contact",
            "contato": "contact",
            "sobre": "about us",
            "about": "about us",
            "poligrafo": "polygraph test",
            "polygraph": "polygraph test",
            "infidelidade": "infidelity polygraph test",
            "furto": "theft polygraph test",
            "roubo": "theft polygraph test",
            "empresas": "corporate polygraph test",
            "legal": "legal polygraph services",
        },
    }

    replacements = replacements_by_language.get(lang, {})

    for source, replacement in replacements.items():
        if source in keyword:
            return replacement

    # Safe fallback for Turkish, Russian, Arabic, etc.:
    # use neutral slug text only, never another language's anchor text.
    return keyword


def inject_fallback_link(content: str, keyword: str, url: str, language: str = ""):
    url_lower = url.lower()
    language = (language or "").lower()
    lang = normalize_language_code(language)

    # For unsupported languages such as Turkish, Russian, Arabic, etc.,
    # do not inject paragraph fallback sentences in the wrong language.
    # Exact keyword links may still be inserted by insert_link_once().
    if lang not in ["pt", "es", "fr", "en"]:
        return content

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
            return content

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

    intelligence_limit = 8
    intelligence_links = load_intelligence_links_for_draft(
        workspace_id=workspace_id,
        draft=draft,
        limit=intelligence_limit,
    )

    try:
        legacy_links = load_internal_links(draft.get("workspace_path"))
    except Exception as e:
        legacy_links = []
        print(f"Warning: legacy internal links unavailable: {e}")

    suggestions = merge_internal_link_sources(
        primary_links=intelligence_links,
        fallback_links=legacy_links,
    )

    if not suggestions:
        print("No internal link suggestions available.")
        return

    language_profile = load_language_profile(draft.get("workspace_path"))
    link_rules = language_profile.get("internal_linking_rules", {}) or {}
    link_rules = dict(link_rules)

    page_plan = draft.get("page_plan") or {}
    validation = page_plan.get("validation_requirements") or {}
    block_requirements = page_plan.get("block_requirements") or {}
    related_links = block_requirements.get("related_links") or {}

    required_links = (
        related_links.get("required_count")
        or validation.get("required_internal_link_count")
        or link_rules.get("required_links")
        or link_rules.get("target_links")
        or link_rules.get("max_links")
        or 3
    )

    try:
        required_links = int(required_links)
    except Exception:
        required_links = 3

    link_rules["required_links"] = required_links
    link_rules["target_links"] = max(
        int(link_rules.get("target_links", 0) or 0),
        required_links,
    )
    link_rules["max_links"] = max(
        int(link_rules.get("max_links", 0) or 0),
        required_links,
    )
    link_rules["allow_strategic_link_block_fallback"] = True

    content = remove_old_fallback_sentences(content, link_rules)

    link_rules["workspace_id"] = workspace_id

    selected_links = find_relevant_links(
        suggestions=suggestions,
        draft=draft,
        rules=link_rules,
    )

    if not selected_links:
        print("No suitable links found.")
        return

    language = (
        draft.get("language")
        or draft.get("locale")
        or "es"
    )

    updated_content, inserted_count = inject_links_into_html(
        content,
        selected_links,
        language,
        link_rules=link_rules
    )

    if inserted_count <= 0:
        print("No internal links were inserted into the content.")
        return

    if "generated_content" not in draft or not isinstance(draft["generated_content"], dict):
        draft["generated_content"] = {}

    draft["generated_content"]["content"] = updated_content
    draft["html_content"] = updated_content
    draft["draft_status"] = "internal_links_added"

    draft_data["scope"] = "workspace"
    draft_data["workspace_id"] = workspace_id
    save_json(draft_registry_file, draft_data)

    print(f"Internal links added to {draft_id}")
    print(f"Links injected: {inserted_count}")
    print(f"Workspace registry: {draft_registry_file}")


if __name__ == "__main__":
    main()