import json
import re
import sys
from pathlib import Path

try:
    from app.image_assets.image_validator import validate_image_plan
except ModuleNotFoundError:
    from image_assets.image_validator import validate_image_plan


from workspace_paths import (
    find_draft_any_workspace,
    get_workspace_draft_registry_path,
)


SOFIA_ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = SOFIA_ROOT / "data" / "workspaces.json"
# Deprecated: draft registries are now workspace-level.
GLOBAL_DRAFT_REGISTRY_FILE = SOFIA_ROOT / "sites" / "draft_registry.json"


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


def load_draft_registry_for_workspace_draft(workspace_id, draft_id):
    registry_path = get_workspace_draft_registry_path(workspace_id)
    registry_data = load_json(registry_path)

    for draft in registry_data.get("drafts", []):
        if draft.get("draft_id") == draft_id:
            return workspace_id, registry_path, registry_data, draft

    raise RuntimeError(f"Draft not found in workspace registry: {workspace_id} {draft_id}")


def find_workspace(workspaces, workspace_id):
    for workspace in workspaces.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def get_drafts(registry):
    if isinstance(registry, dict) and "drafts" in registry:
        return registry["drafts"]
    if isinstance(registry, list):
        return registry
    return []


def find_draft(drafts, draft_id):
    for draft in drafts:
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def find_workspace_for_draft(workspaces, draft_id):
    for workspace in workspaces.get("workspaces", []):
        draft_registry_path = workspace.get("draft_registry_path")
        if not draft_registry_path:
            continue

        full_path = SOFIA_ROOT / draft_registry_path

        if not full_path.exists():
            continue

        try:
            data = load_json(full_path)
        except Exception:
            continue

        draft = find_draft(get_drafts(data), draft_id)

        if draft:
            return workspace, full_path, data, draft

    if LEGACY_DRAFT_REGISTRY_FILE.exists():
        data = load_json(LEGACY_DRAFT_REGISTRY_FILE)
        draft = find_draft(get_drafts(data), draft_id)

        if draft:
            return None, LEGACY_DRAFT_REGISTRY_FILE, data, draft

    return None, None, None, None


def count_tag(content, tag):
    return len(re.findall(f"<{tag}", content, re.IGNORECASE))


def detect_english_headings(content):
    english_words = ["practical", "examples", "introduction"]
    issues = []

    for word in english_words:
        if re.search(rf"<h[1-3][^>]*>.*{word}.*</h[1-3]>", content, re.IGNORECASE):
            issues.append(f"English heading detected: {word}")

    return issues


def load_language_profile_for_workspace(workspace):
    if not workspace:
        return {}

    folder_path = workspace.get("folder_path", "")
    if not folder_path:
        return {}

    profile_path = SOFIA_ROOT / folder_path / "language_profile.json"

    if not profile_path.exists():
        return {}

    return load_json(profile_path)


def load_language_profile_for_draft(draft):
    workspace_path = draft.get("workspace_path", "")
    if not workspace_path:
        return {}

    profile_path = SOFIA_ROOT / workspace_path / "language_profile.json"

    if not profile_path.exists():
        return {}

    return load_json(profile_path)






def detect_workspace_language_contamination(content, workspace, draft, language_profile):
    issues = []

    html = str(content or "")
    visible_text = re.sub(r"<[^>]+>", " ", html)
    visible_lower = visible_text.lower()
    html_lower = html.lower()

    workspace_id = (
        draft.get("workspace_id")
        or (workspace or {}).get("workspace_id")
        or language_profile.get("workspace_id")
        or ""
    )

    language = str(
        draft.get("language")
        or language_profile.get("language")
        or (workspace or {}).get("language")
        or ""
    ).lower()

    forbidden_terms = language_profile.get("forbidden_terms", []) or []
    forbidden_url_patterns = language_profile.get("forbidden_url_patterns", []) or []

    # Safe fallback for Spanish workspaces.
    # Prefer language_profile.json, but protect local.es even if the profile is incomplete.
    if workspace_id == "local.es" or language.startswith("es"):
        forbidden_terms = list(dict.fromkeys(forbidden_terms + [
            "também",
            "perguntas",
            "respostas",
            "secção",
            "orientação",
            "connosco",
            "contacte-nos",
            "entre em contacto",
            "contacto connosco"
        ]))

        forbidden_url_patterns = list(dict.fromkeys(forbidden_url_patterns + [
            "/poligrafo-ao/",
            "/perguntas-respostas/",
            "/contato/",
            "poligrafoangola.com",
            "poligrafoportugal.com"
        ]))

    for term in forbidden_terms:
        term = str(term or "").strip().lower()
        if term and term in visible_lower:
            issues.append(f"Workspace language contamination detected: {term}")

    for pattern in forbidden_url_patterns:
        pattern = str(pattern or "").strip().lower()
        if pattern and pattern in html_lower:
            issues.append(f"Forbidden workspace URL/path detected: {pattern}")

    return issues

