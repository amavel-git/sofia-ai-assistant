import json
import os
import re
import urllib.request
import sys
from pathlib import Path

from workspace_paths import (
    find_draft_any_workspace,
    get_workspace_draft_registry_path,
)

from content_knowledge import (
    build_knowledge_package,
    format_package_for_prompt,
)


SOFIA_ROOT = Path(__file__).resolve().parents[1]
# Deprecated: draft registries are now workspace-level.
GLOBAL_DRAFT_REGISTRY_FILE = SOFIA_ROOT / "sites" / "draft_registry.json"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("SOFIA_MODEL", "qwen2.5:14b")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_draft_registry_for_draft(draft_id):
    workspace_id, draft = find_draft_any_workspace(draft_id)

    if not workspace_id or not draft:
        raise RuntimeError(f"Draft not found in any workspace registry: {draft_id}")

    registry_path = get_workspace_draft_registry_path(workspace_id)
    registry_data = load_json(registry_path)

    return workspace_id, registry_path, registry_data, draft


def load_draft_registry_for_workspace_draft(workspace_id, draft_id):
    registry_path = get_workspace_draft_registry_path(workspace_id)
    registry_data = load_json(registry_path)

    for draft in registry_data.get("drafts", []):
        if draft.get("draft_id") == draft_id:
            return workspace_id, registry_path, registry_data, draft

    raise RuntimeError(f"Draft not found in workspace registry: {workspace_id} {draft_id}")


def call_ollama(prompt):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False
    }

    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(req, timeout=600) as response:
        result = json.loads(response.read().decode("utf-8"))

    return result.get("response", "").strip()


def find_draft(drafts, draft_id):
    for d in drafts:
        if d.get("draft_id") == draft_id:
            return d
    return None


def extract_minimum_word_count(issues):
    for issue in issues:
        match = re.search(r"Minimum required:\s*(\d+)", issue, re.IGNORECASE)
        if match:
            return int(match.group(1))

    return 800


def has_short_content_issue(issues):
    for issue in issues:
        if "content too short" in issue.lower():
            return True

    return False


def load_language_profile_for_draft(draft):
    workspace_path = draft.get("workspace_path", "")
    if not workspace_path:
        return {}

    profile_path = SOFIA_ROOT / workspace_path / "language_profile.json"

    if not profile_path.exists():
        return {}

    try:
        return load_json(profile_path)
    except Exception:
        return {}


def get_workspace_language_name(draft, language_profile):
    repair_guidance = language_profile.get("repair_guidance", {}) or {}

    return (
        repair_guidance.get("language_name")
        or language_profile.get("language_name")
        or draft.get("language")
        or draft.get("locale")
        or "the workspace language"
    )


def get_configured_forbidden_terms(language_profile):
    terms = language_profile.get("forbidden_terms", []) or []
    return [str(term).strip().lower() for term in terms if str(term).strip()]


def has_configured_language_contamination(html, language_profile):
    visible = re.sub(r"<[^>]+>", " ", str(html or "")).lower()

    for term in get_configured_forbidden_terms(language_profile):
        if term and term in visible:
            return term

    return ""


def deterministic_expand_from_profile(content, draft, language_profile, minimum_word_count):
    repair_guidance = language_profile.get("repair_guidance", {}) or {}

    page_plan = draft.get("page_plan") or {}
    page_type = (
        page_plan.get("page_type")
        or page_plan.get("blueprint_id")
        or draft.get("page_type")
        or draft.get("blueprint_id")
        or ""
    )

    by_page_type = repair_guidance.get("fallback_expansion_by_page_type", {}) or {}
    paragraphs = (
        by_page_type.get(page_type)
        or repair_guidance.get("fallback_expansion_paragraphs", [])
        or []
    )

    expanded = str(content or "").strip()

    for paragraph in paragraphs:
        if word_count(expanded) >= minimum_word_count:
            break

        paragraph = str(paragraph or "").strip()
        if paragraph and paragraph not in expanded:
            expanded += "\n\n" + paragraph

    return expanded



