import json
import re
import sys
from pathlib import Path

from workspace_paths import (
    find_draft_any_workspace,
    get_workspace_draft_registry_path,
    load_json as load_json_workspace,
)

SOFIA_ROOT = Path(__file__).resolve().parents[1]
# Deprecated: draft registries are now workspace-level.
GLOBAL_DRAFT_REGISTRY_FILE = SOFIA_ROOT / "sites" / "draft_registry.json"


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


def find_draft(drafts, draft_id):
    for d in drafts:
        if d.get("draft_id") == draft_id:
            return d
    return None


def strip_code_fences(content: str):
    return re.sub(r"```html|```", "", content or "", flags=re.IGNORECASE).strip()


def load_language_profile_for_draft(draft):
    workspace_path = draft.get("workspace_path", "")
    if not workspace_path:
        return {}

    profile_path = SOFIA_ROOT / workspace_path / "language_profile.json"

    if not profile_path.exists():
        return {}

    return load_json(profile_path)


def remove_full_html_wrapper(content: str):
    content = re.sub(r"<!DOCTYPE.*?>", "", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<html.*?>|</html>", "", content, flags=re.IGNORECASE)
    content = re.sub(r"<head.*?>.*?</head>", "", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<body.*?>|</body>", "", content, flags=re.IGNORECASE)
    return content.strip()


def extract_body_content(content):
    body_patterns = [
        r"###\s*Body Content\s*\(HTML format\)\s*:\s*(.*)",
        r"###\s*Body Content\s*:\s*(.*)",
        r"###\s*Conteúdo do Corpo\s*\(formato HTML\)\s*:\s*(.*)",
        r"###\s*Conteúdo do Corpo\s*:\s*(.*)",
        r"###\s*Conteúdo\s*:\s*(.*)",
        r"###\s*Cuerpo del contenido\s*:\s*(.*)",
        r"###\s*Contenido principal\s*:\s*(.*)",
        r"###\s*Contenu principal\s*:\s*(.*)",
    ]

    for pattern in body_patterns:
        match = re.search(pattern, content, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()

    return content.strip()


def remove_markdown_metadata_blocks(content):
    # Remove metadata sections that the model may append after the HTML body.
    # These sections must never be published as visible page content.
    trailing_metadata_patterns = [
        r"\n\s*#{1,4}\s*Yoast SEO Fields\b.*\Z",
        r"\n\s*#{1,4}\s*SEO Fields\b.*\Z",
        r"\n\s*#{1,4}\s*Image Suggestions\b.*\Z",
        r"\n\s*#{1,4}\s*Internal Link Suggestions\b.*\Z",
        r"\n\s*#{1,4}\s*External Link Suggestions\b.*\Z",
        r"\n\s*#{1,4}\s*Suggested Image\b.*\Z",
        r"\n\s*#{1,4}\s*Yoast\b.*\Z",
        r"\n\s*Yoast SEO Fields\b.*\Z",
        r"\n\s*Focus Keyphrase\s*:.*\Z",
        r"\n\s*SEO Title\s*:.*\Z",
        r"\n\s*Meta Description\s*:.*\Z",
        r"\n\s*Slug\s*:.*\Z",
        r"\n\s*Images\s*:.*\Z",
    ]

    for pattern in trailing_metadata_patterns:
        content = re.sub(pattern, "", content, flags=re.IGNORECASE | re.DOTALL)

    metadata_fields = [
        "Title",
        "Meta Title",
        "Meta Description",
        "Slug",
        "Focus Keyphrase",
        "H1",
        "Body Content",
        "Body Content (HTML format)",
        "Yoast SEO Fields",
        "SEO Fields",
        "Image Suggestions",
        "Suggested Image",
        "Internal Link Suggestions",
        "External Link Suggestions",
    ]

    for field in metadata_fields:
        pattern = rf"###\s*{re.escape(field)}\s*:?.*?(?=\n\s*###|\Z)"
        content = re.sub(pattern, "", content, flags=re.IGNORECASE | re.DOTALL)

    return content.strip()


def ensure_h1(content, h1_text):
    h1_count = len(re.findall(r"<h1\b", content, flags=re.IGNORECASE))

    if h1_count == 0 and h1_text:
        content = f"<h1>{h1_text}</h1>\n\n{content}"

    return content


def demote_extra_h1_tags(content: str):
    h1_matches = list(
        re.finditer(
            r"<h1[^>]*>.*?</h1>",
            content,
            flags=re.IGNORECASE | re.DOTALL
        )
    )

    if len(h1_matches) <= 1:
        return content

    rest = content[h1_matches[0].end():]

    rest = re.sub(
        r"<h1([^>]*)>(.*?)</h1>",
        r"<h2\1>\2</h2>",
        rest,
        flags=re.IGNORECASE | re.DOTALL
    )

    return content[:h1_matches[0].end()] + rest


def normalize_faq_heading(content: str):
    faq_patterns = [
        r"<h1[^>]*>\s*(frequently asked questions|faq|perguntas frequentes|preguntas frecuentes|questions fréquentes)\s*</h1>",
        r"<h2[^>]*>\s*(frequently asked questions|faq|perguntas frequentes|preguntas frecuentes|questions fréquentes)\s*</h2>",
        r"<h3[^>]*>\s*(frequently asked questions|faq|perguntas frequentes|preguntas frecuentes|questions fréquentes)\s*</h3>",
    ]

    for pattern in faq_patterns:
        content = re.sub(
            pattern,
            "<h2>Perguntas frequentes</h2>",
            content,
            flags=re.IGNORECASE
        )

    return content


def fix_invalid_tags(content: str):
    content = content.replace("</br>", "")
    content = content.replace("<br>", "")
    content = content.replace("<br/>", "")
    return content


def remove_forbidden_phrases(content: str, language_profile: dict):
    risky_rules = language_profile.get("risky_phrase_rules", {})
    replacements = risky_rules.get("safe_replacements", {})

    fallback_replacements = {
        "100%": "de forma profissional",
        "garantido": "avaliado profissionalmente",
        "garantida": "avaliada profissionalmente",
        "guaranteed": "professionally assessed",
        "certified": "professional",
        "legally accepted": "subject to proper legal evaluation",
        "legally admissible": "subject to proper legal evaluation",
    }

    merged = {}
    merged.update(fallback_replacements)
    merged.update(replacements)

    for phrase, replacement in merged.items():
        content = re.sub(
            re.escape(phrase),
            replacement,
            content,
            flags=re.IGNORECASE
        )

    return content


def fix_faq_structure(content: str):
    content = re.sub(
        r"<p>\s*<strong>(.*?)</strong>\s*</p>",
        r"<h3>\1</h3>",
        content,
        flags=re.IGNORECASE
    )
    return content


def ensure_faq_heading(content: str):
    content = re.sub(
        r"<h1>\s*Perguntas frequentes\s*</h1>",
        "<h2>Perguntas frequentes</h2>",
        content,
        flags=re.IGNORECASE
    )
    return content


def get_faq_heading_match(content: str):
    return re.search(
        r"<h2[^>]*>\s*(Perguntas frequentes|FAQ|Perguntas e respostas|Preguntas frecuentes|Questions fréquentes|Frequently asked questions)\s*</h2>",
        content,
        flags=re.IGNORECASE
    )


def get_faq_question_count(content: str):
    faq_heading = get_faq_heading_match(content)

    if not faq_heading:
        return 0

    faq_content = content[faq_heading.end():]

    next_h2 = re.search(r"<h2\b", faq_content, flags=re.IGNORECASE)
    if next_h2:
        faq_content = faq_content[:next_h2.start()]

    return len(re.findall(r"<h3\b", faq_content, flags=re.IGNORECASE))


def get_language_for_draft(draft):
    language = str(draft.get("language", "") or "").lower()

    if language.startswith("pt"):
        return "pt"
    if language.startswith("es"):
        return "es"
    if language.startswith("fr"):
        return "fr"

    return "en"


def build_missing_faq_block(draft, current_count):
    language = get_language_for_draft(draft)
    topic = (
        draft.get("working_title")
        or draft.get("title")
        or draft.get("target_keyword")
        or "este serviço"
    )

    if language == "pt":
        questions = [
            (
                f"O teste de polígrafo pode ser usado em casos de {topic}?",
                "O teste de polígrafo pode ser usado como ferramenta auxiliar em investigações internas, desde que seja realizado por um examinador qualificado, com consentimento informado e respeitando os limites éticos e legais aplicáveis."
            ),
            (
                "O polígrafo substitui uma investigação interna?",
                "Não. O polígrafo não substitui uma investigação interna completa. Ele pode ajudar a avaliar declarações específicas, mas deve ser integrado com outros elementos de análise, documentação e avaliação profissional."
            ),
            (
                "Que tipo de perguntas podem ser feitas durante o teste?",
                "As perguntas devem ser claras, específicas e diretamente relacionadas ao assunto em investigação. A formulação das perguntas deve ser feita pelo examinador para evitar ambiguidades e proteger a validade do procedimento."
            ),
            (
                "Como solicitar uma avaliação profissional?",
                "O primeiro passo é contactar o examinador, explicar o contexto do caso e confirmar se o serviço é adequado. O examinador poderá indicar as condições, limitações e requisitos necessários antes de qualquer teste."
            ),
        ]
        heading = "Perguntas frequentes"

    elif language == "es":
        questions = [
            (
                f"¿Puede utilizarse el polígrafo en casos de {topic}?",
                "El polígrafo puede utilizarse como herramienta auxiliar en investigaciones internas, siempre que sea aplicado por un examinador cualificado, con consentimiento informado y respetando los límites éticos y legales aplicables."
            ),
            (
                "¿El polígrafo sustituye una investigación interna?",
                "No. El polígrafo no sustituye una investigación completa. Puede ayudar a evaluar declaraciones específicas, pero debe integrarse con otros elementos de análisis profesional."
            ),
            (
                "¿Qué tipo de preguntas pueden realizarse durante la prueba?",
                "Las preguntas deben ser claras, específicas y directamente relacionadas con el asunto investigado. La formulación debe ser realizada por el examinador para evitar ambigüedades."
            ),
            (
                "¿Cómo solicitar una evaluación profesional?",
                "El primer paso es contactar con el examinador, explicar el contexto del caso y confirmar si el servicio es adecuado para la situación concreta."
            ),
        ]
        heading = "Preguntas frecuentes"

    elif language == "fr":
        questions = [
            (
                f"Le polygraphe peut-il être utilisé dans les cas de {topic} ?",
                "Le polygraphe peut être utilisé comme outil complémentaire dans certaines évaluations, à condition d’être appliqué par un examinateur qualifié, avec consentement éclairé et dans le respect des limites éthiques et légales."
            ),
            (
                "Le polygraphe remplace-t-il une enquête interne ?",
                "Non. Le polygraphe ne remplace pas une enquête complète. Il peut aider à évaluer des déclarations spécifiques, mais doit être intégré à une analyse professionnelle plus large."
            ),
            (
                "Quel type de questions peut être posé pendant le test ?",
                "Les questions doivent être claires, spécifiques et directement liées au sujet évalué. Leur formulation doit être préparée par l’examinateur afin d’éviter les ambiguïtés."
            ),
            (
                "Comment demander une évaluation professionnelle ?",
                "La première étape consiste à contacter l’examinateur, expliquer le contexte du cas et confirmer si le service est adapté à la situation."
            ),
        ]
        heading = "Questions fréquentes"

    else:
        questions = [
            (
                f"Can a polygraph test be used in cases involving {topic}?",
                "A polygraph test may be used as an auxiliary tool in specific assessments when conducted by a qualified examiner, with informed consent and within applicable ethical and legal limits."
            ),
            (
                "Does the polygraph replace an internal investigation?",
                "No. The polygraph does not replace a complete investigation. It may help assess specific statements, but it should be combined with other professional review elements."
            ),
            (
                "What type of questions can be asked during the test?",
                "Questions should be clear, specific, and directly related to the matter being assessed. They should be formulated by the examiner to avoid ambiguity."
            ),
            (
                "How can someone request a professional assessment?",
                "The first step is to contact the examiner, explain the case context, and confirm whether the service is appropriate for the specific situation."
            ),
        ]
        heading = "Frequently asked questions"

    needed = max(0, 4 - current_count)

    if needed == 0:
        return ""

    selected = questions[-needed:]

    faq_html = ""

    if current_count == 0:
        faq_html += f"\n\n<h2>{heading}</h2>\n"

    for question, answer in selected:
        faq_html += f"<h3>{question}</h3>\n<p>{answer}</p>\n"

    return faq_html.strip()


def ensure_minimum_faq_questions(content: str, draft: dict):
    current_count = get_faq_question_count(content)

    if current_count >= 4:
        return content

    missing_block = build_missing_faq_block(draft, current_count)

    if not missing_block:
        return content

    faq_heading = get_faq_heading_match(content)

    if not faq_heading:
        return content.strip() + "\n\n" + missing_block

    insert_position = len(content)

    after_faq = content[faq_heading.end():]
    next_h2 = re.search(r"<h2\b", after_faq, flags=re.IGNORECASE)

    if next_h2:
        insert_position = faq_heading.end() + next_h2.start()

    return (
        content[:insert_position].strip()
        + "\n\n"
        + missing_block
        + "\n\n"
        + content[insert_position:].strip()
    ).strip()


def get_content_from_draft(draft):
    return (
        draft.get("generated_content", {}).get("content", "")
        or draft.get("html_content", "")
        or draft.get("draft_content", {}).get("content", "")
    )


def synchronize_content_fields(draft, content):
    if "generated_content" not in draft or not isinstance(draft["generated_content"], dict):
        draft["generated_content"] = {}

    draft["generated_content"]["content"] = content
    draft["html_content"] = content


def extract_markdown_field(content, field_name):
    pattern = rf"###\s*{re.escape(field_name)}\s*:\s*(.*?)(?=\n###\s|\Z)"
    match = re.search(pattern, content, flags=re.IGNORECASE | re.DOTALL)

    if not match:
        return ""

    return match.group(1).strip()


def extract_body_from_markdown_package(content):
    body_labels = [
        "Body Content (HTML format)",
        "Body Content",
        "Conteúdo",
        "Contenido",
        "Contenu"
    ]

    for label in body_labels:
        body = extract_markdown_field(content, label)
        if body:
            return body

    return content


def extract_h1_from_markdown_package(content):
    h1 = extract_markdown_field(content, "H1")
    if h1:
        return strip_html_for_preview(h1).strip()

    title = extract_markdown_field(content, "Title")
    if title:
        return strip_html_for_preview(title).strip()

    return ""


def strip_html_for_preview(html):
    text = re.sub(r"<[^>]+>", " ", str(html or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def markdownish_body_to_html(body, h1_text=""):
    html = str(body or "").strip()

    # Remove markdown headings if present.
    html = re.sub(r"^###\s+(.+?)\s*$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^##\s+(.+?)\s*$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^#\s+(.+?)\s*$", r"<h1>\1</h1>", html, flags=re.MULTILINE)

    # If there are no HTML tags, create paragraph structure.
    if not re.search(r"<h1|<h2|<h3|<p|<ul|<ol|<li", html, flags=re.IGNORECASE):
        lines = [line.strip() for line in html.splitlines() if line.strip()]
        converted = []

        for line in lines:
            # Simple heading heuristic: short line without final punctuation.
            if (
                len(line.split()) <= 12
                and not line.endswith((".", ":", ";", ","))
            ):
                converted.append(f"<h2>{line}</h2>")
            else:
                converted.append(f"<p>{line}</p>")

        html = "\n".join(converted)

    # Ensure one H1 if missing.
    h1_count = len(re.findall(r"<h1\b", html, flags=re.IGNORECASE))
    if h1_count == 0 and h1_text:
        html = f"<h1>{h1_text}</h1>\n\n{html}"

    return html


def main():
    print("=== Sofia: Clean Generated HTML ===\n")

    if len(sys.argv) == 2:
        workspace_id_arg = None
        draft_id = sys.argv[1]
    elif len(sys.argv) == 3:
        workspace_id_arg = sys.argv[1]
        draft_id = sys.argv[2]
    else:
        print("Usage:")
        print("python app/clean_generated_html.py DRAFT-0005")
        print("python app/clean_generated_html.py WORKSPACE_ID DRAFT-0005")
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

    content = get_content_from_draft(draft)

    raw_content = str(content or "")

    if (
        "### Body Content" in raw_content
        or "### H1" in raw_content
        or "### Title" in raw_content
        or "### Meta Title" in raw_content
    ):
        h1_text = extract_h1_from_markdown_package(raw_content)
        body_content = extract_body_from_markdown_package(raw_content)
        content = markdownish_body_to_html(body_content, h1_text=h1_text)

    if not content:
        print("No content found.")
        return

    language_profile = load_language_profile_for_draft(draft)

    h1_text = (
        draft.get("h1")
        or draft.get("title")
        or draft.get("working_title")
        or draft.get("target_keyword")
        or ""
    )

    content = strip_code_fences(content)
    content = remove_full_html_wrapper(content)
    content = remove_markdown_metadata_blocks(content)
    content = ensure_h1(content, h1_text)
    content = demote_extra_h1_tags(content)
    content = normalize_faq_heading(content)
    content = fix_invalid_tags(content)
    content = remove_forbidden_phrases(content, language_profile)
    content = fix_faq_structure(content)
    content = ensure_faq_heading(content)
    content = ensure_minimum_faq_questions(content, draft)

    synchronize_content_fields(draft, content)

    draft_registry_data["scope"] = "workspace"
    draft_registry_data["workspace_id"] = workspace_id
    save_json(draft_registry_file, draft_registry_data)

    print("Content cleaned successfully.")
    print(f"Workspace registry: {draft_registry_file}")


if __name__ == "__main__":
    main()