def detect_wrong_language_or_markup(content):
    issues = []
    text = str(content or "")

    if re.search(r"[\u4e00-\u9fff]", text):
        issues.append("Wrong-language text detected: Chinese/CJK characters")

    if "**" in text:
        issues.append("Markdown formatting detected inside HTML: **")

    if re.search(r"(^|\n)\s*[-*]\s+\*\*", text):
        issues.append("Markdown bullet list detected inside HTML")

    lower = text.lower()

    meta_phrases = [
        "please let me know",
        "if you need",
        "se precisar",
        "este texto segue",
        "diretrizes",
        "guidelines",
        "conteúdo aprovado",
        "blocos de conhecimento",
        "上述",
        "文档"
    ]

    for phrase in meta_phrases:
        if phrase in lower:
            issues.append(f"Meta commentary detected: {phrase}")

    return issues


def detect_pt_pt_localization_issues(content, workspace, draft):
    warnings = []

    language = str(
        draft.get("language")
        or draft.get("locale")
        or workspace.get("language")
        or ""
    ).lower()

    if not language.startswith("pt"):
        return warnings

    text = re.sub(r"<[^>]+>", " ", str(content or ""))
    lower = text.lower()

    avoid_terms = {
        "equipe": "Prefer pt-PT/Angola wording: equipa",
        "você": "Avoid Brazilian/direct wording in pt-PT content; prefer neutral professional wording",
        "estresse": "Prefer pt-PT wording: stress or tensão",
        "gerenciamento": "Prefer pt-PT wording: gestão",
        "registros": "Prefer pt-PT wording: registos",
        "coletados": "Prefer pt-PT wording: recolhidos",
        "coletadas": "Prefer pt-PT wording: recolhidas"
    }

    for term, message in avoid_terms.items():
        if re.search(rf"\b{re.escape(term)}\b", lower):
            warnings.append(f"Portuguese localization warning: {term} — {message}")

    return warnings





def get_configured_quality_replacement_sources(language_profile: dict) -> set:
    """
    Return phrases that are already handled by workspace-level
    content_quality_replacements.

    These are soft cleanup rules, not validation failures.
    """
    sources = set()

    rules = language_profile.get("content_quality_replacements", [])

    if not isinstance(rules, list):
        return sources

    for rule in rules:
        if not isinstance(rule, dict):
            continue

        source = str(rule.get("from") or "").strip().lower()
        if source:
            sources.add(source)

    return sources


def detect_workspace_content_quality_warnings(content, language_profile):
    configured_replacement_sources = get_configured_quality_replacement_sources(language_profile)
    warnings = []

    quality_rules = language_profile.get("content_quality_rules", {})
    warning_phrases = quality_rules.get("warning_phrases", [])

    text_plain = re.sub(r"<[^>]+>", " ", str(content or ""))
    lower = text_plain.lower()

    for item in warning_phrases:
        if isinstance(item, str):
            phrase = item.strip()
            message = "Workspace-defined content quality warning."
        elif isinstance(item, dict):
            phrase = str(item.get("phrase", "")).strip()
            message = str(item.get("message", "")).strip()
        else:
            continue

        if not phrase:
            continue

        phrase_lower = phrase.lower()

        # If this phrase is already handled by workspace-level
        # content_quality_replacements, do not keep warning after cleanup.
        if phrase_lower in configured_replacement_sources:
            continue

        if phrase_lower in lower:
            if message:
                warnings.append(f"Workspace content quality warning: {phrase} — {message}")
            else:
                warnings.append(f"Workspace content quality warning: {phrase}")

    return warnings





