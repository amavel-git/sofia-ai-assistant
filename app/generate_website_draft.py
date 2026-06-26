import json
import re
import sys
import requests
from pathlib import Path
from datetime import datetime, timezone

from seo_field_rules import normalize_seo_fields
from workspace_paths import (
    get_workspace_draft_registry_path,
    empty_draft_registry,
)

from content_knowledge import (
    build_knowledge_package,
    format_package_for_prompt,
)

from page_blueprints import build_page_blueprint_package

from generation_package_builder import (
    build_generation_package,
    summarize_generation_package,
)

from content_architect import (
    build_content_architecture,
    summarize_architecture,
)

from section_contract_builder import (
    build_section_contracts,
    summarize_section_contracts,
)

from writer_agent import (
    build_full_page_writer_prompt,
    summarize_writer_input,
)

from editorial.pipeline import process_editorial_pipeline

IMAGE_ASSETS_DIR = Path(__file__).resolve().parent / "image_assets"
if str(IMAGE_ASSETS_DIR) not in sys.path:
    sys.path.insert(0, str(IMAGE_ASSETS_DIR))

from image_asset_planner import build_image_plan_for_draft
from image_plan_expander import expand_image_plan_with_in_article_images


BASE_DIR = Path(__file__).resolve().parent.parent

WORKSPACES_FILE = BASE_DIR / "data" / "workspaces.json"
PROMPT_FILE = BASE_DIR / "prompts" / "website_content_prompt.md"
# Deprecated: draft registries are now workspace-level.
GLOBAL_DRAFT_REGISTRY_FILE = BASE_DIR / "sites" / "draft_registry.json"

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "mistral-small:24b"

# ---------------------------------------------------------------------
# Content length strategy
# ---------------------------------------------------------------------
# Validation remains conservative.
# Generation should target substantially more words to avoid repairs.
# ---------------------------------------------------------------------
VALIDATION_MINIMUM_WORD_COUNT = 800
GENERATION_TARGET_WORD_COUNT = 1200
EXPANSION_MARGIN = 300