def build_repair_prompt(content, issues, knowledge_prompt="", draft=None, language_profile=None):
    draft = draft or {}
    language_profile = language_profile or {}
    workspace_language = get_workspace_language_name(draft, language_profile)
    minimum_word_count = extract_minimum_word_count(issues)
    target_word_count = max(minimum_word_count + 500, 1300)
    short_content = has_short_content_issue(issues)

    expansion_rules = ""

    if short_content:
        expansion_rules = f"""
SPECIAL KNOWLEDGE-AWARE EXPANSION REQUIREMENT:
- The content is too short.
- Expand the existing content to at least {target_word_count} words so it remains above the minimum after cleaning.
- Use the controlled knowledge package below as professional reference material.
- Do NOT copy the knowledge blocks verbatim.
- Do NOT mirror sentence structure from the knowledge blocks.
- Paraphrase, synthesize, and adapt the ideas naturally.
- Add useful, relevant, professional detail.
- Do NOT add filler text.
- Do NOT repeat the same paragraphs.
- Prefer expanding existing sections with practical explanation, limitations, process, examiner guidance, ethical safeguards, FAQ detail, and local service considerations.
- Do not add new <h2> sections for short-content repair unless the article has fewer than 5 <h2> sections.
- Prefer adding one useful paragraph to existing sections.
- Preserve all existing headings and section order.
- Preserve all existing <a href=""> links exactly.
- Preserve the original topic and search intent.
- Keep the content in the same language as the original content.
- Never remove an existing FAQ section.
- Never reduce the number of FAQ questions already present.
- Preserve every existing FAQ <h3> question.
- If fewer than 6 FAQ questions exist, add additional questions.
"""

    return f"""
You are Sofia, an SEO content correction assistant.

Your task:
Fix the HTML content below based ONLY on the listed issues.

STRICT RULES:
- Output ONLY clean HTML.
- Do NOT include explanations.
- Do NOT include markdown fences.
- Workspace language: {workspace_language}.
- Keep every sentence in the workspace language.
- Do not introduce words or phrases from any other language.
- If a sentence appears in another language, rewrite it into the workspace language.
- Keep the same topic and search intent.
- Do NOT remove important sections.
- Do NOT change the meaning of the content unless required to fix a listed issue.
- Keep SEO structure intact.
- Output ONLY valid HTML body content.
- Use exactly ONE <h1>.
- Use only standard HTML tags: <h1>, <h2>, <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, <a>.
- Do not use <br>, </br>, custom tags, markdown, or full <html>/<body> wrappers.
- Replace every heading that is not in the target website language.
- FAQ section is mandatory.
- FAQ section heading must use an <h2> tag.
- FAQ must contain at least 4 questions.
- Each FAQ question must be written as a separate <h3> question.
- Each FAQ answer must be written as one separate <p> paragraph.
- Remove or rewrite any statement about legal admissibility, legal acceptance, certification, guaranteed accuracy, or absolute certainty.
- Do not mention legally accepted, 100%, certified, guaranteed, infallible, or equivalent claims in any language.
- Do not introduce new legal, price, timing, phone, email, address, or office claims.
- The entire output must be in the workspace language only.
- Do not include Chinese, English, Spanish, French, Arabic, Russian, or any other language unless the workspace language requires it.
- For Portuguese pt-PT/Angola output, do not use: você, equipe, estresse, registros, coletados.
- Prefer: neutral professional wording, equipa, stress/tensão, registos, recolhidos.
- For Portuguese output using pt-PT, avoid Brazilian terms such as "equipe", "você", "estresse", "gerenciamento", "registros", "coletados" and prefer "equipa", neutral wording, "stress" or "tensão", "gestão", "registos", "recolhidos".
- If any sentence appears in the wrong language, rewrite it into the workspace language.
- Do not include meta commentary about the text, instructions, guidelines, prompts, knowledge blocks, validation, SEO, GEO, or Sofia.
- Do not write phrases such as "this text follows the guidelines", "este texto segue as diretrizes", "conteúdo aprovado", "blocos de conhecimento", or similar.
- Do not invent company names, website names, office names, service brands, examiner names, or organization names.
- If no official company name is provided, use neutral wording such as "our team", "our service", "our examiners", or "the examiner".

FAQ PRESERVATION RULES:
- Never remove an existing FAQ section.
- Never reduce the number of FAQ questions already present.
- Preserve existing FAQ questions.
- If fewer than 6 FAQ questions exist, add new questions until there are at least 6.
- Each FAQ question must use <h3>.
- Each FAQ answer must use one separate <p>.
- If the listed issues are only about a missing FAQ section or too few FAQ questions, preserve the existing page content.
- Do not rewrite, shorten, or replace the main article.
- Only add or correct the FAQ section.
- The FAQ heading must be exactly:
  - Portuguese: <h2>Perguntas frequentes</h2>
  - Spanish: <h2>Preguntas frecuentes</h2>
  - French: <h2>Questions fréquentes</h2>
  - English: <h2>Frequently Asked Questions</h2>
- Add at least 6 FAQ questions directly related to the page topic.
- Use <h3>Question</h3> followed by <p>Answer</p>.

{expansion_rules}

CONTROLLED KNOWLEDGE CONTEXT:
{knowledge_prompt}

ISSUES TO FIX:
{json.dumps(issues, ensure_ascii=False, indent=2)}

CONTENT TO FIX:
{content}
""".strip()