def detect_placeholder_content(content, language_profile):
    """
    Detect placeholder content without hardcoding workspace-language phrases.

    Structural rule:
    - Python only detects generic bracket placeholders, e.g. [example].
    - Workspace/language-specific placeholder phrases must live in:
      language_profile.json -> content_quality_rules.forbidden_placeholders
    """
    issues = []

    text = str(content or "")
    lower = text.lower()

    configured = (
        language_profile
        .get("content_quality_rules", {})
        .get("forbidden_placeholders", [])
    )

    for pattern in configured:
        pattern = str(pattern or "").strip()
        if not pattern:
            continue

        if pattern.startswith("r:"):
            raw_pattern = pattern[2:]
            if re.search(raw_pattern, text, re.IGNORECASE):
                issues.append(f"Placeholder content detected: {pattern}")
        elif pattern.lower() in lower:
            issues.append(f"Placeholder content detected: {pattern}")

    # Language-agnostic structural placeholder catch.
    if re.search(r"\[[^\]]{3,80}\]", text):
        issues.append("Placeholder content detected: bracketed placeholder text")

    return list(dict.fromkeys(issues))

def validate_word_count(content, language_profile):
    issues = []

    quality_rules = language_profile.get("content_quality_rules", {})
    minimum_word_count = quality_rules.get("minimum_word_count", 800)

    text = re.sub(r"<[^>]+>", " ", content)
    words = re.findall(r"\b\w+\b", text, re.UNICODE)

    if len(words) < minimum_word_count:
        issues.append(f"Content too short: {len(words)} words. Minimum required: {minimum_word_count}")

    return issues


def detect_invalid_tags(content):
    issues = []

    if "<soft_contact>" in content:
        issues.append("Invalid custom tag detected: <soft_contact>")

    if "</br>" in content:
        issues.append("Invalid HTML tag detected: </br>")

    return issues


def is_responsible_limitation_context(content, match_start, match_end):
    """
    Decide whether a risky phrase appears inside a responsible limitation statement.

    This prevents Sofia from flagging statements such as:
    - "O teste não é infalível"
    - "Nenhum teste é 100% preciso"
    - "Não garantimos resultados"
    - "No test is 100% accurate"

    The goal is not to ignore risky language completely, but to avoid blocking
    responsible disclaimers that explain professional limits.
    """

    window_start = max(0, match_start - 90)
    window_end = min(len(content), match_end + 90)

    context = content[window_start:window_end].lower()

    negation_patterns = [
        # Portuguese
        "não é",
        "não são",
        "não deve",
        "não devem",
        "não pode",
        "não podem",
        "não substitui",
        "não garantimos",
        "não garante",
        "não garantem",
        "nunca deve",
        "nenhum teste",
        "nenhuma avaliação",
        "sem garantia",
        "não é possível garantir",

        # Spanish
        "no es",
        "no son",
        "no debe",
        "no deben",
        "no puede",
        "no pueden",
        "no sustituye",
        "no garantizamos",
        "no garantiza",
        "ningún test",
        "ninguna prueba",
        "sin garantía",

        # French
        "n’est pas",
        "ne sont pas",
        "ne doit pas",
        "ne doivent pas",
        "ne peut pas",
        "ne peuvent pas",
        "ne remplace pas",
        "ne garantit pas",
        "nous ne garantissons pas",
        "aucun test",
        "aucune évaluation",
        "sans garantie",

        # English
        "is not",
        "are not",
        "does not",
        "do not",
        "should not",
        "must not",
        "cannot",
        "can not",
        "does not replace",
        "do not guarantee",
        "not guaranteed",
        "no test",
        "no assessment",
        "without guarantee",
    ]

    limitation_words = [
        # Portuguese
        "limitação",
        "limitações",
        "qualificado e certificado",
        "qualificados e certificados",
        "treinado e certificado",
        "treinados e certificados",
        "profissional qualificado",
        "profissionais qualificados",
        "profissional certificado",
        "profissionais certificados",
        "profissional treinado",
        "profissionais treinados",
        "equipa qualificada",
        "equipe qualificada",
        "equipa certificada",
        "equipe certificada",
        "examinador certificado",
        "profissional certificado",
        "técnico certificado",
        "formação certificada",
        "certificação profissional",
        "não infalível",
        "não é infalível",
        "não são absolutos",
        "não é absoluto",
        "falsos positivos",
        "falsos negativos",
        "ferramenta complementar",
        "não substitui investigação",
        "não substitui aconselhamento jurídico",

        # Spanish
        "limitación",
        "limitaciones",
        "no es infalible",
        "falsos positivos",
        "falsos negativos",
        "certificación profesional",
        "examinador certificado",
        "herramienta complementaria",
        "no sustituye una investigación",

        # French
        "limitation",
        "limitations",
        "n’est pas infaillible",
        "faux positifs",
        "faux négatifs",
        "professionnel certifié",
        "examinateur certifié",
        "outil complémentaire",
        "ne remplace pas une enquête",

        # English
        "limitation",
        "limitations",
        "not infallible",
        "false positives",
        "false negatives",
        "certified examiner",
        "certified professional",
        "professional certification",
        "complementary tool",
        "does not replace an investigation",
    ]

    return any(pattern in context for pattern in negation_patterns + limitation_words)