def load_json(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path: Path, data):
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_text(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return f.read()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def word_count(text):
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return len([w for w in text.split() if w.strip()])


def find_workspace(workspaces_data, workspace_id: str):
    for workspace in workspaces_data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def get_drafts(draft_registry):
    if isinstance(draft_registry, dict) and "drafts" in draft_registry:
        return draft_registry["drafts"]
    if isinstance(draft_registry, list):
        return draft_registry
    return []


def find_draft(draft_registry, draft_id):
    for draft in get_drafts(draft_registry):
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def slugify(text):
    text = text.lower().strip()
    replacements = {
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u",
        "ç": "c",
        "ñ": "n"
    }

    for original, replacement in replacements.items():
        text = text.replace(original, replacement)

    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def infer_locale(language: str, workspace_id: str, site_target: str):
    language = (language or "").lower().strip()
    workspace_id = (workspace_id or "").lower().strip()
    site_target = (site_target or "").lower().strip()

    language_aliases = {
        "spanish": "es",
        "español": "es",
        "espanol": "es",
        "castellano": "es",
        "portuguese": "pt",
        "português": "pt",
        "portugues": "pt",
        "french": "fr",
        "français": "fr",
        "francais": "fr",
        "english": "en",
    }

    language = language_aliases.get(language, language)

    if language in ["pt", "pt-pt"]:
        if "br" in workspace_id or "brasil" in site_target:
            return "pt-BR"
        return "pt-PT"

    if language == "pt-br":
        return "pt-BR"

    if language in ["en", "en-us", "en-gb"]:
        return "en-US"

    if language in ["es", "es-es"]:
        return "es-ES"

    if language in ["fr", "fr-fr"]:
        return "fr-FR"

    return language


def load_internal_links(workspace_folder: Path):
    suggestions_file = workspace_folder / "internal_link_suggestions.json"
    structure_file = workspace_folder / "site_structure.json"

    links = []

    if suggestions_file.exists():
        try:
            data = load_json(suggestions_file)

            items = (
                data.get("internal_link_suggestions")
                or data.get("suggestions")
                or []
            )

            for item in items:
                url = item.get("target_url") or item.get("url")
                anchor = item.get("anchor_text") or item.get("anchor") or ""

                if url:
                    links.append({
                        "url": url,
                        "anchor": anchor,
                        "source": "internal_link_suggestions",
                        "source_url": item.get("source_url", ""),
                        "source_slug": item.get("source_slug", ""),
                        "source_page_type": item.get("source_page_type", ""),
                        "target_slug": item.get("target_slug", ""),
                        "target_page_type": item.get("target_page_type", ""),
                        "link_type": item.get("link_type", ""),
                        "priority": item.get("priority", ""),
                        "reason": item.get("reason", "")
                    })
        except Exception:
            pass

    if not links and structure_file.exists():
        try:
            structure = load_json(structure_file)
            for page in structure.get("pages", []):
                url = page.get("url", "")
                slug = page.get("slug", "")
                page_type = page.get("page_type", "")

                if url:
                    links.append({
                        "url": url,
                        "anchor": slug or page_type or url,
                        "source": "site_structure"
                    })
        except Exception:
            pass

    return links[:40]

def load_page_presentation(workspace_folder: Path):
    path = workspace_folder / "page_presentation.json"

    if not path.exists():
        return {}

    try:
        return load_json(path)
    except Exception:
        return {}
    

def load_image_guidelines(workspace_folder: Path):
    path = workspace_folder / "image_guidelines.json"

    if not path.exists():
        return {}

    try:
        return load_json(path)
    except Exception:
        return {}


def format_internal_links(internal_links):
    if not internal_links:
        return "No internal links available. If none are relevant, include no forced internal links."

    lines = []

    for link in internal_links:
        lines.append(
            f"- URL: {link.get('url', '')} | Suggested anchor: {link.get('anchor', '')}"
        )

    return "\n".join(lines)


def normalize_text_for_matching(text):
    text = str(text or "").lower()
    replacements = {
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u",
        "ç": "c",
        "ñ": "n"
    }
    for a, b in replacements.items():
        text = text.replace(a, b)
    return text


def link_relevance_score(link, topic_text):
    topic = normalize_text_for_matching(topic_text)
    slug = normalize_text_for_matching(link.get("target_slug") or link.get("slug") or link.get("anchor") or link.get("url") or "")
    url = normalize_text_for_matching(link.get("url") or "")
    combined = f"{slug} {url}"

    score = 0

    topic_groups = {
        "fuel_or_theft": ["combustivel", "fuel", "furto", "roubo", "theft", "desvio"],
        "hr": ["recursos-humanos", "pre-employment", "emprego", "funcionarios", "employee"],
        "legal": ["legal", "casos-legais", "advogados", "justica", "inocencia"],
        "infidelity": ["infidelidade", "fidelidade", "casais"],
        "sexual": ["agressao-sexual", "sexual"]
    }

    for terms in topic_groups.values():
        if any(t in topic for t in terms) and any(t in combined for t in terms):
            score += 5

    if "perguntas-respostas" in combined or "faq" in combined:
        score += 2

    if "funcionamento-poligrafo" in combined:
        score += 2

    if "contato" in combined:
        score += 1

    if "infidelidade" in combined and not any(t in topic for t in ["infidelidade", "fidelidade", "casais"]):
        score -= 6

    if "agressao-sexual" in combined and "sexual" not in topic:
        score -= 6

    if "provar-inocencia" in combined and not any(t in topic for t in ["legal", "inocencia", "defesa"]):
        score -= 4

    if combined.strip() in ["", "home"]:
        score -= 10

    return score


def derive_anchor_text(link):
    anchor = (link.get("anchor") or "").strip()

    if not anchor:
        return None

    if anchor.upper() == "AUTO":
        return None

    if anchor.startswith("http"):
        return None

    # Avoid exposing slugs as public anchor text.
    if "-" in anchor:
        return None

    return anchor


def select_relevant_internal_links(internal_links, topic_text, max_links=4):
    scored = []

    for link in internal_links:
        url = link.get("url")
        if not url:
            continue

        score = link_relevance_score(link, topic_text)
        if score <= 0:
            continue

        link = dict(link)
        link["anchor"] = derive_anchor_text(link)
        if not link["anchor"]:
            continue
        link["_score"] = score
        scored.append(link)

    scored.sort(key=lambda x: x.get("_score", 0), reverse=True)

    unique = []
    seen = set()

    for link in scored:
        url = link.get("url")
        if url in seen:
            continue
        seen.add(url)
        unique.append(link)
        if len(unique) >= max_links:
            break

    return unique


def inject_contextual_internal_links(content, internal_links, topic_text, language_profile=None, page_presentation=None):
    html = str(content or "")
    internal_link_settings = {}
    if isinstance(page_presentation, dict):
        internal_link_settings = page_presentation.get("internal_links", {}) or {}

    if internal_link_settings.get("enabled") is False:
        return html, []

    target_links = internal_link_settings.get("target_links", 1)
    maximum_links = internal_link_settings.get("maximum_links", target_links)

    selected = select_relevant_internal_links(
        internal_links,
        topic_text,
        max_links=min(target_links, maximum_links)
    )

    if not selected:
        return html, []

    inserted = []

    internal_linking = {}

    if isinstance(language_profile, dict):
        internal_linking = (
            language_profile.get("internal_linking")
            or language_profile.get("content_strategy_templates", {}).get("internal_linking")
            or {}
        )

    phrase_templates = internal_linking.get("contextual_phrase_templates") or []

    if not phrase_templates:
        return html, []

    template = phrase_templates[0]

    insertion_rules = [
        {
            "keywords": ["roubo", "furto", "desvio", "fraude", "combustível", "combustivel"],
            "preferred_anchor_contains": ["roubo", "furto"]
        },
        {
            "keywords": ["processo", "perguntas", "exame", "avaliação", "poligráfica", "poligrafo"],
            "preferred_anchor_contains": ["funcionamento", "perguntas"]
        },
        {
            "keywords": ["empresa", "funcionários", "funcionarios", "recursos humanos", "equipa"],
            "preferred_anchor_contains": ["recursos humanos", "empresas"]
        }
    ]

    paragraphs = re.findall(r"<p>.*?</p>", html, flags=re.IGNORECASE | re.DOTALL)

    for link in selected:
        if link.get("url") in html:
            inserted.append(link)
            continue

        anchor = link.get("anchor")
        url = link.get("url")

        if not anchor or not url:
            continue

        linked = f'<a href="{url}">{anchor}</a>'
        sentence = template.format(link=linked).strip()

        placed = False

        for rule in insertion_rules:
            if placed:
                break

            if not any(term in normalize_text_for_matching(anchor) for term in rule["preferred_anchor_contains"]):
                continue

            for paragraph in paragraphs:
                plain = normalize_text_for_matching(re.sub(r"<[^>]+>", " ", paragraph))

                if not any(k in plain for k in [normalize_text_for_matching(x) for x in rule["keywords"]]):
                    continue

                if "<a " in paragraph.lower():
                    continue

                replacement = paragraph.replace(
                    "</p>",
                    f" {sentence}</p>",
                    1
                )

                html = html.replace(paragraph, replacement, 1)
                inserted.append(link)
                placed = True
                break

    return html, inserted


def build_internal_links_html(internal_links, topic_text="", max_links=3, language_profile=None):
    language_profile = language_profile or {}
    selected = select_relevant_internal_links(internal_links, topic_text, max_links=max_links)

    if not selected:
        return ""

    heading = get_internal_links_heading(language_profile)
    intro = get_internal_links_intro(language_profile)

    lines = [
        f"<h2>{heading}</h2>",
    ]

    if intro:
        lines.append(f"<p>{intro}</p>")

    lines.append("<ul>")

    for link in selected:
        url = link.get("url", "")
        anchor = link.get("anchor") or url
        lines.append(f'<li><a href="{url}">{anchor}</a></li>')

    lines.append("</ul>")

    return "\n".join(lines)


def ensure_internal_links_section(content, internal_links, topic_text="", language_profile=None, page_presentation=None):
    html = str(content or "")

    if not internal_links:
        return html

    html, inserted = inject_contextual_internal_links(
        html,
        internal_links,
        topic_text,
        language_profile=language_profile,
        page_presentation=page_presentation
    )

    if inserted:
        return html

    if any(link.get("url") and link.get("url") in html for link in internal_links):
        return html

    links_html = build_internal_links_html(
        internal_links,
        topic_text=topic_text,
        language_profile=language_profile
    )

    if not links_html:
        return html

    return html.rstrip() + "\n\n" + links_html




def get_opportunity_intelligence(draft: dict) -> dict:
    """
    Return the best available content intelligence object.

    opportunity_intelligence is the new source of truth.
    intake_intelligence is kept only as a fallback.
    """
    if not isinstance(draft, dict):
        return {}

    intelligence = draft.get("opportunity_intelligence") or {}
    if isinstance(intelligence, dict) and intelligence:
        return intelligence

    fallback = draft.get("intake_intelligence") or {}
    if isinstance(fallback, dict) and fallback:
        return fallback

    return {}


def trim_at_word_boundary(text: str, limit: int = 65) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text

    shortened = text[:limit].rsplit(" ", 1)[0].strip()
    return shortened or text[:limit].strip()


def build_intelligence_topic(draft: dict, fallback: str = "") -> str:
    intelligence = get_opportunity_intelligence(draft)

    issue = (
        intelligence.get("issue")
        or draft.get("issue")
        or ""
    )
    sector = (
        intelligence.get("sector")
        or draft.get("sector")
        or ""
    )

    if issue and sector:
        return f"{issue} {sector}"

    return (
        intelligence.get("recommended_focus_keyphrase")
        or draft.get("target_keyword")
        or draft.get("focus_keyphrase")
        or fallback
        or ""
    )


def apply_opportunity_intelligence_to_seo_fields(seo_fields: dict, draft: dict) -> dict:
    """
    Force SEO fields to use opportunity_intelligence when present.
    This prevents raw examiner wording such as 'cómo investigar sospechas...'
    from contaminating slug, keyphrase, title and metadata.
    """
    seo_fields = seo_fields or {}
    intelligence = get_opportunity_intelligence(draft)

    if not intelligence:
        return seo_fields

    recommended_keyphrase = intelligence.get("recommended_focus_keyphrase")
    recommended_slug = intelligence.get("recommended_slug")
    recommended_title = intelligence.get("recommended_seo_title")
    recommended_meta = intelligence.get("recommended_meta_description")

    if recommended_keyphrase:
        seo_fields["focus_keyphrase"] = recommended_keyphrase
        draft["focus_keyphrase"] = recommended_keyphrase
        draft["target_keyword"] = recommended_keyphrase

    if recommended_slug:
        seo_fields["slug"] = recommended_slug
        draft["slug"] = recommended_slug
        draft["suggested_slug"] = recommended_slug

    if recommended_title:
        seo_fields["seo_title"] = trim_at_word_boundary(recommended_title, 65)
        draft["seo_title"] = seo_fields["seo_title"]

    if recommended_meta:
        seo_fields["meta_description"] = trim_at_word_boundary(recommended_meta, 155)
        draft["meta_description"] = seo_fields["meta_description"]

    if intelligence.get("recommended_h1"):
        draft["title"] = intelligence.get("recommended_h1")
        draft["working_title"] = intelligence.get("recommended_h1")
        draft["page_h1"] = intelligence.get("recommended_h1")

    if intelligence.get("recommended_title"):
        draft["normalized_title"] = intelligence.get("recommended_title")

    return seo_fields




def format_opportunity_intelligence_for_prompt(draft: dict) -> str:
    intelligence = get_opportunity_intelligence(draft)

    if not intelligence:
        return "No opportunity intelligence package available."

    lines = []
    lines.append("OPPORTUNITY INTELLIGENCE PACKAGE")
    lines.append("")
    lines.append("Use this package as topic-specific drafting guidance.")
    lines.append("Do not mention this package in the final page.")
    lines.append("")

    for label, key in [
        ("Issue", "issue"),
        ("Sector", "sector"),
        ("Topic family", "topic_family"),
        ("Visual topic family", "visual_topic_family"),
        ("Service angle", "service_angle"),
        ("Search intent", "search_intent"),
    ]:
        value = intelligence.get(key)
        if value:
            lines.append(f"{label}: {value}")

    content_angles = intelligence.get("content_angles") or []
    if content_angles:
        lines.append("")
        lines.append("Content angles to include as real section themes:")
        for item in content_angles:
            lines.append(f"- {item}")

        lines.append("")
        lines.append("Suggested H2 theme mapping:")
        lines.append("Use these as topic-specific section ideas when they fit the locked page plan.")
        lines.append("Do not output these exact English phrases if the workspace language is different.")
        lines.append("Translate/adapt them naturally into the workspace language.")
        for item in content_angles:
            lines.append(f"- Create or enrich one major section around: {item}")

        lines.append("")
        lines.append("Mandatory content-angle rule:")
        lines.append("- At least 3 major non-FAQ sections must clearly use these content angles.")
        lines.append("- The first half of the page must include concrete operational details from these angles.")
        lines.append("- Do not merely mention the issue; explain how it appears in real client situations.")
        lines.append("- Each major content-angle section should contain at least 2 substantial paragraphs.")
        lines.append("- Include practical examples of how the problem is detected, why responsibility is difficult to clarify, and what internal information may be reviewed.")
        lines.append("- Do not stop after a short overview; develop the operational, investigative, and decision-making context.")

    visual_scenarios = intelligence.get("visual_scenarios") or {}
    if visual_scenarios:
        lines.append("")
        lines.append("Concrete investigation/problem scenarios to use naturally:")
        for role, scenarios in visual_scenarios.items():
            if not scenarios:
                continue
            lines.append(f"- {role}:")
            for item in scenarios[:4]:
                lines.append(f"  - {item}")

    faq_topics = intelligence.get("faq_topics") or []
    if faq_topics:
        lines.append("")
        lines.append("FAQ themes to prioritize:")
        for item in faq_topics:
            lines.append(f"- {item}")

        lines.append("")
        lines.append("FAQ drafting rule:")
        lines.append("- FAQ questions must be specific to the issue and sector, not generic polygraph FAQs.")
        lines.append("- Include questions about the suspected problem, employee involvement, documents/records, confidentiality, consent, limits, and how the examination fits into a broader investigation.")
        lines.append("- At least half of the FAQ items must directly mention or clearly relate to the issue, sector, or investigation scenario.")
        lines.append("- Do not repeat generic questions already answered in the main body unless they are adapted to this specific case.")
        lines.append("- Write every FAQ question and answer exclusively in the workspace language.")
        lines.append("- Include the full required FAQ count from the locked page plan. If the plan asks for 8, write 8 FAQ items.")

    internal_link_topics = intelligence.get("internal_link_topics") or []
    if internal_link_topics:
        lines.append("")
        lines.append("Internal-link topical focus:")
        for item in internal_link_topics:
            lines.append(f"- {item}")

    recommended_h1 = intelligence.get("recommended_h1")
    recommended_focus = intelligence.get("recommended_focus_keyphrase")
    if recommended_h1 or recommended_focus:
        lines.append("")
        lines.append("Canonical SEO/content focus:")
        if recommended_h1:
            lines.append(f"- H1: {recommended_h1}")
        if recommended_focus:
            lines.append(f"- Focus keyphrase: {recommended_focus}")

    return "\n".join(lines).strip()



def build_draft_context(draft, workspace):
    draft_input = draft.get("draft_input", {}) or {}
    seo_input = draft_input.get("seo", {}) or {}

    title = (
        seo_input.get("page_title")
        or draft_input.get("page_title")
        or draft_input.get("title")
        or draft.get("working_title")
        or draft.get("title")
        or draft.get("draft_title")
        or ""
    )

    focus_keyphrase = (
        seo_input.get("focus_keyphrase")
        or draft_input.get("focus_keyphrase")
        or draft.get("target_keyword")
        or draft.get("focus_keyphrase")
        or ""
    )

    secondary_keywords = draft.get("secondary_keywords", [])
    if isinstance(secondary_keywords, str):
        secondary_keywords = [secondary_keywords]

    language = draft.get("language") or workspace.get("language", "")
    site_target = draft.get("site_target") or workspace.get("domain", "")
    locale = draft.get("locale") or infer_locale(language, workspace.get("workspace_id", ""), site_target)

    return {
        "title": title,
        "focus_keyphrase": focus_keyphrase,
        "secondary_keywords": secondary_keywords,
        "language": language,
        "locale": locale,
        "site_target": site_target,
        "content_type": draft.get("content_type", "seo_page"),
        "search_intent": draft.get("search_intent", "informational and commercial"),
        "suggested_slug": draft.get("slug") or draft.get("suggested_slug") or slugify(title),
        "idea_summary": draft.get("notes") or draft.get("summary") or title,
        "market": workspace.get("market_code", ""),
        "country": workspace.get("country", ""),
        "domain": workspace.get("domain", "")
    }


def extract_draft_strategy(draft: dict) -> dict:
    draft_input = draft.get("draft_input", {}) or {}
    strategy = (
        draft_input.get("strategy", {})
        or draft.get("strategy", {})
        or draft.get("content_strategy_brief", {})
        or {}
    )

    if not isinstance(strategy, dict):
        return {}

    return strategy


def format_strategy_for_prompt(strategy: dict) -> str:
    if not strategy:
        return "No structured content strategy package available."

    lines = []

    strategy_version = strategy.get("strategy_version", "")
    if strategy_version:
        lines.append(f"Strategy version: {strategy_version}")

    page_blueprint = strategy.get("page_blueprint", {}) or {}
    blueprint_id = page_blueprint.get("blueprint_id", "")
    if blueprint_id:
        lines.append(f"Recommended blueprint: {blueprint_id}")

    content_focus = strategy.get("content_focus", {}) or {}
    if content_focus:
        lines.append("")
        lines.append("Content focus strategy:")
        lines.append(f"- Focus keyphrase: {content_focus.get('focus_keyphrase', '')}")
        lines.append(f"- Topic: {content_focus.get('topic', '')}")
        lines.append(f"- Topical focus target: {content_focus.get('topical_focus_target', '')}")
        lines.append(f"- Generic content limit: {content_focus.get('generic_content_limit', '')}")

        balance = content_focus.get("preferred_content_balance", {}) or {}
        if balance:
            lines.append("- Preferred content balance:")
            for key, value in balance.items():
                lines.append(f"  - {key}: {value}")

        for item in content_focus.get("guidance", []) or []:
            lines.append(f"- {item}")

    topic_intelligence = content_focus.get("topic_intelligence", {}) or {}
    if topic_intelligence:
            lines.append("")
            lines.append("Topic intelligence:")
            
            topic_tags = topic_intelligence.get("topic_tags", []) or []
            if topic_tags:
                lines.append("- Topic tags: " + ", ".join(topic_tags))

            pain_points = topic_intelligence.get("client_pain_points", []) or []
            if pain_points:
                lines.append("- Client pain points:")
                for item in pain_points:
                    lines.append(f"  - {item}")

            scenarios = topic_intelligence.get("investigation_scenarios", []) or []
            if scenarios:
                lines.append("- Investigation scenarios:")
                for item in scenarios:
                    lines.append(f"  - {item}")

            examples = topic_intelligence.get("topic_specific_examples", []) or []
            if examples:
                lines.append("- Topic-specific examples:")
                for item in examples:
                    lines.append(f"  - {item}")

            questions = topic_intelligence.get("questions_the_page_should_answer", []) or []
            if questions:
                lines.append("- Questions the page should answer:")
                for item in questions:
                    lines.append(f"  - {item}")

    professional_situation = content_focus.get("professional_situation", {}) or {}
    if professional_situation:
            lines.append("")
            lines.append("Professional situation:")
            for key in [
                "typical_client_problem",
                "typical_investigation_trigger",
                "operational_context",
                "why_evidence_may_be_insufficient",
                "decision_pressure",
                "professional_objective",
                "editorial_perspective",
            ]:
                value = professional_situation.get(key)
                if value:
                    lines.append(f"- {key}: {value}")

            page_questions = professional_situation.get("page_should_answer", []) or []
            if page_questions:
                lines.append("- Page should answer:")
                for item in page_questions:
                    lines.append(f"  - {item}")

    faq_strategy = strategy.get("faq_strategy", {}) or {}
    if faq_strategy:
        lines.append("")
        lines.append("FAQ strategy:")
        lines.append(f"- FAQ required: {faq_strategy.get('required', True)}")
        lines.append(f"- Minimum questions: {faq_strategy.get('minimum_questions', '')}")
        lines.append(f"- Maximum questions: {faq_strategy.get('maximum_questions', '')}")
        lines.append(f"- Question style: {faq_strategy.get('question_style', '')}")

        for item in faq_strategy.get("guidance", []) or []:
            lines.append(f"- {item}")

    conversion_strategy = strategy.get("conversion_strategy", {}) or {}
    if conversion_strategy:
        lines.append("")
        lines.append("Conversion and trust strategy:")
        lines.append(f"- Primary goal: {conversion_strategy.get('primary_goal', '')}")
        lines.append(f"- Contact style: {conversion_strategy.get('cta_style', '')}")
        lines.append(f"- Trust block required: {conversion_strategy.get('trust_block_required', '')}")
        lines.append(f"- Local relevance required: {conversion_strategy.get('local_relevance_required', '')}")
        lines.append(f"- Internal links required: {conversion_strategy.get('internal_links_required', '')}")

        for item in conversion_strategy.get("guidance", []) or []:
            lines.append(f"- {item}")

    quality_controls = strategy.get("quality_controls", {}) or {}
    if quality_controls:
        lines.append("")
        lines.append("Quality controls:")
        for key, value in quality_controls.items():
            lines.append(f"- {key}: {value}")

    required_sections = strategy.get("required_sections", []) or []
    if required_sections:
        lines.append("")
        lines.append("Required section IDs from strategy:")
        for section_id in required_sections:
            lines.append(f"- {section_id}")

    return "\n".join(lines).strip() or "No structured content strategy package available."


def format_page_plan_for_prompt(page_plan: dict) -> str:
    """
    Convert locked page_plan into strict generation instructions.

    The page_plan is the source of truth for section order, required sections,
    FAQ count, internal link count, and rendering expectations.
    """
    if not isinstance(page_plan, dict) or not page_plan:
        return "No locked page_plan available."

    lines = []
    lines.append("LOCKED PAGE PLAN")
    lines.append("")
    lines.append(f"Page plan version: {page_plan.get('version', '')}")
    lines.append(f"Locked: {page_plan.get('locked', False)}")
    lines.append(f"Blueprint ID: {page_plan.get('blueprint_id', '')}")
    lines.append(f"Page type: {page_plan.get('page_type', '')}")
    lines.append(f"Search intent: {page_plan.get('search_intent', '')}")
    lines.append(f"Target keyword: {page_plan.get('target_keyword', '')}")
    lines.append("")
    lines.append("CRITICAL PAGE PLAN RULES:")
    lines.append("- This page_plan overrides generic prompt structure.")
    lines.append("- Follow the required section order exactly.")
    lines.append("- Do not omit required sections.")
    lines.append("- Do not invent unrelated H2 sections.")
    lines.append("- Use natural visitor-facing headings, not section IDs.")
    lines.append("- Each required non-FAQ/non-contact section should contain substantial body text.")
    lines.append("- Repair and validation must later check against this same plan.")
    lines.append("")

    required_sections = page_plan.get("required_sections") or []
    if required_sections:
        lines.append("Required section order:")
        for index, section in enumerate(required_sections, start=1):
            lines.append(
                f"{index}. {section.get('id', '')} "
                f"({section.get('type', '')})"
            )
            purpose = section.get("purpose", "")
            if purpose:
                lines.append(f"   Purpose: {purpose}")
            min_words = section.get("min_words")
            if min_words is not None:
                lines.append(f"   Minimum words: {min_words}")
        lines.append("")

    optional_sections = page_plan.get("optional_sections") or []
    if optional_sections:
        lines.append("Optional sections:")
        for section in optional_sections:
            lines.append(
                f"- {section.get('id', '')} "
                f"({section.get('type', '')}): {section.get('purpose', '')}"
            )
        lines.append("")

    topic_profile = page_plan.get("topic_intelligence_profile") or {}
    if topic_profile:
        lines.append("Topic intelligence profile:")
        for key in [
            "topic_family",
            "problem_angle",
            "consequence_angle",
            "investigation_angle",
            "process_angle",
            "faq_angle",
        ]:
            if topic_profile.get(key):
                lines.append(f"- {key}: {topic_profile.get(key)}")
        lines.append("")

    section_intelligence = page_plan.get("section_intelligence") or {}
    if section_intelligence:
        lines.append("Section-specific drafting intelligence:")
        for section_id, guidance in section_intelligence.items():
            if not isinstance(guidance, dict):
                continue
            lines.append(f"- {section_id}:")
            lines.append(f"  Section type: {guidance.get('section_type', '')}")
            lines.append(f"  Topic family: {guidance.get('topic_family', '')}")
            lines.append(f"  Drafting focus: {guidance.get('drafting_focus', '')}")
            avoid = guidance.get("avoid") or []
            if avoid:
                lines.append("  Avoid: " + "; ".join(str(item) for item in avoid))
        lines.append("")

    validation = page_plan.get("validation_requirements") or {}
    if validation:
        lines.append("Validation requirements:")
        for key in [
            "minimum_word_count",
            "minimum_faq_items",
            "required_internal_link_count",
            "requires_cta",
            "requires_trust_block",
            "requires_featured_image",
            "requires_hero_image",
        ]:
            if key in validation:
                lines.append(f"- {key}: {validation.get(key)}")
        lines.append("")

    blocks = page_plan.get("block_requirements") or {}
    faq = blocks.get("faq") or {}
    if faq:
        lines.append("FAQ requirements:")
        lines.append(f"- Required: {faq.get('required', False)}")
        lines.append(f"- Minimum items: {faq.get('minimum_items', '')}")
        lines.append(f"- Preferred format: {faq.get('preferred_format', '')}")
        lines.append("")

    related_links = blocks.get("related_links") or {}
    if related_links:
        lines.append("Internal link requirements:")
        lines.append(f"- Required count: {related_links.get('required_count', 0)}")
        lines.append(f"- Rendering: {related_links.get('rendering', '')}")
        lines.append("")

    cta = blocks.get("cta") or {}
    if cta:
        lines.append("Contact / next-step requirements:")
        lines.append(f"- Required: {cta.get('required', False)}")
        lines.append(f"- Rendering: {cta.get('rendering', '')}")
        lines.append("")

    trust = blocks.get("trust") or {}
    if trust:
        lines.append("Trust requirements:")
        lines.append(f"- Required: {trust.get('required', False)}")
        lines.append(f"- Rendering: {trust.get('rendering', '')}")
        lines.append("")

    image_slots = page_plan.get("image_slots") or []
    if image_slots:
        lines.append("Image planning requirements:")
        for slot in image_slots:
            lines.append(
                f"- {slot.get('slot_id', '')}: "
                f"required={slot.get('required', False)}, "
                f"role={slot.get('role', '')}, "
                f"style={slot.get('preferred_style', '')}"
            )
        lines.append("")

    generation_contract = page_plan.get("generation_contract") or {}
    if generation_contract:
        lines.append("Generation contract:")
        for key, value in generation_contract.items():
            lines.append(f"- {key}: {value}")
        lines.append("")

    return "\n".join(lines).strip()


def get_page_plan_minimum_word_count(page_plan: dict, fallback: int = 800) -> int:
    validation = (page_plan or {}).get("validation_requirements") or {}
    try:
        return int(validation.get("minimum_word_count") or fallback)
    except Exception:
        return fallback


def get_page_plan_required_link_count(page_plan: dict, fallback: int = 1) -> int:
    validation = (page_plan or {}).get("validation_requirements") or {}
    blocks = (page_plan or {}).get("block_requirements") or {}
    related = blocks.get("related_links") or {}

    for value in [
        related.get("required_count"),
        validation.get("required_internal_link_count"),
    ]:
        try:
            value = int(value)
            if value > 0:
                # Generate more FAQs than validation minimum to reduce repair loops.
                return max(value, 6)
        except Exception:
            continue

    return fallback


def get_page_plan_faq_count(page_plan: dict, fallback: int = 8) -> int:
    blocks = (page_plan or {}).get("block_requirements") or {}
    faq = blocks.get("faq") or {}
    validation = (page_plan or {}).get("validation_requirements") or {}

    for value in [
        faq.get("minimum_items"),
        validation.get("minimum_faq_items"),
    ]:
        try:
            value = int(value)
            if value > 0:
                # Generate more FAQ items than the validation minimum.
                # Validator can still accept 4, but generation should aim higher
                # to reduce repair loops and improve FAQ quality.
                return max(value, 8)
        except Exception:
            continue

    return fallback




def build_blueprint_package_for_draft(draft: dict) -> dict:
    """
    Resolve the blueprint package for draft generation.

    Priority:
    1. draft_input.blueprint_id
    2. draft.blueprint_id
    3. strategy.page_blueprint.blueprint_id
    4. fallback package generated from draft fields

    This keeps blueprint selection upstream and prevents the generator from
    guessing page architecture from content_type alone.
    """
    draft_input = draft.get("draft_input", {}) or {}
    strategy = extract_draft_strategy(draft)
    page_blueprint = strategy.get("page_blueprint", {}) or {}

    explicit_blueprint_id = (
        draft_input.get("blueprint_id")
        or draft.get("blueprint_id")
        or page_blueprint.get("blueprint_id")
        or ""
    )

    source = dict(draft)
    source["blueprint_id"] = explicit_blueprint_id
    source["page_type"] = (
        draft_input.get("page_type")
        or draft.get("page_type")
        or page_blueprint.get("page_type")
        or draft.get("content_type")
        or ""
    )

    package = build_page_blueprint_package(source)

    strategy_prompt_text = page_blueprint.get("prompt_text", "")
    if strategy_prompt_text:
        package["prompt_text"] = strategy_prompt_text

    return package



def format_terminology_guidance_for_prompt(language_profile: dict) -> str:
    guidance = language_profile.get("terminology_guidance", {}) if isinstance(language_profile, dict) else {}

    if not guidance:
        return "No workspace terminology guidance configured."

    lines = []
    lines.append("WORKSPACE TERMINOLOGY GUIDANCE")
    lines.append("")
    lines.append("Use this as soft writing guidance. Do not block generation.")
    lines.append("Prefer professional, cautious wording. If a discouraged term appears naturally, validation may warn the examiner.")
    lines.append("")

    preferred_terms = guidance.get("preferred_terms", []) or []
    if preferred_terms:
        lines.append("Preferred terms:")
        for term in preferred_terms:
            lines.append(f"- {term}")
        lines.append("")

    discouraged_terms = guidance.get("discouraged_terms", []) or []
    if discouraged_terms:
        lines.append("Discouraged terms and preferred alternatives:")
        for item in discouraged_terms:
            if isinstance(item, dict):
                term = item.get("term", "")
                alternative = item.get("preferred_alternative", "")
                reason = item.get("reason", "")
                lines.append(f"- Avoid: {term}")
                if alternative:
                    lines.append(f"  Prefer: {alternative}")
                if reason:
                    lines.append(f"  Reason: {reason}")
            else:
                lines.append(f"- Avoid: {item}")
        lines.append("")

    return "\n".join(lines).strip()



def get_contact_phrase_examples(language_profile):
    preferred = language_profile.get("preferred_terms", {}) if isinstance(language_profile, dict) else {}

    examples = (
        preferred.get("contact_phrase_examples")
        or preferred.get("contact_examples")
        or []
    )

    if isinstance(examples, str):
        examples = [examples]

    examples = [str(item).strip() for item in examples if str(item).strip()]

    if not examples:
        fallback = preferred.get("cta_contact_heading") or preferred.get("contact_anchor") or "Contact us"
        examples = [fallback]

    return "\n".join(f"- {item}" for item in examples)


def get_internal_links_heading(language_profile):
    rules = language_profile.get("internal_linking_rules", {}) if isinstance(language_profile, dict) else {}
    return (
        rules.get("strategic_links_heading")
        or language_profile.get("preferred_terms", {}).get("internal_links_heading")
        or "Related links"
    )


def get_internal_links_intro(language_profile):
    rules = language_profile.get("internal_linking_rules", {}) if isinstance(language_profile, dict) else {}
    return (
        rules.get("strategic_links_intro")
        or language_profile.get("preferred_terms", {}).get("internal_links_intro")
        or ""
    )



def get_language_output_rules(language_profile: dict, context: dict) -> str:
    """
    Profile-driven language instructions.
    Structural generator stays language-agnostic.
    Workspace-specific wording lives in language_profile.json.
    """
    language_profile = language_profile or {}
    guard = language_profile.get("language_guard") or {}
    language_name = (
        guard.get("target_language_name")
        or language_profile.get("language_name")
        or context.get("language")
        or context.get("locale")
        or "the workspace language"
    )

    lines = [
        "LANGUAGE ENFORCEMENT",
        "",
        f"The entire output must be written exclusively in {language_name}.",
        "All headings, paragraphs, lists, FAQs, and contact sections must use only the workspace language.",
        "Before returning the final HTML, review every heading and paragraph and remove or translate any foreign-language text.",
    ]

    forbidden = guard.get("forbidden_language_markers") or []
    if forbidden:
        lines.append("")
        lines.append("Do not use language markers from other configured languages, including:")
        for item in forbidden[:20]:
            lines.append(f"- {item}")

    return "\n".join(lines).strip()


def get_faq_heading_instruction(language_profile: dict) -> str:
    """
    Return the configured FAQ heading from language_profile.json.
    """
    language_profile = language_profile or {}
    preferred = language_profile.get("preferred_terms") or {}
    repair = ((language_profile.get("content_repair") or {}).get("faq_rebuild") or {})

    heading = (
        preferred.get("faq_heading")
        or repair.get("heading")
        or "Frequently Asked Questions"
    )

    return f'FAQ section requirement: use exactly <h2>{heading}</h2>.'


def get_polygraph_terminology_rules(language_profile: dict) -> str:
    """
    Profile-driven professional terminology guidance.
    """
    language_profile = language_profile or {}
    terminology = language_profile.get("terminology_guidance") or {}
    preferred = terminology.get("preferred_terms") or []
    discouraged = terminology.get("discouraged_terms") or []

    lines = [
        "Professional polygraph terminology:",
        "- Do not say the polygraph detects lies directly.",
        "- Do not describe the polygraph as infallible, guaranteed, or 100% accurate.",
        "- Do not present the result as legal proof.",
        "- Explain that the polygraph records physiological responses associated with specific questions.",
        "- Include limitations, ethical considerations, and the need for professional review.",
    ]

    if preferred:
        lines.append("- Prefer configured workspace terminology:")
        for item in preferred[:12]:
            lines.append(f"  - {item}")

    if discouraged:
        lines.append("- Avoid configured discouraged terminology when possible:")
        for item in discouraged[:12]:
            if isinstance(item, dict):
                term = item.get("term", "")
                alt = item.get("preferred_alternative", "")
                if alt:
                    lines.append(f"  - Avoid: {term}; prefer: {alt}")
                elif term:
                    lines.append(f"  - Avoid: {term}")
            else:
                lines.append(f"  - Avoid: {item}")

    return "\n".join(lines).strip()



def fill_prompt(
    template: str,
    draft: dict,
    workspace: dict,
    internal_links_text: str,
    knowledge_prompt: str = "",
    blueprint_prompt: str = "",
    strategy_prompt: str = "",
    page_plan_prompt: str = "",
    terminology_prompt: str = "",
    opportunity_intelligence_prompt: str = "",
    language_profile: dict = None,
):
    language_profile = language_profile or {}
    context = build_draft_context(draft, workspace)
    page_plan = draft.get("page_plan") or {}
    minimum_word_count = get_page_plan_minimum_word_count(
        page_plan,
        fallback=VALIDATION_MINIMUM_WORD_COUNT
    )

    # Generate well above validation minimum to reduce repair loops.
    generation_word_target = max(
        minimum_word_count + EXPANSION_MARGIN,
        GENERATION_TARGET_WORD_COUNT
    )

    required_faq_count = get_page_plan_faq_count(page_plan, fallback=8)
    required_internal_link_count = get_page_plan_required_link_count(page_plan, fallback=1)

    replacements = {
        "{{language}}": context["language"],
        "{{locale}}": context["locale"],
        "{{market}}": context["market"],
        "{{country}}": context["country"],
        "{{content_type}}": context["content_type"],
        "{{idea_title}}": context["title"],
        "{{idea_summary}}": context["idea_summary"],
        "{{target_keyword}}": context["focus_keyphrase"],
        "{{focus_keyphrase}}": context["focus_keyphrase"],
        "{{secondary_keywords}}": ", ".join(context["secondary_keywords"]),
        "{{search_intent}}": context["search_intent"],
        "{{suggested_slug}}": context["suggested_slug"],
        "{{site_target}}": context["site_target"],
        "{{domain}}": context["domain"],
        "{{internal_links}}": internal_links_text,
        "{{minimum_word_count}}": str(generation_word_target)
    }

    prompt = template

    for key, value in replacements.items():
        prompt = prompt.replace(key, str(value))

    knowledge_rules = f"""

CONTROLLED KNOWLEDGE PACKAGE

Use the following approved professional reference material as semantic guidance only.

IMPORTANT KNOWLEDGE RULES:
- Do NOT copy knowledge blocks verbatim.
- Do NOT mirror sentence structure from the source blocks.
- Extract concepts and rewrite them naturally.
- Adapt terminology to the workspace language and country.
- Maintain professional, ethical, and legally cautious wording.
- Preserve local terminology consistency.
- Avoid duplicate-content behavior across workspaces.
- Use the knowledge blocks to strengthen:
  - professional explanations
  - FAQ quality
  - limitations
  - procedural clarity
  - ethical safeguards
  - realistic expectations
  - localized terminology
  - service explanations

{knowledge_prompt}
""".strip()

    strategy_rules = f"""

CONTENT STRATEGY PACKAGE

Use the following structured strategy package to guide the page.

IMPORTANT STRATEGY RULES:
- This strategy controls page intent, FAQ depth, conversion style, and quality priorities.
- Do not mention the strategy package in the final page.
- Keep the page focused on the focus keyphrase and search intent.
- Most of the page should support the main topic directly.
- Generic polygraph explanation should be brief and secondary.
- Prefer topic-specific FAQs over generic filler.
- Use visitor-facing contact wording only. Do not use internal marketing terms.
- The topic intelligence package is mandatory when available.
- Use the client pain points, investigation scenarios, topic-specific examples, and questions the page should answer.
- The first half of the page must be shaped primarily by the topic intelligence package, not by generic polygraph explanations.
- Do not rely primarily on the approved knowledge blocks to understand the business problem.
- Approved knowledge blocks should mainly support professional wording, limits, ethics, consent, process, and FAQ accuracy.
- If topic intelligence contains procurement, supplier, invoice, fuel, warehouse, inventory, or internal investigation scenarios, include those scenarios naturally in the page body.

{strategy_prompt}
""".strip()

    drafting_personality_rules = f"""

DRAFTING PERSONALITY AND CONVERSION STRATEGY

You are a professional SEO and content strategist specialized in:
- polygraph services
- corporate investigations
- employee theft investigations
- fraud prevention
- integrity screening
- investigative interviewing
- local lead generation for professional services

Your goal is NOT to write a generic encyclopedia article.

Your goal is to create:
- persuasive service landing pages
- professional trust-oriented content
- commercially appealing content
- locally relevant business content
- conversion-oriented SEO pages

WRITING STYLE REQUIREMENTS

The content should feel:
- professional
- trustworthy
- locally adapted
- human-written
- search-intent relevant
- clear and practical
- persuasive without exaggeration

IMPORTANT:
- Avoid sounding like Wikipedia.
- Avoid generic AI filler.
- Avoid repetitive definitions.
- Avoid overexplaining the polygraph scientifically.
- Follow the active page blueprint for whether the page should focus on education, authority, service, local relevance, pricing, or broad topic coverage.

SEARCH INTENT AND PAGE-TYPE PRIORITY

Before drafting, identify the page type and search intent from the active blueprint.

The opening logic must depend on the active page type:

- landing_page: start with the visitor's practical problem, suspicion, commercial concern, or service need.
- city_page: start with local service availability and careful local relevance.
- pricing_page: start with price context, price ranges, or quotation factors.
- educational_page: start with a clear explanation of the topic and why it matters professionally.
- authority_page: start with the standard, research topic, professional body, or authority concept.
- blog_post: answer the reader's question directly before expanding the topic.
- pillar_page: start with a broad topic overview and explain the scope of the hub page.

Do not force pain-point/service-page structure onto educational, authority, blog, pricing, FAQ, or pillar pages.

GENERIC CONTENT CONTROL

Avoid starting with:
- dictionary definitions unless the blueprint is educational_page or authority_page
- historical explanations unless the page topic requires it
- scientific explanations before practical relevance
- generic descriptions of the polygraph that could fit any page

For commercial landing pages, explain the client problem before explaining the polygraph.
For educational pages, define the concept clearly but avoid generic filler.
For authority pages, define the authority topic and then explain professional relevance.
For blog posts, answer the query directly and then add context.
For city pages, avoid tourism filler and avoid invented local presence.

SECTION ORDER GUIDELINES

Preferred order for landing_page:
1. Client problem / pain point
2. Consequences and concerns
3. Investigation difficulties
4. Professional polygraph role
5. Professional process
6. Limits, consent, and ethics
7. FAQ
8. Contact invitation

Preferred order for educational_page:
1. Topic definition
2. Why the topic matters
3. Core concepts or methodology
4. Practical application
5. Misunderstandings and limitations
6. FAQ
7. Soft next step or related topics

Preferred order for authority_page:
1. Topic or standard definition
2. Background or research context
3. Professional relevance
4. Limitations and responsible interpretation
5. FAQ
6. Related topics

Preferred order for blog_post:
1. Direct answer
2. Practical context
3. Main explanation
4. Key considerations
5. Limitations
6. FAQ
7. Related links or soft next step

CONVERSION STRUCTURE

The content should naturally include:
- client pain points
- practical investigation scenarios
- confidentiality/trust language
- professional process explanation
- local market positioning
- strategic contact invitations
- reassurance without guarantees

CONTACT STYLE

Include natural invitation-style contact wording such as:
- contact us for confidential guidance
- discuss your situation with a professional examiner
- request more information
- evaluate whether the test is appropriate for your case

DO NOT:
- pressure the reader
- guarantee results
- promise certainty
- promise legal proof
- claim 100% accuracy
- use internal marketing terms such as CTA or call-to-action in visible text

LOCAL MARKET ADAPTATION

Adapt language and examples to:
- the local country
- the local business environment
- local terminology
- local client concerns

The content must feel locally relevant for {context["country"]} and {context["market"]}.
""".strip()

    terminology_rules = f"""

WORKSPACE TERMINOLOGY AND STYLE GUIDANCE

Use the following workspace-level terminology guidance as soft writing guidance.

IMPORTANT:
- This guidance should improve wording, not block draft generation.
- Prefer the recommended professional terms when possible.
- Avoid discouraged expressions when a better professional alternative is available.
- Do not mention this guidance in the final page.
- Examiner review and validation warnings remain responsible for final wording decisions.

{terminology_prompt}
""".strip()

    page_plan_rules = f"""

LOCKED PAGE PLAN ENFORCEMENT

Use the following locked page plan as the primary structural contract for this page.

IMPORTANT:
- The page plan overrides generic drafting personality rules.
- The page plan overrides older strategy sections when there is a conflict.
- The page plan controls required sections, order, FAQ count, internal links, and contact/trust expectations.
- Do not mention the page plan in the final page.
- Do not output section IDs visibly.
- Convert section IDs into natural H2 headings in the workspace language.
- If the page plan says locked=True, do not change the page structure.
- Required internal links: {required_internal_link_count}
- Required FAQ questions: {required_faq_count}
- Validation minimum word count: {minimum_word_count}
- Generation target word count: {generation_word_target}

{page_plan_prompt}
""".strip()


    blueprint_rules = f"""

PAGE BLUEPRINT STRUCTURE

Use the following page blueprint as the required semantic structure for this page.

The blueprint defines the preferred section order, purpose, and content sequencing.
Follow the sequence unless there is a strong reason not to.

CRITICAL SECTION ORDER ENFORCEMENT

The H2 sections MUST follow the active page blueprint.

IMPORTANT:
- The blueprint controls page structure.
- Do not mention the blueprint in the final page.
- Do not output section IDs.
- Use natural headings adapted to the page topic and language.
- Do not force service-page structure onto educational, authority, FAQ, city, pricing, blog, or pillar pages.
- Follow the drafting_instructions provided by the active blueprint.
- If the blueprint is educational_page, start with the topic definition and explanation, not client pain points.
- If the blueprint is authority_page, start with the authority, standard, research, or professional concept.
- If the blueprint is landing_page, start with the client problem and practical service need.
- If the blueprint is city_page, start with local service availability and local relevance.
- If the blueprint is pricing_page, start with clear pricing context.

{blueprint_prompt}
""".strip()

    opportunity_intelligence_rules = f"""

OPPORTUNITY INTELLIGENCE — TOPIC-SPECIFIC CONTENT DEPTH

Use the following opportunity intelligence after applying the locked page plan and blueprint.

IMPORTANT:
- The locked page plan controls structure and order.
- Opportunity intelligence controls topic specificity, business examples, investigation scenarios, FAQ focus, and issue/sector relevance.
- Use the issue, sector, content angles, and scenarios naturally in the first half of the page.
- Every major non-FAQ section should relate clearly to the specific issue and sector.
- Do not write generic polygraph content that could fit any page.
- Do not mention this intelligence package visibly.

{opportunity_intelligence_prompt}
""".strip()


    strict_html_rules = f"""

CRITICAL OUTPUT FORMAT — STRICT HTML ONLY

Return ONLY the final page body in clean HTML.

{get_language_output_rules(language_profile, context)}

LINK AND URL POLICY

Mandatory:
- Never invent URLs.
- Never invent domains.
- Never invent href links.
- Never use example domains or generic domains.
- Never use polygraphservices.com or any non-workspace domain.
- Only create an <a href=""> link when the exact URL is explicitly provided in the approved internal links, contact links, or workspace navigation data.
- If no approved URL is available, write the text without a hyperlink.
- Contact links, WhatsApp links, city links, reusable blocks, and strategic links are handled by Sofia after generation.

Workspace domain:
{workspace.get("domain", "")}

SPAIN FORMALITY POLICY

For Spanish Spain workspace content:
- Use formal usted style.
- Do not use tú, te, tu, tus, contigo, ayudarte, contáctanos, sospechas, necesitas, contacta.
- Prefer: usted, su, sus, puede contactar, podemos ayudarle, si sospecha, si necesita.
- Keep the tone professional, discreet and formal.

BRAND SAFETY

Do not invent:
- company names
- service brands
- office names
- examiner names
- organization names

If no company name is explicitly provided, use:
- our team
- our service
- the examiner
- the examination

CONTENT QUALITY ENFORCEMENT

Do not generate generic encyclopedia-style content.
When topic intelligence is available, every major non-FAQ section must include at least one specific client problem, investigation scenario, operational risk, or business example from that topic intelligence.
Do not write a page that could apply equally to any polygraph service.

Every section must be directly related to:
- the specific issue
- the target keyword
- the investigation scenario
- the client concern

Avoid generic explanations that could appear on any polygraph page.

The page must feel written specifically for the target topic.

TOPIC ADHERENCE

At least 70% of the page must focus on:
- the specific issue
- the investigation scenario
- the target keyword
- practical client situations

Generic explanations of the polygraph process must remain secondary.

A reader should immediately understand that the page is specifically about:
"{context['focus_keyphrase']}"

and not about polygraph services in general.

Do NOT return Markdown.
Do NOT use Markdown headings.
Do NOT use code fences.
Do NOT include explanatory comments.
Do NOT include metadata blocks such as:
### Title:
### Meta Title:
### Meta Description:
### Slug:
### Focus Keyphrase:
### H1:
### Body Content (HTML format):

Each required H2 section before the FAQ must include at least 2 substantial paragraphs.
Each paragraph should contain practical, topic-specific detail.
Do not write one short paragraph per section.
Do not count bullet lists as a substitute for paragraphs.
The full page must meet or exceed the locked page plan generation target word count.

The first sections must include realistic examples and situations from the topic intelligence package when available.

For corporate investigation pages, examples must focus on the suspected business problem, such as procurement irregularities, supplier favoritism, invoice fraud, fuel diversion, warehouse losses, inventory discrepancies, access-control problems, internal audits, employee misconduct, or weak internal controls, depending on the topic.

Always adapt the examples to the specific page topic, target audience, and blueprint type:
- For corporate investigation pages, use business and employer examples.
- For relationship or personal investigation pages, use relational, emotional, or trust-related examples.
- For pre-employment or screening pages, use integrity, trust, and hiring-risk examples.
- For training pages, use student, professional-development, and certification-readiness examples.

Do NOT place SEO fields inside the page body.
Sofia's Python workflow will save SEO title, focus keyphrase, slug, and meta description separately.

Do NOT use the words:
- CTA
- Call to Action
- Chamada para ação
- Chame a Ação

These are internal marketing terms and must never appear visibly on the final page.

Use natural visitor-facing contact headings appropriate to the workspace language.

Allowed contact phrase examples for this workspace:
{get_contact_phrase_examples(language_profile)}

The response must start directly with exactly one <h1> tag.

Required HTML structure:

<h1>...</h1>

Then create H2 sections according to the active page blueprint.

For landing_page only, use a service-oriented order:
- client problem or practical concern
- situations where the service may help
- professional polygraph role
- process
- confidentiality, consent, and limits
- FAQ
- contact

For educational_page, use an educational order:
- topic definition
- why the topic matters
- core concepts or methodology
- practical application
- misunderstandings and limitations
- FAQ
- soft next step or related topics

For authority_page, use an authority-building order:
- topic or standard definition
- background or research context
- professional relevance
- limitations and responsible interpretation
- FAQ
- related topics

For city_page, use a local service order:
- local service introduction
- local context
- common local client situations
- process
- trust and limits
- FAQ
- contact

City-page local accuracy rules:
- Do not imply a physical office, permanent presence, local branch, or resident examiner in the city unless explicitly configured.
- Do not say "nuestra ciudad", "nuestra presencia en la región", "oficina en la ciudad", "sin necesidad de viajar largas distancias", "estamos en [city]", or "nuestro equipo local" unless a confirmed local office exists.
- Prefer neutral service-coverage wording such as "servicio disponible para casos en [city]", "atención profesional para clientes de [city]", "orientación confidencial para personas, empresas y abogados de [city]", or "evaluaciones que pueden organizarse previa consulta".
- Avoid tourism or generic local filler such as "ciudad rica en historia y cultura", "ciudad dinámica", or unrelated descriptions of the city.
- Do not invent addresses, local offices, local examiners, travel arrangements, or guaranteed local appointment availability.
- Do not promise convenience based on distance, travel reduction, or local presence unless explicitly configured.
- Explain availability carefully: "previa consulta", "según disponibilidad", or "para clientes de [city]" rather than claiming permanent local presence.

City-page claim-safety rules:
- Do not call the polygraph a "herramienta poderosa".
- Do not promise "información veraz y precisa".
- Do not say the test provides "evidencia crucial".
- Do not say the polygraph can "identificar a los responsables" or "identificar rápidamente a los responsables".
- Prefer cautious wording: "puede aportar información complementaria", "puede ayudar a orientar una investigación", "permite valorar respuestas fisiológicas ante preguntas específicas", or "debe interpretarse junto con otros elementos del caso".
- Do not describe the result as proof, certainty, evidence of guilt, or a substitute for a broader investigation.

For pricing_page, use a pricing order:
- pricing context
- prices or price ranges if available
- what affects price
- what is included
- booking or quote guidance
- FAQ
- contact

For pillar_page, use a hub order:
- broad topic overview
- definition and scope
- main applications
- process overview
- limitations and ethics
- related services/internal links
- FAQ
- contact

{get_faq_heading_instruction(language_profile)}

The FAQ section must include the number of structured question-answer pairs required by the content strategy.
If no content strategy number is available, include at least 6 question-answer pairs.
For the current HTML renderer, use <h3>Question...</h3> followed by <p>Answer...</p>.
Do not write fewer than the required number of FAQ questions.

{get_polygraph_terminology_rules(language_profile)}

Internal links:
Use only relevant internal links from the provided internal links list if they fit naturally.
Never invent URLs.
Never use placeholder URLs such as example.com.
Never link to a URL that is not present in the provided internal links list.
If no suitable internal link is available, omit the link instead of inventing one.
If the locked page plan requires internal links, include at least {required_internal_link_count} relevant internal links only when enough relevant links are available.
Do not output plain-text link names without URLs.
Every item in an internal links section must be a real <a href="...">anchor</a> using a provided URL.
Do not force links that are not relevant.

Final reminder:
Your answer must be only clean HTML beginning with <h1>.
""".strip()

    prompt = (
        f"{prompt}\n\n"
        f"{knowledge_rules}\n\n"
        f"{strategy_rules}\n\n"
        f"{terminology_rules}\n\n"
        f"{page_plan_rules}\n\n"
        f"{opportunity_intelligence_rules}\n\n"
        f"{drafting_personality_rules}\n\n"
        f"{blueprint_rules}\n\n"
        f"{strict_html_rules}"
    )

    return prompt, context




def repair_faq_language_leakage(html: str, language_profile: dict, locale: str = "") -> str:
    """
    Workspace-profile-driven FAQ language leakage repair.
    Structural logic only. Language-specific replacements live in language_profile.json.
    """
    profile = ((language_profile or {}).get("content_repair") or {}).get("faq_language_leakage") or {}

    if not profile.get("enabled"):
        return html

    target_prefix = str(profile.get("target_locale_prefix") or "").lower().strip()
    if target_prefix and not str(locale or "").lower().startswith(target_prefix):
        return html

    replacements = profile.get("replacements") or {}
    repaired = str(html or "")

    for old, new in replacements.items():
        repaired = repaired.replace(str(old), str(new))

    if profile.get("ensure_question_marks"):
        def fix_h3(match):
            q = match.group(1).strip()
            if q and not q.startswith("¿") and target_prefix == "es":
                q = "¿" + q
            if q and not q.endswith("?"):
                q = q.rstrip(".") + "?"
            return f"<h3>{q}</h3>"

        repaired = re.sub(r"<h3>(.*?)</h3>", fix_h3, repaired, flags=re.I | re.S)

    return repaired





def count_faq_h3(html: str) -> int:
    return len(re.findall(r"<h3>.*?</h3>", str(html or ""), flags=re.I | re.S))


def contains_language_leakage(html: str, language_profile: dict, locale: str = "") -> bool:
    profile = ((language_profile or {}).get("content_repair") or {}).get("faq_language_leakage") or {}
    target_prefix = str(profile.get("target_locale_prefix") or "").lower().strip()

    if target_prefix and not str(locale or "").lower().startswith(target_prefix):
        return False

    leakage_terms = list((profile.get("replacements") or {}).keys())
    faq_html = ""
    match = re.search(r"<h2>\s*(Preguntas frecuentes|Perguntas frequentes|Questions fréquentes|Frequently Asked Questions)\s*</h2>(.*)", str(html or ""), flags=re.I | re.S)
    if match:
        faq_html = match.group(2)

    haystack = faq_html or str(html or "")
    return any(str(term) in haystack for term in leakage_terms)


def render_profile_faq_block(draft: dict, language_profile: dict, required_count: int) -> str:
    profile = ((language_profile or {}).get("content_repair") or {}).get("faq_rebuild") or {}
    if not profile.get("enabled"):
        return ""

    intelligence = get_opportunity_intelligence(draft)
    page_plan = draft.get("page_plan") or {}
    semantic_entities = page_plan.get("semantic_entities") or {}

    issue = (
        intelligence.get("issue")
        or semantic_entities.get("incident")
        or draft.get("issue")
        or "este caso"
    )
    sector = (
        intelligence.get("sector")
        or semantic_entities.get("industry")
        or draft.get("sector")
        or "la organización"
    )
    focus_keyphrase = (
        intelligence.get("recommended_focus_keyphrase")
        or draft.get("focus_keyphrase")
        or draft.get("target_keyword")
        or ""
    )
    topic = (
        intelligence.get("recommended_title")
        or draft.get("normalized_title")
        or draft.get("title")
        or focus_keyphrase
        or issue
    )

    values = {
        "issue": issue,
        "sector": sector,
        "country": intelligence.get("country_localized") or draft.get("country_localized") or "",
        "focus_keyphrase": focus_keyphrase,
        "topic": topic,
        "incident": semantic_entities.get("incident") or issue,
        "object": semantic_entities.get("object") or issue,
        "industry": semantic_entities.get("industry") or sector,
        "audience": semantic_entities.get("audience") or sector,
        "service": semantic_entities.get("service") or "",
        "investigation_type": semantic_entities.get("investigation_type") or "",
    }

    templates = profile.get("templates") or []
    minimum_items = max(int(profile.get("minimum_items") or 0), int(required_count or 0))

    lines = [f"<h2>{profile.get('heading') or 'FAQ'}</h2>"]

    for item in templates[:minimum_items]:
        q = str(item.get("question") or "").format(**values)
        a = str(item.get("answer") or "").format(**values)
        if q and a:
            lines.append(f"<h3>{q}</h3>")
            lines.append(f"<p>{a}</p>")

    return "\n".join(lines)


def replace_or_append_faq_block(html: str, faq_block: str) -> str:
    if not faq_block:
        return html

    pattern = r"<h2>\s*(Preguntas frecuentes|Perguntas frequentes|Questions fréquentes|Frequently Asked Questions)\s*</h2>.*?(?=<h2>|$)"
    if re.search(pattern, str(html or ""), flags=re.I | re.S):
        return re.sub(pattern, faq_block, str(html or ""), count=1, flags=re.I | re.S)

    return str(html or "").rstrip() + "\n\n" + faq_block


def repair_or_rebuild_faq_block(html: str, draft: dict, language_profile: dict, locale: str, required_count: int) -> str:
    repaired = repair_faq_language_leakage(html, language_profile=language_profile, locale=locale)

    if count_faq_h3(repaired) >= required_count and not contains_language_leakage(repaired, language_profile, locale):
        return repaired

    faq_block = render_profile_faq_block(draft, language_profile, required_count)
    if faq_block:
        return replace_or_append_faq_block(repaired, faq_block)

    return repaired







def apply_profile_quality_replacements(html: str, language_profile: dict) -> str:
    """
    Apply workspace-profile-driven text replacements.
    Structural logic only; language-specific replacements live in language_profile.json.

    Supports existing profile shapes:
    - content_quality_rules.replacements: find / replace
    - content_quality_rules.quality_replacements: find / replace
    - content_quality_replacements: from / to
    """
    profile = language_profile or {}
    rules = profile.get("content_quality_rules") or {}

    replacements = []
    replacements.extend(rules.get("replacements") or [])
    replacements.extend(rules.get("quality_replacements") or [])
    replacements.extend(profile.get("content_quality_replacements") or [])

    repaired = str(html or "")

    for item in replacements:
        if not isinstance(item, dict):
            continue

        find = (
            item.get("find")
            if item.get("find") is not None
            else item.get("from")
        )
        replace = (
            item.get("replace")
            if item.get("replace") is not None
            else item.get("to")
        )

        if find is None or replace is None:
            continue

        repaired = repaired.replace(str(find), str(replace))

    return repaired



def get_language_guard(language_profile: dict) -> dict:
    return ((language_profile or {}).get("language_guard") or {})


def detect_language_guard_failure(html: str, language_profile: dict, locale: str = "") -> dict:
    guard = get_language_guard(language_profile)
    if not guard.get("enabled"):
        return {"failed": False, "forbidden_hits": [], "hit_count": 0}

    target_prefix = str(guard.get("target_locale_prefix") or "").lower().strip()
    if target_prefix and not str(locale or "").lower().startswith(target_prefix):
        return {"failed": False, "forbidden_hits": [], "hit_count": 0}

    content = str(html or "").lower()
    forbidden = guard.get("forbidden_language_markers") or []
    hits = []

    for marker in forbidden:
        marker_text = str(marker or "").lower().strip()
        if marker_text and marker_text in content:
            hits.append(marker)

    max_hits = int(guard.get("max_forbidden_hits", 0) or 0)
    failed = len(hits) > max_hits

    return {
        "failed": failed,
        "forbidden_hits": hits,
        "hit_count": len(hits),
        "max_forbidden_hits": max_hits,
    }


def repair_content_language_with_ai(html: str, language_profile: dict, context: dict) -> str:
    guard = get_language_guard(language_profile)
    instruction = guard.get("repair_instruction") or "Rewrite the complete HTML content in the target language only."

    repair_prompt = f"""
{instruction}

Target language: {guard.get('target_language_name') or context.get('language') or context.get('locale')}

Rules:
- Return only clean HTML.
- Preserve headings and paragraph structure as much as possible.
- Preserve professional and ethical limitation wording.
- Do not add markdown fences.
- Do not add explanations.

HTML to rewrite:
{html}
""".strip()

    repaired = call_ollama(repair_prompt)
    repaired = clean_generated_content(repaired)
    return repaired or html


def enforce_profile_language_guard(html: str, language_profile: dict, context: dict) -> tuple[str, dict]:
    locale = context.get("locale", "")
    result = detect_language_guard_failure(html, language_profile, locale=locale)

    if not result.get("failed"):
        return html, result

    repaired = repair_content_language_with_ai(html, language_profile, context)
    second = detect_language_guard_failure(repaired, language_profile, locale=locale)
    second["repair_attempted"] = True
    second["initial_forbidden_hits"] = result.get("forbidden_hits", [])

    if second.get("failed"):
        # Keep repaired content if it improved, otherwise keep original.
        if second.get("hit_count", 999) < result.get("hit_count", 999):
            return repaired, second
        return html, second

    return repaired, second



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


def extract_markdown_field(content, field_name):
    pattern = rf"###\s*{re.escape(field_name)}\s*:\s*(.*?)(?=\n\s*###|\Z)"
    match = re.search(pattern, content, flags=re.IGNORECASE | re.DOTALL)

    if not match:
        return ""

    return match.group(1).strip()



def get_locked_h1(draft: dict, context: dict | None = None) -> str:
    context = context or {}
    page_plan = draft.get("page_plan") or {}
    intelligence = get_opportunity_intelligence(draft)

    return (
        page_plan.get("h1")
        or page_plan.get("page_h1")
        or intelligence.get("recommended_h1")
        or draft.get("page_h1")
        or draft.get("title")
        or draft.get("working_title")
        or context.get("title")
        or ""
    ).strip()


def enforce_locked_h1(html: str, locked_h1: str) -> tuple[str, dict]:
    html = str(html or "").strip()
    locked_h1 = str(locked_h1 or "").strip()

    result = {
        "enabled": bool(locked_h1),
        "locked_h1": locked_h1,
        "changed": False,
        "original_h1": "",
        "h1_count_before": 0,
    }

    if not locked_h1:
        return html, result

    h1_pattern = r"<h1\b[^>]*>(.*?)</h1>"
    matches = re.findall(h1_pattern, html, flags=re.I | re.S)
    result["h1_count_before"] = len(matches)

    if matches:
        result["original_h1"] = re.sub(r"<[^>]+>", " ", matches[0]).strip()

        def replace_first_h1(match):
            return f"<h1>{locked_h1}</h1>"

        html = re.sub(h1_pattern, replace_first_h1, html, count=1, flags=re.I | re.S)

        # Remove extra H1 tags by downgrading only H1 tags after the first one.
        seen_h1 = {"count": 0}

        def downgrade_extra_h1(match):
            seen_h1["count"] += 1
            if seen_h1["count"] == 1:
                return match.group(0)
            return f"<h2>{match.group(1).strip()}</h2>"

        html = re.sub(
            h1_pattern,
            downgrade_extra_h1,
            html,
            flags=re.I | re.S,
        )
    else:
        html = f"<h1>{locked_h1}</h1>\n\n{html}"

    result["changed"] = result["original_h1"] != locked_h1 or result["h1_count_before"] != 1
    return html, result



def clean_generated_content(content):
    content = str(content or "").strip()

    if content.startswith("```html"):
        content = content.replace("```html", "", 1).strip()

    if content.startswith("```"):
        content = content.replace("```", "", 1).strip()

    if content.endswith("```"):
        content = content[:-3].strip()

    # If Ollama returns a Markdown package, extract only the body section.
    markdown_package_markers = [
        "### Title:",
        "### Meta Title:",
        "### Meta Description:",
        "### Slug:",
        "### Focus Keyphrase:",
        "### H1:",
        "### Body Content"
    ]

    if any(marker.lower() in content.lower() for marker in markdown_package_markers):
        h1_text = extract_markdown_field(content, "H1") or extract_markdown_field(content, "Title")
        body = (
            extract_markdown_field(content, "Body Content (HTML format)")
            or extract_markdown_field(content, "Body Content")
            or content
        )

        content = body.strip()

        if h1_text and "<h1" not in content.lower():
            content = f"<h1>{h1_text}</h1>\n\n{content}"

    return content


def extract_meta_description(content, focus_keyphrase):
    text = re.sub(r"<[^>]+>", " ", content)
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) <= 155:
        return text

    description = text[:155].rsplit(" ", 1)[0]

    if focus_keyphrase and focus_keyphrase.lower() not in description.lower():
        description = f"{focus_keyphrase}: {description}"

    return description[:155]