def strip_tags_for_count(html):
    text = re.sub(r"<[^>]+>", " ", str(html or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def word_count(html):
    text = strip_tags_for_count(html)
    return len([w for w in text.split() if w.strip()])




def contains_forbidden_language_or_markdown(html):
    text = str(html or "")

    # Chinese / CJK characters
    if re.search(r"[\u4e00-\u9fff]", text):
        return True

    # Markdown bullets or bold markers inside HTML output
    if re.search(r"(^|\n)\s*[-*]\s+\*\*", text):
        return True

    if "**" in text:
        return True

    # Meta commentary often produced by models after repair
    bad_phrases = [
        "se precisar",
        "please let me know",
        "if you need",
        "este texto",
        "上述",
        "文档",
        "conteúdo aprovado",
        "diretrizes",
        "guidelines"
    ]

    lower = text.lower()
    return any(phrase in lower for phrase in bad_phrases)


def repaired_still_obviously_invalid(html):
    html_lower = str(html or "").lower()

    h1_count = len(re.findall(r"<h1\b", html_lower))
    has_faq = (
        "<h2>perguntas frequentes</h2>" in html_lower
        or "<h2>faq</h2>" in html_lower
        or "perguntas frequentes" in html_lower
    )

    faq_question_count = len(re.findall(r"<h3\b", html_lower))

    risky_terms = [
        "infalível",
        "100%",
        "garantido",
        "garantida",
        "garantia",
        "detectar mentiras",
        "detecta mentiras",
        "detector de mentiras",
        "prova legal definitiva",
        "respostas que precisa",
        "identificar responsáveis",
        "identifica responsáveis",
        "provar fraude",
        "prova fraude",
    ]

    has_risky = any(term in html_lower for term in risky_terms)

    return (
        h1_count != 1
        or not has_faq
        or faq_question_count < 4
        or word_count(html) < 800
        or has_risky
        or contains_forbidden_language_or_markdown(html)
    )


def build_fallback_repair_prompt(draft, issues, knowledge_prompt=""):
    title = (
        draft.get("working_title")
        or draft.get("title")
        or draft.get("target_keyword")
        or "Professional polygraph assessment"
    )

    target_keyword = (
        draft.get("target_keyword")
        or draft.get("focus_keyphrase")
        or title
    )

    language = (
        draft.get("language")
        or draft.get("locale")
        or "en"
    )

    issue_text = "\n".join([f"- {issue}" for issue in issues])

    return f"""
You are Sofia, a professional SEO/GEO content assistant for polygraph service websites.

Rewrite the draft completely in the correct workspace language.

Workspace language:
{language}

Topic:
{title}

Target keyword:
{target_keyword}

CONTROLLED KNOWLEDGE CONTEXT:
{knowledge_prompt}

Validation issues to fix:
{issue_text}

Mandatory output rules:
- Return ONLY clean HTML.
- Preserve the original H1 and all existing H2/H3 headings unless a heading itself is invalid.
- Do not replace the article with a different structure.
- Do not add invented currencies, prices, numbers, legal claims, office claims, or unsupported examples.
- Do not use Markdown.
- Start with exactly one <h1>.
- Include at least 6 meaningful <h2> sections.
- The FAQ heading is mandatory and must be written exactly as one of these:
  - Portuguese: <h2>Perguntas frequentes</h2>
  - Spanish: <h2>Preguntas frecuentes</h2>
  - French: <h2>Questions fréquentes</h2>
  - English: <h2>Frequently Asked Questions</h2>
- Do not use alternative FAQ headings.
- Do not write "FAQ", "Dúvidas frequentes", "Perguntas comuns", or any other variation.
- Include at least 4 FAQ questions using <h3>.
- Minimum length: 1100 words. The final text must comfortably exceed 800 words after HTML cleaning.
- Use professional polygraph terminology.
- Use the controlled knowledge context as professional reference material only.
- Do not copy knowledge blocks verbatim.
- Paraphrase, synthesize, and localize the ideas naturally.
- Do not mirror sentence structure from the source blocks.
- Do not say the polygraph "detects lies" directly.
- Do not call the service "detector de mentiras" in Portuguese output unless explaining that this is an informal expression.
- Prefer "exame poligráfico", "avaliação poligráfica" or "teste de polígrafo".
- Do not say the polygraph identifies the responsible person, proves guilt, proves fraud, or provides the answers the client needs.
- Use cautious wording: "pode ajudar a clarificar", "pode apoiar a investigação", "pode contribuir para avaliar declarações específicas".
- Do not use absolute claims such as 100%, guaranteed, infallible, infalível, infalible, infaillible.
- Do not present the result as legal proof.
- Explain that the polygraph records physiological responses associated with specific questions.
- Include limitations and ethical considerations.
- Include a contact / consultation section.
- The entire output must be in the workspace language only.
- Do not include Chinese, English, Spanish, French, Arabic, Russian, or any other language unless the workspace language requires it.
- For Portuguese pt-PT/Angola output, do not use: você, equipe, estresse, registros, coletados.
- Prefer: neutral professional wording, equipa, stress/tensão, registos, recolhidos.
- For Portuguese output using pt-PT, avoid Brazilian terms such as "equipe", "você", "estresse", "gerenciamento", "registros", "coletados" and prefer "equipa", neutral wording, "stress" or "tensão", "gestão", "registos", "recolhidos".
- If any sentence appears in the wrong language, rewrite it into the workspace language.
- Do not include meta commentary about the text, instructions, guidelines, prompts, knowledge blocks, validation, SEO, GEO, or Sofia.
- Do not write phrases such as "this text follows the guidelines", "este texto segue as diretrizes", "conteúdo aprovado", "blocos de conhecimento", or similar.
- Do not invent company names, website names, office names, service brands, examiner names, or organization names.
- If no official company name is provided, use neutral wording such as "our team", "our service", "our examiners", or "the examiner".
- Keep the content highly specific to the topic.
- Do not invent company names, brand names, organization names, examiner names, certifications, offices, addresses, phone numbers, or associations.
- If no business name is supplied, use neutral wording such as "our team", "our service", "our examiners", or "the examiner".
- The first half of the page must focus on the actual issue being investigated, not on generic polygraph explanation.
- Use concrete scenarios related to the topic before explaining the polygraph process.

The first half of the page must focus on the actual problem being investigated.

Do not create a generic educational page about polygraph testing.

Use practical examples and realistic situations related to the topic.

Explain the business, personal, operational, or investigative consequences of the issue before discussing the polygraph process.

FAQ PRESERVATION RULES:
- Never remove an existing FAQ section.
- Never reduce the number of FAQ questions already present.
- Preserve existing FAQ questions.
- If fewer than 6 FAQ questions exist, add new questions until there are at least 6.
- Each FAQ question must use <h3>.
- Each FAQ answer must use one separate <p>.
- If the listed issues are only about a missing FAQ section or too few FAQ questions, preserve the existing page content.
- Do not rewrite, shorten, or replace the main article.
- Only add or correct the FAQ section.
- The FAQ heading must be exactly:
  - Portuguese: <h2>Perguntas frequentes</h2>
  - Spanish: <h2>Preguntas frecuentes</h2>
  - French: <h2>Questions fréquentes</h2>
  - English: <h2>Frequently Asked Questions</h2>
- Add at least 6 FAQ questions directly related to the page topic.
- Use <h3>Question</h3> followed by <p>Answer</p>.
""".strip()

def extract_draft_strategy(draft):
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


def format_strategy_for_repair_prompt(strategy):
    if not strategy:
        return "No structured strategy available."

    parts = []

    content_focus = strategy.get("content_focus", {}) or {}
    faq_strategy = strategy.get("faq_strategy", {}) or {}
    conversion_strategy = strategy.get("conversion_strategy", {}) or {}
    page_blueprint = strategy.get("page_blueprint", {}) or {}

    if page_blueprint.get("blueprint_id"):
        parts.append(f"Blueprint: {page_blueprint.get('blueprint_id')}")

    if content_focus:
        parts.append("Content focus:")
        parts.append(f"- Topic: {content_focus.get('topic', '')}")
        parts.append(f"- Focus keyphrase: {content_focus.get('focus_keyphrase', '')}")
        parts.append(f"- Topical focus target: {content_focus.get('topical_focus_target', '')}")
        parts.append(f"- Generic content limit: {content_focus.get('generic_content_limit', '')}")

        for item in content_focus.get("guidance", []) or []:
            parts.append(f"- {item}")

    if faq_strategy:
        parts.append("FAQ strategy:")
        parts.append(f"- Minimum questions: {faq_strategy.get('minimum_questions', 6)}")
        parts.append(f"- Question style: {faq_strategy.get('question_style', '')}")

    if conversion_strategy:
        parts.append("Conversion strategy:")
        parts.append(f"- Primary goal: {conversion_strategy.get('primary_goal', '')}")
        parts.append(f"- Contact style: {conversion_strategy.get('cta_style', '')}")

    return "\n".join(parts).strip()


def build_ai_expansion_prompt(draft, content, issues, knowledge_prompt=""):
    title = (
        draft.get("working_title")
        or draft.get("title")
        or draft.get("target_keyword")
        or "Professional polygraph assessment"
    )

    target_keyword = (
        draft.get("target_keyword")
        or draft.get("focus_keyphrase")
        or title
    )

    language = (
        draft.get("language")
        or draft.get("locale")
        or "en"
    )

    strategy = extract_draft_strategy(draft)
    strategy_prompt = format_strategy_for_repair_prompt(strategy)

    issue_text = "\n".join([f"- {issue}" for issue in issues])

    return f"""
You are Sofia, a professional SEO/GEO landing page expansion assistant.

Your task:
Expand the existing HTML without rewriting it.
Preserve all existing headings and section order.
Only add useful paragraphs to existing sections.
Do not replace the article.

Workspace language:
{language}

Topic:
{title}

Target keyword:
{target_keyword}

Validation issues:
{issue_text}

STRUCTURED STRATEGY:
{strategy_prompt}

CONTROLLED KNOWLEDGE CONTEXT:
{knowledge_prompt}

CRITICAL CONTENT DIRECTION:
- The page must be mainly about the specific issue in the topic.
- Do not write a generic page about polygraph testing.
- Do not start with "what is a polygraph" or a generic definition.
- Start with the client problem, risk, business concern, or practical situation.
- At least 70 percent of the content must directly support the target keyword and issue.
- General polygraph explanation must be secondary and brief.
- Use concrete examples related to the topic.
- Explain why this issue creates uncertainty, loss, distrust, operational risk, or decision pressure.
- Explain how a professional polygraph assessment may help clarify specific statements or involvement.
- Avoid absolute promises, guarantees, legal-proof claims, or exaggerated language.
- The entire output must be in the workspace language only.
- Do not include Chinese, English, Spanish, French, Arabic, Russian, or any other language unless the workspace language requires it.
- For Portuguese pt-PT/Angola output, do not use: você, equipe, estresse, registros, coletados.
- Prefer: neutral professional wording, equipa, stress/tensão, registos, recolhidos.
- For Portuguese output using pt-PT, avoid Brazilian terms such as "equipe", "você", "estresse", "gerenciamento", "registros", "coletados" and prefer "equipa", neutral wording, "stress" or "tensão", "gestão", "registos", "recolhidos".
- If any sentence appears in the wrong language, rewrite it into the workspace language.
- Do not include meta commentary about the text, instructions, guidelines, prompts, knowledge blocks, validation, SEO, GEO, or Sofia.
- Do not write phrases such as "this text follows the guidelines", "este texto segue as diretrizes", "conteúdo aprovado", "blocos de conhecimento", or similar.
- Do not invent company names, website names, office names, service brands, examiner names, or organization names.
- If no official company name is provided, use neutral wording such as "our team", "our service", "our examiners", or "the examiner".

ISSUE-FIRST REQUIREMENT:

The first 50 percent of the page must focus on:
- the specific problem
- common real-world scenarios
- operational consequences
- financial consequences
- investigation uncertainty
- practical examples

Do not begin by explaining the polygraph process.

Do not begin by explaining how a polygraph works.

Do not begin with ethics or procedure.

Establish the problem first.

Only after the problem has been explained should the page discuss how a professional polygraph assessment may assist an investigation.

Do not invent company names, brand names, examiner names, office names, addresses, phone numbers, certifications, professional associations, or organizations.

If no company or service name is provided, use neutral wording such as:
- our team
- our service
- our examiners
- the examiner

STRICT OUTPUT RULES:
- Return ONLY clean HTML.
- Preserve the original H1 and all existing H2/H3 headings unless a heading itself is invalid.
- Do not replace the article with a different structure.
- Do not add invented currencies, prices, numbers, legal claims, office claims, or unsupported examples.
- Do not use Markdown.
- Do not use code fences.
- Start with exactly one <h1>.
- Keep the same language as the original draft.
- Keep the same topic and search intent.
- Do not add unrelated topics.
- Do not mention Sofia, prompts, SEO, GEO, strategy, validation, or knowledge blocks.
- Do not copy the knowledge context verbatim.
- Do not introduce phone numbers, prices, addresses, legal claims, or guarantees.
- Do not say the polygraph detects lies directly.
- Do not use absolute claims such as 100%, guaranteed, infallible, infalível, infalible, or infaillible.
- Do not present the result as legal proof.
- Preserve every existing <a href=""> link exactly unless it is broken HTML.
- Do not remove internal links.
- Do not change URLs.
- Do not move links to unrelated sections.

STRUCTURE REQUIREMENTS:
- Final content must be at least 900 words, but preserve the original article structure.
- Use one <h1>.
- Use at least 6 useful <h2> sections.
- Each main <h2> section before FAQ must include at least 2 substantial paragraphs.
- Include one FAQ section with the exact heading required for the language:
  - Portuguese: <h2>Perguntas frequentes</h2>
  - Spanish: <h2>Preguntas frecuentes</h2>
  - French: <h2>Questions fréquentes</h2>
  - English: <h2>Frequently Asked Questions</h2>
- Do not use alternative FAQ headings.
- FAQ must include at least 6 question-answer pairs.
- Each FAQ question must use <h3>.
- Each FAQ answer must use <p>.
- End with a natural contact section.
- The contact section must not promise answers, certainty, proof, or successful identification of responsible persons.
- Use cautious contact wording such as "avaliar se o exame é adequado ao caso" or "discutir a situação de forma confidencial".

For issue-focused topics such as theft, sabotage, fraud, misconduct, corruption, harassment, pre-employment screening, internal investigations, inventory losses, or workplace incidents:
- Include practical issue-specific detail only where it naturally fits the existing sections.
- Include examples relevant to the topic.
- Explain how the issue affects organizations, managers, employees, investigations, trust, and decision-making.
- Avoid generic educational content about polygraph testing.

CONTENT TO IMPROVE:
{content}
""".strip()

def build_faq_only_repair_prompt(draft, issues, knowledge_prompt=""):
    title = (
        draft.get("working_title")
        or draft.get("title")
        or draft.get("target_keyword")
        or "Professional polygraph assessment"
    )

    target_keyword = (
        draft.get("target_keyword")
        or draft.get("focus_keyphrase")
        or title
    )

    language = (
        draft.get("language")
        or draft.get("locale")
        or "en"
    )

    return f"""
You are Sofia, a professional FAQ writing assistant.

Your task:
Create ONLY a valid FAQ HTML section for the page below.

Workspace language:
{language}

Topic:
{title}

Target keyword:
{target_keyword}

CONTROLLED KNOWLEDGE CONTEXT:
{knowledge_prompt}

STRICT OUTPUT RULES:
- Return ONLY the FAQ section.
- Do not rewrite the main article.
- Do not include Markdown.
- Do not use code fences.
- Do not mention Sofia, SEO, GEO, strategy, validation, or prompts.
- Do not invent company names, phone numbers, prices, addresses, offices, certifications, associations, or legal claims.
- The FAQ must be directly related to the topic and issue.
- Include at least 6 FAQ questions.
- Each question must use <h3>.
- Each answer must use <p>.

FAQ heading:
- Portuguese: <h2>Perguntas frequentes</h2>
- Spanish: <h2>Preguntas frecuentes</h2>
- French: <h2>Questions fréquentes</h2>
- English: <h2>Frequently Asked Questions</h2>

Use the correct heading for the workspace language.

The FAQ should answer practical questions about:
- the specific issue
- when the service may be appropriate
- what kind of facts/questions can be examined
- limits of the examination
- consent and professional procedure
- how the client should prepare the case

Return only the FAQ section in clean HTML.
""".strip()


def issues_require_fallback(issues):
    issue_text = " ".join(str(issue).lower() for issue in issues)

    triggers = [
        "invalid h1",
        "missing faq",
        "faq has fewer",
        "content too short",
        "risky claim",
        "infalível",
        "infalible",
        "infaillible",
        "100%",
        "guaranteed"
    ]

    return any(trigger in issue_text for trigger in triggers)


def extract_links(html):
    return re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>.*?</a>', str(html or ""), flags=re.IGNORECASE | re.DOTALL)


def repair_removed_existing_links(original_html, repaired_html):
    original_links = extract_links(original_html)
    repaired = str(repaired_html or "")

    for url in original_links:
        if url not in repaired:
            # Do not invent placement. Put missing original links back at the end as safe fallback.
            repaired = repaired.rstrip() + f'\n\n<p>Consultar também: <a href="{url}">{url}</a></p>'

    return repaired


def get_language_family(draft):
    language = str(
        draft.get("language")
        or draft.get("locale")
        or ""
    ).lower()

    if language.startswith("pt"):
        return "pt"
    if language.startswith("es"):
        return "es"
    if language.startswith("fr"):
        return "fr"

    return "en"


def main():
    print("=== Sofia: Repair Generated Content ===\n")

    if len(sys.argv) == 2:
        workspace_id_arg = None
        draft_id = sys.argv[1]
    elif len(sys.argv) == 3:
        workspace_id_arg = sys.argv[1]
        draft_id = sys.argv[2]
    else:
        print("Usage:")
        print("python app/repair_generated_content.py DRAFT-0005")
        print("python app/repair_generated_content.py WORKSPACE_ID DRAFT-0005")
        return

    try:
        if workspace_id_arg:
            workspace_id, draft_registry_file, draft_registry_data, draft = load_draft_registry_for_workspace_draft(
                workspace_id_arg,
                draft_id
            )
        else:
            workspace_id, draft_registry_file, draft_registry_data, draft = load_draft_registry_for_draft(draft_id)
    except Exception as e:
        print(f"ERROR: {e}")
        return

    validation = draft.get("validation", {})
    issues = validation.get("issues", [])

    if validation.get("status") != "failed":
        print("STOP: Draft validation status is not failed.")
        print(f"Current validation status: {validation.get('status')}")
        print("Repair cancelled to avoid damaging already valid, approved, prepared, or published content.")
        print("Only drafts with validation.status == 'failed' should be repaired automatically.")
        return

    if not issues:
        issues = [
            "Improve the draft so it passes Sofia validation.",
            "Ensure exactly one H1 heading is present.",
            "Ensure a clear FAQ section exists in the correct workspace language.",
            "Ensure at least 4 FAQ questions are included.",
            "Expand the content to meet the minimum required word count.",
            "Remove risky or absolute claims such as infalível, infalible, infaillible, 100%, guaranteed, or detects lies directly."
        ]

    content = (
        draft.get("generated_content", {}).get("content", "")
        or draft.get("html_content", "")
        or draft.get("draft_content", {}).get("content", "")
    )

    if not content:
        print("No content found.")
        return

    original_word_count = word_count(content)
    print(f"Original content word count: {original_word_count}")

    topic = (
        draft.get("working_title")
        or draft.get("title")
        or draft.get("target_keyword")
        or draft.get("focus_keyphrase")
        or ""
    )

    tags_hint = [
        "procedure",
        "ethics",
        "limitations",
        "questions",
        "faq",
        "service",
    ]

    knowledge_package = build_knowledge_package(
        workspace_id=workspace_id,
        topic=topic,
        tags_hint=tags_hint,
        max_blocks=6,
    )

    knowledge_prompt = format_package_for_prompt(knowledge_package)

    issue_text = " ".join(str(issue).lower() for issue in issues)

    faq_issue = (
        "missing faq" in issue_text
        or "faq has fewer" in issue_text
    )

    if faq_issue and not has_short_content_issue(issues):
        print("FAQ-only repair detected. Generating FAQ section without rewriting main content.")

        faq_prompt = build_faq_only_repair_prompt(
            draft=draft,
            issues=issues,
            knowledge_prompt=knowledge_prompt,
        )

        try:
            faq_section = call_ollama(faq_prompt)
        except Exception as e:
            print(f"FAQ repair failed: {e}")
            return

        if not faq_section:
            print("FAQ repair failed: empty model response.")
            return

        repaired = content.strip() + "\n\n" + faq_section.strip()
        repaired_word_count = word_count(repaired)

        if "generated_content" not in draft or not isinstance(draft["generated_content"], dict):
            draft["generated_content"] = {}

        draft["generated_content"]["content"] = repaired
        draft["html_content"] = repaired

        draft["repair"] = {
            "status": "completed",
            "model": OLLAMA_MODEL,
            "repair_type": "faq_only_ai_append",
            "issues_fixed": issues,
            "knowledge_base_used": True,
            "knowledge_topic": topic,
            "knowledge_blocks_used": [
                block.get("block_id") or block.get("id")
                for block in knowledge_package.get("selected_blocks", [])
            ],
            "original_word_count": original_word_count,
            "repaired_word_count": repaired_word_count,
        }

        draft["validation"] = {
            "status": "pending",
            "issues": []
        }

        draft_registry_data["scope"] = "workspace"
        draft_registry_data["workspace_id"] = workspace_id
        save_json(draft_registry_file, draft_registry_data)

        print(f"FAQ section added. Repaired content word count: {repaired_word_count}")
        print("Content repaired. Run validation again.")
        return

    language_profile = load_language_profile_for_draft(draft)

    prompt = build_repair_prompt(
        content,
        issues,
        knowledge_prompt=knowledge_prompt,
        draft=draft,
        language_profile=language_profile,
    )

    try:
        repaired = call_ollama(prompt)
    except Exception as e:
        print(f"Repair failed: {e}")
        return
    
    # First check what AI returned
    if "<a " in content.lower():
        original_links = len(extract_links(content))
        repaired_links = len(extract_links(repaired))

        if repaired_links < original_links:
            print(
                f"WARNING: AI reduced links "
                f"({original_links} -> {repaired_links}). Restoring."
            )

    repaired = repair_removed_existing_links(content, repaired)

    if not repaired:
        print("Repair failed: empty model response.")
        return

    if (not has_short_content_issue(issues)) and (issues_require_fallback(issues) or repaired_still_obviously_invalid(repaired)):
        print("AI repair needs stricter fallback repair prompt.")

        fallback_prompt = build_fallback_repair_prompt(
            draft,
            issues,
            knowledge_prompt=knowledge_prompt,
        )

        try:
            repaired = call_ollama(fallback_prompt)
        except Exception as e:
            print(f"Fallback repair failed: {e}")
            return

        if not repaired:
            print("Fallback repair failed: empty model response.")
            return

    if word_count(repaired) < 800:
        current_count = word_count(repaired)
        print(
            f"Repaired content still too short ({current_count} words). "
            "Running AI expansion pass."
        )

        expansion_prompt = build_ai_expansion_prompt(
            draft=draft,
            content=repaired,
            issues=issues,
            knowledge_prompt=knowledge_prompt,
        )

        try:
            expanded = call_ollama(expansion_prompt)
        except Exception as e:
            print(f"AI expansion failed: {e}")
            expanded = ""

        if expanded and word_count(expanded) > word_count(repaired):
            repaired = expanded
            print(f"AI expansion completed. New word count: {word_count(repaired)}")
        else:
            print(
                "AI expansion did not improve the draft. "
                "Keeping the best available repaired content."
            )

    contamination_term = has_configured_language_contamination(
        repaired,
        language_profile,
    )

    if contamination_term:
        print(
            "Configured workspace language contamination detected after repair: "
            f"{contamination_term}"
        )
        print("Keeping original content and applying deterministic workspace fallback expansion if needed.")
        repaired = deterministic_expand_from_profile(
            content=content,
            draft=draft,
            language_profile=language_profile,
            minimum_word_count=extract_minimum_word_count(issues),
        )

    minimum_required_words = extract_minimum_word_count(issues)

    if word_count(repaired) < minimum_required_words:
        print(
            f"Repaired content still below minimum after AI repair "
            f"({word_count(repaired)} < {minimum_required_words}). "
            "Applying deterministic workspace fallback expansion."
        )
        repaired = deterministic_expand_from_profile(
            content=repaired,
            draft=draft,
            language_profile=language_profile,
            minimum_word_count=minimum_required_words,
        )

    if contains_forbidden_language_or_markdown(repaired):
        print("STOP: Repaired content contains forbidden language, markdown, or meta commentary.")
        print("Repair cancelled to avoid damaging the draft.")
        return

    repaired_word_count = word_count(repaired)
    print(f"Repaired content word count: {repaired_word_count}")

    if repaired_word_count < original_word_count and not has_short_content_issue(issues):
        print("STOP: Repaired content is shorter than the original and this was not a short-content repair.")
        print("Repair cancelled to avoid degrading the draft.")
        return

    if "generated_content" not in draft or not isinstance(draft["generated_content"], dict):
        draft["generated_content"] = {}

    draft["generated_content"]["content"] = repaired
    draft["html_content"] = repaired

    draft["repair"] = {
        "status": "completed",
        "model": OLLAMA_MODEL,
        "issues_fixed": issues,
        "knowledge_base_used": True,
        "knowledge_topic": topic,
        "knowledge_blocks_used": [
            block.get("block_id") or block.get("id")
            for block in knowledge_package.get("selected_blocks", [])
        ],
        "original_word_count": original_word_count,
        "repaired_word_count": repaired_word_count,
    }

    draft["validation"] = {
        "status": "pending",
        "issues": []
    }

    draft_registry_data["scope"] = "workspace"
    draft_registry_data["workspace_id"] = workspace_id
    save_json(draft_registry_file, draft_registry_data)

    print("Content repaired. Run validation again.")


if __name__ == "__main__":
    main()