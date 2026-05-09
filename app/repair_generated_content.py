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


def build_repair_prompt(content, issues, knowledge_prompt=""):
    minimum_word_count = extract_minimum_word_count(issues)
    target_word_count = max(minimum_word_count + 250, 1100)
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
- If needed, add one or two new relevant <h2> sections.
- Preserve the original topic and search intent.
- Keep the content in the same language as the original content.
"""

    return f"""
You are Sofia, an SEO content correction assistant.

Your task:
Fix the HTML content below based ONLY on the listed issues.

STRICT RULES:
- Output ONLY clean HTML.
- Do NOT include explanations.
- Do NOT include markdown fences.
- Keep the same language as the original content.
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
        "prova legal definitiva",
    ]

    has_risky = any(term in html_lower for term in risky_terms)

    return (
        h1_count != 1
        or not has_faq
        or faq_question_count < 4
        or word_count(html) < 800
        or has_risky
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
- Do not use Markdown.
- Start with exactly one <h1>.
- Include at least 6 meaningful <h2> sections.
- Include one <h2>Perguntas frequentes</h2>, <h2>Preguntas frecuentes</h2>, <h2>Questions fréquentes</h2>, or <h2>Frequently Asked Questions</h2> section according to the language.
- Include at least 4 FAQ questions using <h3>.
- Minimum length: 1100 words. The final text must comfortably exceed 800 words after HTML cleaning.
- Use professional polygraph terminology.
- Use the controlled knowledge context as professional reference material only.
- Do not copy knowledge blocks verbatim.
- Paraphrase, synthesize, and localize the ideas naturally.
- Do not mirror sentence structure from the source blocks.
- Do not say the polygraph "detects lies" directly.
- Do not use absolute claims such as 100%, guaranteed, infallible, infalível, infalible, infaillible.
- Do not present the result as legal proof.
- Explain that the polygraph records physiological responses associated with specific questions.
- Include limitations and ethical considerations.
- Include a contact / consultation section.
- Keep the content specific to the topic.
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


def build_word_count_expansion_block(draft):
    title = (
        draft.get("working_title")
        or draft.get("title")
        or draft.get("target_keyword")
        or "avaliação poligráfica profissional"
    )

    lang = get_language_family(draft)

    if lang == "pt":
        return f"""
<h2>Critérios para avaliar se o caso é adequado</h2>
<p>Antes de avançar com uma avaliação poligráfica, é necessário confirmar se o caso permite perguntas claras, específicas e relacionadas com factos verificáveis. O examinador deve compreender o contexto, identificar o objetivo principal da avaliação e verificar se a pessoa avaliada entende o procedimento. Nem todas as situações são adequadas para este tipo de exame, especialmente quando existem perguntas vagas, interpretações subjetivas ou temas que não podem ser formulados de forma objetiva.</p>

<p>No contexto de {title}, a avaliação deve concentrar-se em declarações ou comportamentos concretos. O exame não deve ser apresentado como uma decisão final sobre o caso, mas como uma ferramenta técnica complementar. A análise deve ser integrada com outros elementos disponíveis, como documentos, entrevistas, comunicações, relatórios internos ou orientação profissional adequada.</p>

<h2>Responsabilidade profissional e limites do exame</h2>
<p>Um serviço de polígrafo profissional deve explicar claramente os limites do método. O polígrafo regista respostas fisiológicas associadas a perguntas específicas, mas não substitui investigação, auditoria, aconselhamento jurídico ou decisão de uma autoridade competente. A interpretação deve ser feita por um examinador treinado e deve considerar o conjunto do procedimento, desde a entrevista pré-teste até à análise dos dados registados.</p>

<p>A comunicação com o cliente deve ser prudente e realista. Não se devem prometer resultados absolutos ou conclusões fora dos limites técnicos do método. O objetivo é oferecer uma avaliação estruturada, confidencial e tecnicamente responsável, sempre respeitando a voluntariedade da pessoa avaliada e a adequação do caso ao procedimento.</p>

<h2>Consulta inicial e preparação do exame</h2>
<p>O primeiro passo é uma consulta inicial com o examinador. Nesta fase, o cliente explica a situação, apresenta a dúvida principal e informa quais factos pretende esclarecer. O examinador pode então avaliar se o tema é compatível com uma avaliação poligráfica e se existem condições adequadas para formular perguntas relevantes.</p>

<p>Quando o caso é tecnicamente adequado, o examinador prepara o procedimento com cuidado. As perguntas devem ser simples, diretas e compreensíveis. A pessoa avaliada deve receber explicações sobre o exame, os sensores utilizados, a forma como os dados são registados e os limites da interpretação. Esta preparação ajuda a proteger a qualidade técnica do exame e a confiança no processo.</p>
""".strip()

    if lang == "es":
        return f"""
<h2>Criterios para evaluar si el caso es adecuado</h2>
<p>Antes de avanzar con una evaluación poligráfica, es necesario confirmar si el caso permite preguntas claras, específicas y relacionadas con hechos verificables. El examinador debe comprender el contexto, identificar el objetivo principal de la evaluación y verificar que la persona evaluada entiende el procedimiento. No todas las situaciones son adecuadas para este tipo de examen, especialmente cuando existen preguntas vagas, interpretaciones subjetivas o temas que no pueden formularse de forma objetiva.</p>

<p>En el contexto de {title}, la evaluación debe centrarse en declaraciones o conductas concretas. El examen no debe presentarse como una decisión final sobre el caso, sino como una herramienta técnica complementaria. El análisis debe integrarse con otros elementos disponibles, como documentos, entrevistas, comunicaciones, informes internos u orientación profesional adecuada.</p>

<h2>Responsabilidad profesional y límites del examen</h2>
<p>Un servicio profesional de polígrafo debe explicar claramente los límites del método. El polígrafo registra respuestas fisiológicas asociadas a preguntas específicas, pero no sustituye una investigación, auditoría, asesoramiento jurídico o decisión de una autoridad competente. La interpretación debe ser realizada por un examinador capacitado y debe considerar el conjunto del procedimiento.</p>

<p>La comunicación con el cliente debe ser prudente y realista. No se deben prometer resultados absolutos, garantías o conclusiones fuera de los límites técnicos del método. El objetivo es ofrecer una evaluación estructurada, confidencial y técnicamente responsable, respetando siempre la voluntariedad de la persona evaluada y la adecuación del caso al procedimiento.</p>

<h2>Consulta inicial y preparación del examen</h2>
<p>El primer paso es una consulta inicial con el examinador. En esta fase, el cliente explica la situación, presenta la duda principal e indica qué hechos desea aclarar. El examinador puede evaluar si el tema es compatible con una evaluación poligráfica y si existen condiciones adecuadas para formular preguntas relevantes.</p>
""".strip()

    if lang == "fr":
        return f"""
<h2>Critères pour évaluer si le cas est adapté</h2>
<p>Avant de procéder à une évaluation polygraphique, il est nécessaire de confirmer que le cas permet de formuler des questions claires, spécifiques et liées à des faits vérifiables. L’examinateur doit comprendre le contexte, identifier l’objectif principal de l’évaluation et vérifier que la personne évaluée comprend la procédure. Toutes les situations ne sont pas adaptées à ce type d’examen, surtout lorsque les questions sont vagues, subjectives ou difficiles à formuler objectivement.</p>

<p>Dans le contexte de {title}, l’évaluation doit porter sur des déclarations ou des comportements concrets. L’examen ne doit pas être présenté comme une décision finale sur le cas, mais comme un outil technique complémentaire. L’analyse doit être intégrée à d’autres éléments disponibles, comme des documents, entretiens, communications, rapports internes ou conseils professionnels appropriés.</p>

<h2>Responsabilité professionnelle et limites de l’examen</h2>
<p>Un service professionnel de polygraphe doit expliquer clairement les limites de la méthode. Le polygraphe enregistre des réponses physiologiques associées à des questions spécifiques, mais il ne remplace pas une enquête, un audit, un conseil juridique ou une décision d’une autorité compétente. L’interprétation doit être réalisée par un examinateur formé et doit tenir compte de l’ensemble de la procédure.</p>

<p>La communication avec le client doit rester prudente et réaliste. Il ne faut pas promettre de résultats absolus, de garanties ou de conclusions dépassant les limites techniques de la méthode. L’objectif est d’offrir une évaluation structurée, confidentielle et techniquement responsable, en respectant toujours le consentement de la personne évaluée et l’adéquation du cas à la procédure.</p>

<h2>Consultation initiale et préparation de l’examen</h2>
<p>La première étape consiste en une consultation initiale avec l’examinateur. À ce stade, le client explique la situation, présente la question principale et indique les faits qu’il souhaite clarifier. L’examinateur peut alors déterminer si le sujet est compatible avec une évaluation polygraphique et si les conditions permettent de formuler des questions pertinentes.</p>
""".strip()

    return f"""
<h2>Criteria for assessing whether the case is suitable</h2>
<p>Before proceeding with a polygraph assessment, it is necessary to confirm whether the case allows clear, specific questions related to verifiable facts. The examiner must understand the context, identify the main objective of the assessment, and confirm that the examinee understands the procedure. Not every situation is suitable for this type of examination, especially when the questions are vague, subjective, or cannot be formulated objectively.</p>

<p>In the context of {title}, the assessment should focus on concrete statements or behaviors. The examination should not be presented as a final decision on the case, but as a complementary technical tool. The analysis should be considered alongside other available information, such as documents, interviews, communications, internal reports, or appropriate professional guidance.</p>

<h2>Professional responsibility and limits of the examination</h2>
<p>A professional polygraph service must clearly explain the limits of the method. The polygraph records physiological responses associated with specific questions, but it does not replace an investigation, audit, legal advice, or decision by a competent authority. Interpretation must be carried out by a trained examiner and should consider the entire procedure.</p>

<p>Communication with the client must be careful and realistic. The service should not promise absolute results, guarantees, or conclusions beyond the technical limits of the method. The objective is to provide a structured, confidential, and technically responsible assessment while respecting the voluntary participation of the examinee and the suitability of the case.</p>

<h2>Initial consultation and examination preparation</h2>
<p>The first step is an initial consultation with the examiner. At this stage, the client explains the situation, presents the main doubt, and identifies the facts that need clarification. The examiner can then assess whether the topic is compatible with a polygraph assessment and whether relevant questions can be formulated properly.</p>
""".strip()


def expand_if_still_too_short(repaired, draft, minimum_words=800):
    current_count = word_count(repaired)

    if current_count >= minimum_words:
        return repaired

    print(f"Repaired content still too short ({current_count} words). Adding deterministic expansion block.")

    expansion = build_word_count_expansion_block(draft)

    return f"{repaired.strip()}\n\n{expansion.strip()}"


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

    prompt = build_repair_prompt(
        content,
        issues,
        knowledge_prompt=knowledge_prompt,
    )

    try:
        repaired = call_ollama(prompt)
    except Exception as e:
        print(f"Repair failed: {e}")
        return

    if not repaired:
        print("Repair failed: empty model response.")
        return

    if issues_require_fallback(issues) or repaired_still_obviously_invalid(repaired):
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

    repaired = expand_if_still_too_short(repaired, draft, minimum_words=800)

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