def safe_image_filename(text):
    base = slugify(text or "image")
    base = base.strip("-") or "image"
    return f"{base}.jpg"


def build_image_filename_from_topic(topic, workspace):
    slug = slugify(topic or "image")

    country = (
        workspace.get("country")
        or workspace.get("market_code")
        or ""
    )

    if country:
        slug = f"{slug}-{slugify(country)}"

    return f"{slug}.jpg"


def detect_image_context(topic: str, draft: dict | None = None, context: dict | None = None) -> str:
    """
    Return a concise Spanish image context label from topic/draft text.

    This is used for natural WordPress image metadata. It avoids generic
    phrases such as "imagen relacionada con..." and avoids visible claims
    about polygraph certainty, proof, or lie detection.
    """
    draft = draft or {}
    context = context or {}

    haystack = normalize_text_for_matching(" ".join([
        str(topic or ""),
        str(context.get("title", "")),
        str(context.get("focus_keyphrase", "")),
        str(draft.get("summary", "")),
        str(draft.get("notes", "")),
        str(draft.get("target_keyword", "")),
        str(draft.get("focus_keyphrase", "")),
    ]))

    patterns = [
        (
            ["combustible", "fuel", "transporte", "flota", "gasolina", "diesel"],
            "investigaciones de fraude o desvío de combustible en empresas de transporte",
        ),
        (
            ["inventario", "almacen", "almacén", "stock", "mercancia", "mercancía", "warehouse"],
            "investigaciones de manipulación de inventario o pérdidas internas en empresas",
        ),
        (
            ["robo", "hurto", "theft", "sustraccion", "sustracción"],
            "investigaciones internas relacionadas con sospechas de robo o sustracción",
        ),
        (
            ["infidelidad", "pareja", "relacion", "relación", "conyugal"],
            "consultas confidenciales relacionadas con dudas de pareja o sospechas de infidelidad",
        ),
        (
            ["pre empleo", "pre-empleo", "seleccion", "selección", "contratacion", "contratación", "integridad"],
            "evaluaciones de integridad y procesos de selección de personal",
        ),
        (
            ["metodologia", "metodología", "tecnica", "técnica", "preguntas", "fiabilidad", "educativa"],
            "contenido educativo sobre metodología y práctica profesional del polígrafo",
        ),
        (
            ["precio", "precios", "tarifa", "coste", "costo", "presupuesto"],
            "información sobre precios, presupuestos y solicitud de servicios de polígrafo",
        ),
        (
            ["ciudad", "madrid", "barcelona", "zaragoza", "cordoba", "córdoba", "granada", "toledo", "alicante", "cadiz", "cádiz", "tenerife", "palmas"],
            "servicios profesionales de polígrafo disponibles para clientes en España",
        ),
    ]

    for terms, label in patterns:
        if any(term in haystack for term in terms):
            return label

    page_type = str((draft.get("page_plan") or {}).get("page_type") or context.get("content_type") or "").strip()

    if page_type == "educational_page":
        return "contenido educativo sobre el uso profesional del polígrafo"
    if page_type == "authority_page":
        return "contenido profesional sobre estándares, metodología o práctica poligráfica"
    if page_type == "blog_post":
        return "contenido informativo sobre evaluación poligráfica y toma de decisiones"
    if page_type == "city_page":
        return "servicios profesionales de polígrafo disponibles para clientes en España"

    return "consultas profesionales y evaluación poligráfica en España"