def detect_risky_claims(content, language_profile):
    warnings = []

    risky_rules = language_profile.get("risky_phrase_rules", {})
    risky_patterns = risky_rules.get("forbidden_phrases", [])

    fallback_patterns = [
        "100%",
        "guaranteed",
        "guarantee",
        "certified",
        "legally accepted",
        "legally admissible",
        "infallible",
        "infalível",
        "infalible",
        "infaillible",
    ]

    checked_patterns = []

    for pattern in risky_patterns + fallback_patterns:
        normalized_pattern = str(pattern or "").strip()

        if not normalized_pattern:
            continue

        if normalized_pattern.lower() in checked_patterns:
            continue

        checked_patterns.append(normalized_pattern.lower())

        for match in re.finditer(re.escape(normalized_pattern), content, re.IGNORECASE):
            if is_responsible_limitation_context(content, match.start(), match.end()):
                continue

            warnings.append(
                f"Risky wording detected for examiner review: {normalized_pattern}"
            )
            break

    return warnings




def count_yoast_faq_questions(content: str) -> int:
    """
    Count questions inside a rendered Yoast FAQ block.
    """
    content = str(content or "")

    if "<!-- wp:yoast/faq-block" not in content:
        return 0

    return len(
        re.findall(
            "schema-faq-question",
            content,
            flags=re.IGNORECASE,
        )
    )


def validate_faq(content):
    issues = []

    # First, support Yoast FAQ blocks.
    yoast_count = count_yoast_faq_questions(content)

    if yoast_count:
        if yoast_count < 4:
            issues.append(
                f"FAQ has fewer than 4 questions ({yoast_count})"
            )
        return issues

    # Legacy H2/H3 FAQ detection
    faq_heading_patterns = [
        r"perguntas frequentes",
        r"frequentes perguntas",
        r"perguntas e respostas",
        r"faq",
        r"frequently asked questions",
        r"preguntas frecuentes",
        r"questions fréquentes"
    ]

    has_faq_heading = any(
        re.search(
            rf"<h2[^>]*>.*{pattern}.*</h2>",
            content,
            re.IGNORECASE
        )
        for pattern in faq_heading_patterns
    )

    if not has_faq_heading:
        issues.append("Missing FAQ <h2> section")

    faq_questions = re.findall(r"<h3", content, re.IGNORECASE)

    if len(faq_questions) < 4:
        issues.append("FAQ has fewer than 4 questions")

    return issues


def validate_structure(content):
    issues = []

    h1_count = count_tag(content, "h1")

    if h1_count != 1:
        issues.append(f"Invalid H1 count: {h1_count}")

    return issues


def get_content_from_draft(draft):
    return (
        draft.get("generated_content", {}).get("content", "")
        or draft.get("html_content")
        or draft.get("draft_content", {}).get("content", "")
    )



def detect_city_page_quality_warnings(content, draft=None):
    """
    Temporary compatibility fallback.

    Returns warning list only.
    Prevents validator crash when city-page warning detector
    is referenced but not defined before main() is called.
    """
    return []