def build_image_alt_text(topic, draft: dict | None = None, context: dict | None = None, workspace: dict | None = None):
    country = ((workspace or {}).get("country") or "").strip()
    label = detect_image_context(topic, draft=draft, context=context)

    text = f"Imagen profesional utilizada como apoyo visual en una página sobre {label}"
    if country and country.lower() not in text.lower():
        text = f"{text} en {country}"

    return text[:160]


def build_image_title(topic, draft: dict | None = None, context: dict | None = None, workspace: dict | None = None):
    country = ((workspace or {}).get("country") or "").strip()
    label = detect_image_context(topic, draft=draft, context=context)
    text = f"Imagen profesional sobre {label}"
    if country and country.lower() not in text.lower():
        text = f"{text} en {country}"
    return text[:120]


def build_image_description(topic, draft: dict | None = None, context: dict | None = None, workspace: dict | None = None):
    country = ((workspace or {}).get("country") or "").strip()
    label = detect_image_context(topic, draft=draft, context=context)
    text = f"Imagen profesional utilizada como apoyo visual en una página sobre {label}"
    if country and country.lower() not in text.lower():
        text = f"{text} en {country}"
    return text[:220]


def build_image_caption(topic):
    # Sofia currently does not use visible image captions in WordPress output.
    return ""


def build_image_prompt(topic, workspace, image_guidelines, page_presentation, image_type="featured_image"):
    country = workspace.get("country", "") or workspace.get("market_code", "")
    style = (
        page_presentation.get("images", {}).get("preferred_style")
        or image_guidelines.get("featured_image", {}).get("preferred_style")
        or "professional_realistic"
    )

    preferred_elements = image_guidelines.get("preferred_elements", []) or []
    avoid_elements = image_guidelines.get("avoid_elements", []) or []
    polygraph_rules = image_guidelines.get("polygraph_rules", []) or []

    prompt_parts = [
        f"A {style.replace('_', ' ')} image for a professional polygraph service page.",
        f"Topic: {topic}.",
    ]

    if country:
        prompt_parts.append(f"Local market context: {country}.")

    if preferred_elements:
        prompt_parts.append(
            "Preferred visual elements: " + ", ".join(preferred_elements[:8]) + "."
        )

    if polygraph_rules:
        prompt_parts.append(
            "Polygraph-specific guidance: " + " ".join(polygraph_rules[:3])
        )

    if avoid_elements:
        prompt_parts.append(
            "Avoid: " + ", ".join(avoid_elements[:10]) + "."
        )

    prompt_parts.append(
        "The image should look professional, calm, ethical, and suitable for a business website."
    )

    return " ".join(prompt_parts)