def append_image_plan_validation(draft, warnings):
    """
    Phase 1 image validation:
    - Warn only.
    - Do not fail generated content because of image metadata issues.
    """
    image_plan = draft.get("image_plan") or {}

    try:
        image_validation = validate_image_plan(image_plan)
    except Exception as e:
        warnings.append(f"[IMAGE] Image plan validation could not run: {e}")
        draft["image_validation"] = {
            "valid": True,
            "warnings": [f"Image plan validation could not run: {e}"],
            "errors": []
        }
        return warnings

    draft["image_validation"] = image_validation

    for warning in image_validation.get("warnings", []):
        warnings.append(f"[IMAGE] {warning}")

    # Phase 1: image errors are reported as warnings, not hard failures.
    for error in image_validation.get("errors", []):
        warnings.append(f"[IMAGE-RISK] {error}")

    return warnings


def main():
    print("=== Sofia: Validate Generated Content ===\n")

    if len(sys.argv) == 2:
        workspace_id_arg = None
        draft_id = sys.argv[1]
    elif len(sys.argv) == 3:
        workspace_id_arg = sys.argv[1]
        draft_id = sys.argv[2]
    else:
        print("Usage:")
        print("python app/validate_generated_content.py DRAFT_ID")
        print("python app/validate_generated_content.py WORKSPACE_ID DRAFT_ID")
        return

    workspaces = load_json(WORKSPACES_PATH)

    if workspace_id_arg:
        workspace = find_workspace(workspaces, workspace_id_arg)

        if not workspace:
            print(f"Workspace not found: {workspace_id_arg}")
            sys.exit(1)

        try:
            workspace_id, draft_registry_file, draft_registry_data, draft = load_draft_registry_for_workspace_draft(
                workspace_id_arg,
                draft_id
            )
        except Exception as e:
            print(f"ERROR: {e}")
            return

        if not draft:
            print(f"Draft not found: {draft_id}")
            sys.exit(1)

    else:
        try:
            workspace_id, draft_registry_file, draft_registry_data, draft = load_draft_registry_for_draft(draft_id)
        except Exception as e:
            print(f"ERROR: {e}")
            return

        workspace = find_workspace(workspaces, workspace_id)

        if not workspace:
            print(f"Workspace not found for draft {draft_id}: {workspace_id}")
            sys.exit(1)

        if not draft:
            print(f"Draft not found: {draft_id}")
            sys.exit(1)

    content = get_content_from_draft(draft)

    if not content:
        print("No content found.")
        draft["validation"] = {
            "status": "failed",
            "issues": ["No content found"]
        }

        draft_registry_data["scope"] = "workspace"
        draft_registry_data["workspace_id"] = workspace_id
        save_json(draft_registry_file, draft_registry_data)

        sys.exit(1)

    language_profile = (
        load_language_profile_for_workspace(workspace)
        or load_language_profile_for_draft(draft)
    )

    issues = []
    warnings = []

    issues += validate_structure(content)
    issues += validate_faq(content)
    issues += detect_english_headings(content)
    issues += detect_invalid_tags(content)
    issues += detect_wrong_language_or_markup(content)
    issues += detect_placeholder_content(content, language_profile)
    issues += detect_workspace_language_contamination(
        content,
        workspace,
        draft,
        language_profile
    )
    issues += validate_word_count(content, language_profile)
    warnings += detect_risky_claims(content, language_profile)
    warnings += detect_pt_pt_localization_issues(content, workspace, draft)
    warnings += detect_workspace_content_quality_warnings(content, language_profile)
    warnings += detect_city_page_quality_warnings(
        content,
        draft
    )

    status = "passed" if not issues else "failed"

    draft["validation"] = {
        "status": status,
        "issues": issues,
        "warnings": warnings
    }

    draft_registry_data["scope"] = "workspace"
    draft_registry_data["workspace_id"] = workspace_id
    save_json(draft_registry_file, draft_registry_data)

    print(f"Validation status: {status}")
    print(f"Workspace registry: {draft_registry_file}")

    if issues:
        print("\nIssues found:")
        for issue in issues:
            print(f"- {issue}")

    if warnings:
        print("\nWarnings found:")
        for warning in warnings:
            print(f"- {warning}")

    if status != "passed":
        sys.exit(1)

if __name__ == "__main__":
    main()