def find_image_topic_mapping(text, image_guidelines):
    topic_mapping = image_guidelines.get("topic_mapping", {}) or {}
    haystack = normalize_text_for_matching(text or "")

    best_key = ""
    best_mapping = {}
    best_score = 0

    for key, mapping in topic_mapping.items():
        score = 0
        for term in mapping.get("match_terms", []) or []:
            if normalize_text_for_matching(term) in haystack:
                score += 1

        if score > best_score:
            best_score = score
            best_key = key
            best_mapping = mapping

    return best_key, best_mapping


def build_image_recommendations(draft, context, workspace, page_presentation, image_guidelines):
    image_settings = page_presentation.get("images", {}) or {}

    if image_settings.get("enabled") is False:
        return {}

    if image_settings.get("generate_metadata") is False:
        return {}

    title = (
        context.get("title")
        or draft.get("title")
        or draft.get("working_title")
        or "polygraph service"
    )

    focus = (
        context.get("focus_keyphrase")
        or draft.get("focus_keyphrase")
        or draft.get("target_keyword")
        or title
    )

    topic = title
    filename_base = slugify(focus or title)

    mapping_key, topic_mapping = find_image_topic_mapping(
        f"{title} {focus} {draft.get('summary', '')} {draft.get('notes', '')}",
        image_guidelines
    )

    recommendations = {
        "generated_at": now_iso(),
        "source": "generate_website_draft.py",
        "topic_mapping_used": mapping_key,
        "featured_image": None,
        "in_article_images": []
    }

    if image_settings.get("featured_image", True):
        featured_topic = (
            topic_mapping.get("featured_image_topic")
            or topic
        )
        recommendations["featured_image"] = {
            "topic": featured_topic,
            "filename": (
                f"{slugify(topic_mapping.get('featured_filename_local'))}.jpg"
                if topic_mapping.get("featured_filename_local")
                else build_image_filename_from_topic(
                    featured_topic,
                    workspace
                )
            ),
            "alt_text": (
                topic_mapping.get("featured_alt_text_local")
                or build_image_alt_text(
                    featured_topic,
                    draft=draft,
                    context=context,
                    workspace=workspace
                )
            ),
            "title": build_image_title(
                featured_topic,
                draft=draft,
                context=context,
                workspace=workspace
            ),
            "description": build_image_description(
                featured_topic,
                draft=draft,
                context=context,
                workspace=workspace
            ),
            "caption": "",
            "placement": image_settings.get("placements", {}).get("featured_image", "page_featured_image"),
            "prompt": build_image_prompt(
                featured_topic,
                workspace,
                image_guidelines,
                page_presentation,
                image_type="featured_image"
            )
        }

    in_article_count = int(image_settings.get("in_article_images", 0) or 0)
    placements = image_settings.get("placements", {}).get("in_article_images", []) or []

    for index in range(in_article_count):
        placement = placements[index] if index < len(placements) else "in_article"
        mapped_topics = topic_mapping.get("in_article_topics", []) or []
        image_topic = (
            mapped_topics[index]
            if index < len(mapped_topics)
            else f"{title} — supporting visual {index + 1}"
        )

        local_topics = topic_mapping.get("in_article_topics_local", []) or []
        local_item = local_topics[index] if index < len(local_topics) else {}

        recommendations["in_article_images"].append({
            "topic": image_topic,
            "filename": (
                f"{slugify(local_item.get('filename'))}.jpg"
                if local_item.get("filename")
                else build_image_filename_from_topic(
                    image_topic,
                    workspace
                )
            ),
            "alt_text": (
                local_item.get("alt_text")
                or build_image_alt_text(
                    image_topic,
                    draft=draft,
                    context=context,
                    workspace=workspace
                )
            ),
            "title": build_image_title(
                image_topic,
                draft=draft,
                context=context,
                workspace=workspace
            ),
            "description": build_image_description(
                image_topic,
                draft=draft,
                context=context,
                workspace=workspace
            ),
            "caption": "",
            "placement": placement,
            "prompt": build_image_prompt(
                image_topic,
                workspace,
                image_guidelines,
                page_presentation,
                image_type="in_article_image"
            )
        })

    return recommendations


def main():
    print("=== Sofia: Generate Website Draft ===\n")

    if len(sys.argv) != 3:
        print("Usage:")
        print("python app/generate_website_draft.py WORKSPACE_ID DRAFT_ID")
        print("Example:")
        print("python app/generate_website_draft.py local.ao DRAFT-0001")
        return

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]

    for required_file in [WORKSPACES_FILE, PROMPT_FILE]:
        if not required_file.exists():
            print(f"ERROR: Required file not found: {required_file}")
            sys.exit(1)

    try:
        workspaces_data = load_json(WORKSPACES_FILE)
        prompt_template = load_text(PROMPT_FILE)
    except Exception as e:
        print(f"ERROR: Could not read required files: {e}")
        sys.exit(1)

    workspace = find_workspace(workspaces_data, workspace_id)

    if not workspace:
        print(f"ERROR: Workspace not found in workspaces.json: {workspace_id}")
        sys.exit(1)

    draft_registry_file = get_workspace_draft_registry_path(workspace_id)

    if draft_registry_file.exists():
        draft_registry_data = load_json(draft_registry_file)
    else:
        draft_registry_data = empty_draft_registry(workspace_id)

    draft = find_draft(draft_registry_data, draft_id)

    if not draft:
        print(f"ERROR: Draft not found in workspace draft registry: {draft_id}")
        print(f"Registry: {draft_registry_file}")
        sys.exit(1)

    workspace_folder = BASE_DIR / workspace.get("folder_path", "")
    internal_links = load_internal_links(workspace_folder)
    page_presentation = load_page_presentation(workspace_folder)
    image_guidelines = load_image_guidelines(workspace_folder)

    language_profile_path = workspace_folder / "language_profile.json"
    language_profile = load_json(language_profile_path) if language_profile_path.exists() else {}

    internal_links_text = format_internal_links(internal_links)

    topic = (
        draft.get("working_title")
        or draft.get("title")
        or draft.get("target_keyword")
        or draft.get("focus_keyphrase")
        or ""
    )

    strategy = extract_draft_strategy(draft)
    content_focus = strategy.get("content_focus", {}) or {}
    topic_intelligence = content_focus.get("topic_intelligence", {}) or {}
    topic_tags = topic_intelligence.get("topic_tags", []) or []

    knowledge_package = build_knowledge_package(
        workspace_id=workspace_id,
        topic=topic,
        tags_hint=list(dict.fromkeys([
            "procedure",
            "ethics",
            "limitations",
            "faq",
            "questions",
            "service",
        ] + topic_tags)),
        max_blocks=6,
    )

    knowledge_prompt = format_package_for_prompt(knowledge_package)

    strategy_prompt = format_strategy_for_prompt(strategy)

    blueprint_package = build_blueprint_package_for_draft(draft)
    blueprint_prompt = blueprint_package.get("prompt_text", "")

    page_plan = draft.get("page_plan") or {}
    page_plan_prompt = format_page_plan_for_prompt(page_plan)
    terminology_prompt = format_terminology_guidance_for_prompt(language_profile)
    opportunity_intelligence_prompt = format_opportunity_intelligence_for_prompt(draft)

    # ----------------------------------------------------------
    # Sofia Core Intelligence
    # Phase 4.5
    #
    # Build deterministic page intelligence before prompt generation.
    # The current prompt still uses the legacy fill_prompt() path.
    # Future prompt_builder.py will consume content_architecture directly.
    # ----------------------------------------------------------

    context = build_draft_context(
        draft,
        workspace,
    )

    navigation_plan = (
        page_plan.get("navigation_plan")
        or page_plan.get("internal_navigation_plan")
        or {}
    )

    generation_package = build_generation_package(
        draft=draft,
        workspace=workspace,
        context=context,
        page_plan=page_plan,
        blueprint_package=blueprint_package,
        strategy=strategy,
        knowledge_package=knowledge_package,
        language_profile=language_profile,
        page_presentation=page_presentation,
        image_plan=draft.get("image_plan") or {},
        opportunity_intelligence=get_opportunity_intelligence(draft),
        navigation_plan=navigation_plan,
    )

    content_architecture = build_content_architecture(
        generation_package
    )

    # Phase 7.3A — Preserve semantic entities for the Writer layer.
    # page_plan_builder extracts concrete entities such as incident, object,
    # industry, audience and country. The Writer must receive them so it
    # does not reduce specific opportunities into generic service pages.
    semantic_entities = (page_plan or {}).get("semantic_entities") or {}
    if semantic_entities:
        content_architecture["semantic_entities"] = semantic_entities

    section_contracts = build_section_contracts(
        content_architecture
    )

    if semantic_entities:
        section_contracts["semantic_entities"] = semantic_entities

    draft["generation_package"] = generation_package
    draft["content_architecture"] = content_architecture
    draft["section_contracts"] = section_contracts

    print("")
    print("=== Sofia Core Intelligence ===")
    print("Generation Package:", summarize_generation_package(generation_package))
    print("Content Architecture:", summarize_architecture(content_architecture))
    print("Section Contracts:", summarize_section_contracts(section_contracts))
    print("")

    prompt, _ = fill_prompt(
        template=prompt_template,
        draft=draft,
        workspace=workspace,
        internal_links_text=internal_links_text,
        knowledge_prompt=knowledge_prompt,
        blueprint_prompt=blueprint_prompt,
        strategy_prompt=strategy_prompt,
        page_plan_prompt=page_plan_prompt,
        terminology_prompt=terminology_prompt,
        opportunity_intelligence_prompt=opportunity_intelligence_prompt,
        language_profile=language_profile,
    )

    # ----------------------------------------------------------
    # Sofia Writer Agent
    # Phase 5.1
    #
    # Safe first integration:
    # keep the legacy full-page prompt, but append section-centric
    # content architecture from Sofia Core Intelligence.
    # ----------------------------------------------------------

    prompt = build_full_page_writer_prompt(
        base_prompt=prompt,
        content_architecture=content_architecture,
        section_contracts=section_contracts,
    )

    draft["writer_agent"] = summarize_writer_input(
        content_architecture,
        section_contracts=section_contracts,
    )

    print("Writer Agent:", draft["writer_agent"])
    print("")

    print(f"Processing draft: {draft_id}")
    print(f"Workspace: {workspace_id}")
    print(f"Title: {context['title']}")
    print(f"Focus keyphrase: {context['focus_keyphrase']}")
    print(f"Locale: {context['locale']}")
    print(
        "Knowledge blocks used:",
        [
            block.get("block_id") or block.get("id")
            for block in knowledge_package.get("selected_blocks", [])
        ],
    )
    print(f"Page blueprint used: {blueprint_package.get('blueprint_id')}")
    print(f"Page plan used: {page_plan.get('blueprint_id', '')} | locked={page_plan.get('locked', False)}")
    print(f"Content strategy version: {strategy.get('strategy_version', 'none')}")
    print("")

    try:
        generated_content = call_ollama(prompt)
    except Exception as e:
        print(f"ERROR: Ollama generation failed: {e}")
        sys.exit(1)

    if not generated_content:
        print("ERROR: Ollama returned empty content.")
        sys.exit(1)

    generated_content = clean_generated_content(generated_content)

    locked_h1 = get_locked_h1(draft, context)
    generated_content, locked_h1_result = enforce_locked_h1(
        generated_content,
        locked_h1,
    )
    draft["locked_h1_enforcement"] = locked_h1_result

    generated_content, language_guard_result = enforce_profile_language_guard(
        generated_content,
        language_profile=language_profile,
        context=context,
    )
    generated_content = apply_profile_quality_replacements(
        generated_content,
        language_profile=language_profile,
    )
    draft["language_guard_result"] = language_guard_result

    generated_content = repair_or_rebuild_faq_block(
        generated_content,
        draft=draft,
        language_profile=language_profile,
        locale=context.get("locale", ""),
        required_count=get_page_plan_faq_count(draft.get("page_plan") or {}, fallback=8),
    )

    required_internal_link_count = get_page_plan_required_link_count(
        draft.get("page_plan") or {},
        fallback=1,
    )

    if isinstance(page_presentation, dict):
        page_presentation = dict(page_presentation)
        internal_link_settings = dict(page_presentation.get("internal_links", {}) or {})
        internal_link_settings["target_links"] = max(
            int(internal_link_settings.get("target_links", 0) or 0),
            required_internal_link_count,
        )
        internal_link_settings["maximum_links"] = max(
            int(internal_link_settings.get("maximum_links", 0) or 0),
            required_internal_link_count,
        )
        page_presentation["internal_links"] = internal_link_settings

    generated_content = ensure_internal_links_section(
        generated_content,
        internal_links,
        topic_text=f"{context['title']} {context['focus_keyphrase']} {topic}",
        language_profile=language_profile,
        page_presentation=page_presentation
    )

    # ----------------------------------------------------------
    # Sofia Editorial Pipeline
    # Phase 7.1
    #
    # Safe no-op integration:
    # - returns HTML unchanged
    # - records metadata only
    # - must never block WordPress draft generation
    # ----------------------------------------------------------

    generated_content, editorial_pipeline_result = process_editorial_pipeline(
        html=generated_content,
        draft=draft,
        editorial_package=draft.get("editorial_package") or {},
        settings={
            "enabled": False,
            "critic_enabled": False,
            "repair_enabled": False,
        },
    )

    draft["editorial_pipeline"] = editorial_pipeline_result

    # Final workspace-profile quality pass.
    # Earlier repairs, FAQ rebuilds, internal links, or editorial processing may
    # reintroduce wording that the workspace profile wants to replace.
    generated_content = apply_profile_quality_replacements(
        generated_content,
        language_profile=language_profile,
    )

    generated_word_count = word_count(generated_content)

    # Safety: make sure generation_word_target exists in main() scope.
    page_plan_for_length = draft.get("page_plan") or {}
    minimum_word_count_for_length = get_page_plan_minimum_word_count(
        page_plan_for_length,
        fallback=VALIDATION_MINIMUM_WORD_COUNT,
    )
    generation_word_target = max(
        minimum_word_count_for_length + EXPANSION_MARGIN,
        GENERATION_TARGET_WORD_COUNT,
    )

    print(f"Generated content word count: {generated_word_count}")

    seo_brief = draft.get("seo_brief", {}) or {}
    draft_input = draft.get("draft_input", {}) or {}

    seo_input = draft_input.get("seo", {}) or {}

    draft_title = (
        seo_input.get("page_title")
        or draft_input.get("page_title")
        or draft.get("title")
        or context.get("title")
        or ""
    )

    # New Image Asset Intelligence Layer.
    # The old build_image_recommendations() helper is kept above for backward compatibility,
    # but Phase 1 now stores draft-level image_plan metadata.
    image_recommendations = {}

    if generated_word_count < generation_word_target:
        print(
            f"Generated content below generation target "
            f"({generated_word_count} words, target {generation_word_target}). "
            "No deterministic expansion was added. "
            "Draft saved as generated and may require AI expansion later."
        )

        draft_title = draft.get("title") or context["title"]

    # --------------------------------------------
    # SEO source priority
    # --------------------------------------------
    # draft_input["seo"] is the normalized strategy output and should win.
    # seo_brief is kept only as a fallback for older opportunities.
    raw_focus_keyphrase = (
        seo_input.get("focus_keyphrase")
        or draft_input.get("focus_keyphrase")
        or context["focus_keyphrase"]
        or draft.get("target_keyword")
        or draft.get("focus_keyphrase")
        or draft_title
    )

    raw_slug = (
        seo_input.get("slug")
        or draft_input.get("slug")
        or context["suggested_slug"]
        or draft.get("suggested_slug")
        or draft.get("slug")
        or draft_title
    )

    raw_meta_description = (
        seo_input.get("meta_description")
        or draft_input.get("meta_description")
        or draft.get("meta_description")
        or extract_meta_description(generated_content, raw_focus_keyphrase)
    )

    raw_seo_title = (
        seo_input.get("seo_title")
        or draft_input.get("seo_title")
        or draft.get("seo_title")
        or draft_title
    )

    seo_fields = normalize_seo_fields(
        title=draft_title,
        focus_keyphrase=raw_focus_keyphrase,
        slug=raw_slug,
        meta_description=raw_meta_description,
        seo_title=raw_seo_title,
        fallback_topic=draft.get("target_keyword") or draft_title,
        language=context["language"]
    )

    draft["title"] = draft_title
    draft["slug"] = seo_fields["slug"]
    draft["focus_keyphrase"] = seo_fields["focus_keyphrase"]
    draft["seo_title"] = seo_fields["seo_title"]
    draft["meta_description"] = seo_fields["meta_description"]

    language_aliases = {
        "spanish": "es",
        "español": "es",
        "espanol": "es",
        "castellano": "es",
        "portuguese": "pt",
        "português": "pt",
        "portugues": "pt",
        "french": "fr",
        "français": "fr",
        "francais": "fr",
        "english": "en"
    }

    image_language = str(context.get("locale") or context.get("language") or "es").lower().strip()
    image_language = language_aliases.get(image_language, image_language)
    image_language = image_language.split("-")[0] if image_language else "es"

    # Apply opportunity intelligence to SEO fields before image planning and saving.
    seo_fields = apply_opportunity_intelligence_to_seo_fields(seo_fields, draft)

    image_page_type = (
        (draft.get("page_plan") or {}).get("page_type")
        or draft_input.get("page_type")
        or draft.get("page_type")
        or draft.get("content_type")
        or context.get("content_type")
        or "service_page"
    )

    # Use opportunity intelligence for image planning.
    # This keeps image prompts/filenames/metadata focused on the real issue
    # instead of generic raw request fragments.
    image_topic = build_intelligence_topic(
        draft,
        fallback=(
            seo_fields.get("focus_keyphrase")
            or draft_title
            or topic
        )
    )

    image_plan = build_image_plan_for_draft(
        workspace_id=workspace_id,
        page_type=image_page_type,
        topic=image_topic,
        language=image_language,
        country=context.get("country") or workspace.get("country") or "",
        page_slug=seo_fields.get("slug") or raw_slug
    )

    # Attach locked page plan so the image expander can use blueprint-driven
    # visual roles instead of hardcoded in-article image slots.
    image_plan["page_plan"] = draft.get("page_plan") or {}

    image_plan = expand_image_plan_with_in_article_images(
        image_plan=image_plan,
        workspace_id=workspace_id,
        page_type=image_page_type,
        topic=image_topic,
        language=image_language,
        country=context.get("country") or workspace.get("country") or "",
        page_slug=seo_fields.get("slug") or raw_slug,
        minimum_images=2,
        page_plan=draft.get("page_plan") or {},
    )

    draft["html_content"] = generated_content
    draft["image_plan"] = image_plan

    # Temporary backward compatibility for older scripts that still read image_recommendations.
    draft["image_recommendations"] = image_plan

    draft["generated_content"] = {
        "generated_at": now_iso(),
        "model": OLLAMA_MODEL,
        "content_format": "html",
        "knowledge_base_used": True,
        "knowledge_topic": topic,
        "knowledge_blocks_used": [
            block.get("block_id") or block.get("id")
            for block in knowledge_package.get("selected_blocks", [])
        ],
        "content_strategy_used": bool(strategy),
        "content_strategy_version": strategy.get("strategy_version", ""),
        "page_blueprint_used": blueprint_package.get("blueprint_id", ""),
        "page_plan_used": bool(draft.get("page_plan")),
        "page_plan_version": (draft.get("page_plan") or {}).get("version", ""),
        "page_plan_locked": (draft.get("page_plan") or {}).get("locked", False),
        "page_plan_blueprint_id": (draft.get("page_plan") or {}).get("blueprint_id", ""),
        "word_count": generated_word_count,
        "needs_ai_expansion": generated_word_count < generation_word_target,
        "image_plan": image_plan,
        "image_recommendations": image_plan,
        "content": generated_content
    }

    draft["draft_status"] = "content_generated"
    draft["html_generated_at"] = now_iso()
    draft["updated_at"] = now_iso()

    draft_registry_data["scope"] = "workspace"
    draft_registry_data["workspace_id"] = workspace_id
    save_json(draft_registry_file, draft_registry_data)

    print("Website draft generated successfully.")
    print(f"Draft ID: {draft_id}")
    print("Saved fields: html_content, generated_content.content, slug, meta_description")
    print("Knowledge base used: yes")
    print(
        f"Needs AI expansion: "
        f"{generated_word_count < generation_word_target}\n"
    )
    print("Generated content preview:")
    print(generated_content[:1200])


if __name__ == "__main__":
    main()