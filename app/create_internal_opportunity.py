import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

from cannibalization_checker import check_workspace_cannibalization

try:
    from app.parse_examiner_request import parse_examiner_request
except Exception:
    from parse_examiner_request import parse_examiner_request

try:
    from app.examiner_intelligence import (
        build_examiner_intent_model,
        load_json as load_examiner_profile,
    )
except Exception:
    from examiner_intelligence import (
        build_examiner_intent_model,
        load_json as load_examiner_profile,
    )


SOFIA_ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = SOFIA_ROOT / "data" / "workspaces.json"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def today():
    return datetime.now().strftime("%Y-%m-%d")


def load_json(path, default=None):
    if not path.exists():
        return default if default is not None else {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def slugify(text):
    text = str(text or "").strip().lower()
    replacements = {
        "á": "a", "à": "a", "â": "a", "ã": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u",
        "ç": "c",
        "ñ": "n",
        "ü": "u",
    }

    for src, dst in replacements.items():
        text = text.replace(src, dst)

    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text or "internal-content-request"


def find_workspace(workspace_id):
    data = load_json(WORKSPACES_PATH, {"workspaces": []})
    for workspace in data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def normalize_language(language):
    language = str(language or "en").strip()

    if language.startswith("pt"):
        return "pt"
    if language.startswith("es"):
        return "es"
    if language.startswith("fr"):
        return "fr"
    if language.startswith("tr"):
        return "tr"
    if language.startswith("ru"):
        return "ru"
    return "en"


def infer_content_type(raw_request):
    text = str(raw_request or "").lower()

    if "landing page" in text or "página de aterrizaje" in text or "pagina de aterrizaje" in text:
        return "landing_page"

    if "service page" in text or "página de servicio" in text or "pagina de servicio" in text:
        return "service_page"

    if "blog" in text or "article" in text or "artículo" in text or "artigo" in text:
        return "blog_post"

    if "faq" in text:
        return "faq_page"

    return "landing_page"


def clean_topic(raw_request):
    text = str(raw_request or "").strip()

    # Remove common Sofia trigger prefixes.
    text = re.sub(r"^\s*sofia\s*[,:\-]?\s*", "", text, flags=re.IGNORECASE)

    # Remove common creation verbs.
    patterns = [
        r"^create\s+(a|an)?\s*",
        r"^prepare\s+(a|an)?\s*",
        r"^generate\s+(a|an)?\s*",
        r"^write\s+(a|an)?\s*",
        r"^make\s+(a|an)?\s*",

        # Portuguese
        r"^criar\s+(uma|um)?\s*",
        r"^cria\s+(uma|um)?\s*",
        r"^crie\s+(uma|um)?\s*",
        r"^preparar\s+(uma|um)?\s*",
        r"^prepara\s+(uma|um)?\s*",
        r"^prepare\s+(uma|um)?\s*",
        r"^gerar\s+(uma|um)?\s*",
        r"^gera\s+(uma|um)?\s*",
        r"^gere\s+(uma|um)?\s*",

        # Spanish
        r"^crear\s+(una|un)?\s*",
        r"^crea\s+(una|un)?\s*",
        r"^preparar\s+(una|un)?\s*",
        r"^prepara\s+(una|un)?\s*",
        r"^generar\s+(una|un)?\s*",
        r"^genera\s+(una|un)?\s*",

        # French
        r"^créer\s+(une|un)?\s*",
        r"^creer\s+(une|un)?\s*",
        r"^crée\s+(une|un)?\s*",
        r"^cree\s+(une|un)?\s*",
        r"^préparer\s+(une|un)?\s*",
        r"^preparer\s+(une|un)?\s*",
        r"^prépare\s+(une|un)?\s*",
        r"^prepare\s+(une|un)?\s*",
    ]

    for pattern in patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()

    # Remove content type words from the beginning.
    content_type_patterns = [
        r"^landing page\s+(about|for|on|sobre|para|de)?\s*",
        r"^service page\s+(about|for|on|sobre|para|de)?\s*",
        r"^blog post\s+(about|for|on|sobre|para|de)?\s*",
        r"^article\s+(about|for|on|sobre|para|de)?\s*",
        r"^content\s+(about|for|on|sobre|para|de)?\s*",
        r"^page\s+(about|for|on|sobre|para|de)?\s*",

        # Portuguese / Spanish / French page terms
        r"^página\s+(sobre|para|de|em|en)?\s*",
        r"^pagina\s+(sobre|para|de|em|en)?\s*",
        r"^artículo\s+(sobre|para|de|en)?\s*",
        r"^articulo\s+(sobre|para|de|en)?\s*",
        r"^artigo\s+(sobre|para|de|em)?\s*",
        r"^conteúdo\s+(sobre|para|de|em)?\s*",
        r"^conteudo\s+(sobre|para|de|em)?\s*",
        r"^contenido\s+(sobre|para|de|en)?\s*",
        r"^contenu\s+(sur|pour|de|en)?\s*",
        r"^page\s+(sur|pour|de|en)?\s*",
    ]

    for pattern in content_type_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()

    text = text.strip(" .,:;-")
    return text or raw_request.strip()


def get_opportunity_prefix(workspace):
    workspace_id = workspace.get("workspace_id", "local.xx")
    market_code = workspace.get("market_code", "")

    if workspace_id.startswith("local.") and market_code:
        return f"OPP-{market_code.upper()}"

    safe = re.sub(r"[^A-Za-z0-9]+", "-", workspace_id).strip("-").upper()
    return f"OPP-{safe}"


def next_opportunity_id(opportunities, workspace):
    prefix = get_opportunity_prefix(workspace)
    max_number = 0

    for opportunity in opportunities:
        opp_id = opportunity.get("id") or opportunity.get("opportunity_id") or ""
        if not opp_id.startswith(prefix + "-"):
            continue

        suffix = opp_id.replace(prefix + "-", "", 1)
        if suffix.isdigit():
            max_number = max(max_number, int(suffix))

    return f"{prefix}-{max_number + 1:03d}"


def simple_cannibalization_check(topic, workspace):
    result = check_workspace_cannibalization(
        workspace=workspace,
        topic=topic,
        extra_terms=[]
    )

    if result.get("result") == "strong_overlap":
        status = "strong_overlap"
    elif result.get("result") == "possible_overlap":
        status = "possible_conflict"
    else:
        status = "clear"

    notes = result.get("notes", "")

    matches = result.get("matches", [])
    if matches:
        top = matches[0]
        notes += (
            f" Top match: {top.get('label')} "
            f"({top.get('source_file')}, score={top.get('score')})."
        )

    return {
        "status": status,
        "notes": notes,
        "details": result
    }


def build_seo_brief(topic, workspace, content_type):
    country = workspace.get("country", "")
    language = normalize_language(workspace.get("language", "en"))
    slug = slugify(topic)

    if language == "es":
        seo_title = f"{topic} en {country}" if country and country != "Global" else topic
        meta = f"Información profesional sobre {topic}, sus aplicaciones, límites y cómo solicitar una evaluación confidencial."
        h2 = [
            "Cuándo puede ser útil este servicio",
            "Cómo funciona el proceso",
            "Limitaciones y consideraciones importantes",
            "Cómo solicitar una evaluación"
        ]
    elif language == "pt":
        seo_title = f"{topic} em {country}" if country and country != "Global" else topic
        meta = f"Informação profissional sobre {topic}, aplicações, limitações e como solicitar uma avaliação confidencial."
        h2 = [
            "Quando este serviço pode ser útil",
            "Como funciona o processo",
            "Limitações e cuidados importantes",
            "Como solicitar uma avaliação"
        ]
    elif language == "fr":
        seo_title = f"{topic} en {country}" if country and country != "Global" else topic
        meta = f"Informations professionnelles sur {topic}, ses applications, ses limites et la demande d’une évaluation confidentielle."
        h2 = [
            "Quand ce service peut être utile",
            "Comment fonctionne le processus",
            "Limites et considérations importantes",
            "Comment demander une évaluation"
        ]
    else:
        seo_title = f"{topic} in {country}" if country and country != "Global" else topic
        meta = f"Professional information about {topic}, its applications, limitations, and how to request a confidential assessment."
        h2 = [
            "When this service may be useful",
            "How the process works",
            "Important limitations and ethical considerations",
            "How to request an assessment"
        ]

    image_country = slugify(country) if country and country != "Global" else "global"

    return {
        "focus_keyphrase": topic,
        "seo_title": seo_title[:70],
        "slug": slug,
        "meta_description": meta[:155],
        "suggested_headings": {
            "h1": topic,
            "h2": h2
        },
        "image_alt_text": seo_title,
        "image_filename": f"{slug}-{image_country}.jpg"
    }


def build_strategy_brief(topic, content_type):
    if content_type in ["landing_page", "service_page"]:
        return {
            "content_goal": "Generate qualified leads by explaining the service clearly and professionally.",
            "target_audience": "Potential clients looking for professional polygraph or forensic services.",
            "recommended_angle": "Explain the service in practical terms without exaggerating what the polygraph can do.",
            "required_sections": [
                "What this service is",
                "When this service may be useful",
                "How the process works",
                "Important limitations and ethical considerations",
                "How to request an appointment"
            ],
            "warnings": [
                "Avoid legal guarantees.",
                "Avoid absolute accuracy claims.",
                "Avoid unverified local law claims."
            ],
            "conversion_goal": "Encourage the visitor to contact the examiner for a confidential consultation.",
            "internal_linking_notes": [
                "Link to the main service page where relevant.",
                "Link to related FAQ or educational content if available.",
                "Avoid linking to pages with the same primary keyword to prevent cannibalization."
            ],
            "source_topic": topic
        }

    return {
        "content_goal": "Build trust and answer a useful question before the visitor contacts the service.",
        "target_audience": "People researching polygraph or forensic services.",
        "recommended_angle": "Explain the topic in simple, accurate language without exaggerating what the polygraph can do.",
        "required_sections": [
            "Short answer to the main question",
            "Explanation of the concept",
            "Practical examples",
            "Limitations and ethical considerations",
            "When to contact a professional examiner"
        ],
        "warnings": [
            "Avoid legal guarantees.",
            "Avoid absolute accuracy claims.",
            "Avoid unverified local law claims."
        ],
        "conversion_goal": "Move the reader from general information to contacting a professional examiner.",
        "internal_linking_notes": [
            "Link to the main service page where relevant.",
            "Link to related FAQ or educational content if available.",
            "Avoid linking to pages with the same primary keyword to prevent cannibalization."
        ],
        "source_topic": topic
    }




def build_opportunity_validation_report(
    *,
    parsed_request,
    examiner_intent_model,
    blueprint_decision,
    sensitivity,
    cannibalization,
):
    """
    Validate the internally created opportunity before it enters examiner review.

    This is advisory metadata only.
    It does not block opportunity creation.
    """

    warnings = []
    checks = {}

    checks["examiner_intent_confidence"] = examiner_intent_model.get("confidence", "")
    checks["needs_clarification"] = bool(examiner_intent_model.get("needs_clarification", False))
    checks["page_type"] = blueprint_decision.get("page_type", "")
    checks["blueprint_id"] = blueprint_decision.get("blueprint_id", "")
    checks["intent_type"] = blueprint_decision.get("intent_type", "")
    checks["blueprint_decision_source"] = blueprint_decision.get("decision_source", "")
    checks["cannibalization_status"] = cannibalization.get("status", "")
    checks["sensitivity"] = sensitivity

    if examiner_intent_model.get("needs_clarification"):
        warnings.append("examiner_intent_needs_clarification")

    if examiner_intent_model.get("confidence") == "low":
        warnings.append("low_examiner_intent_confidence")

    if not blueprint_decision.get("page_type"):
        warnings.append("missing_page_type")

    if not blueprint_decision.get("blueprint_id"):
        warnings.append("missing_blueprint_id")

    if cannibalization.get("status") in ("strong_overlap", "possible_conflict"):
        warnings.append("possible_cannibalization_issue")

    if sensitivity in ("high", "manual_review"):
        warnings.append("sensitive_topic_requires_manual_review")

    parser_type = parsed_request.get("page_type") or parsed_request.get("recommended_content_type") or ""
    intent_type = examiner_intent_model.get("recommended_page_type") or ""

    if parser_type and intent_type and parser_type != intent_type:
        warnings.append("parser_and_examiner_intent_page_type_differ")

    passed_basic_checks = not any(
        warning in warnings
        for warning in [
            "low_examiner_intent_confidence",
            "missing_page_type",
            "missing_blueprint_id",
        ]
    )

    return {
        "version": "1.0",
        "source": "internal_opportunity_validation_v1",
        "passed_basic_checks": passed_basic_checks,
        "warnings": warnings,
        "checks": checks,
    }



def build_blueprint_decision(parsed_request, examiner_intent_model, raw_request):
    """
    Decide page_type and blueprint_id from examiner intent, with parser values
    used only when they are explicit and useful.

    This keeps the examiner intent model as the main strategic source.
    """

    parser_content_type = parsed_request.get("recommended_content_type") or ""
    parser_page_type = parsed_request.get("page_type") or ""
    parser_blueprint_id = parsed_request.get("blueprint_id") or ""

    intent_page_type = examiner_intent_model.get("recommended_page_type") or ""
    intent_blueprint = examiner_intent_model.get("recommended_blueprint") or ""
    intent_seo = examiner_intent_model.get("seo_intent") or ""

    fallback_type = infer_content_type(raw_request)

    # If examiner intent recommends a non-default authority/FAQ/etc. page,
    # prefer that over generic parser landing_page defaults.
    if intent_page_type and intent_page_type != "landing_page":
        content_type = intent_page_type
        page_type = intent_page_type
        blueprint_id = intent_blueprint or intent_page_type
        source = "examiner_intent_non_default"
    else:
        content_type = (
            parser_content_type
            or parser_page_type
            or intent_page_type
            or fallback_type
        )
        page_type = (
            parser_page_type
            or intent_page_type
            or content_type
        )
        blueprint_id = (
            parser_blueprint_id
            or intent_blueprint
            or page_type
        )
        source = "parser_with_examiner_intent_fallback"

    parser_intent_type = parsed_request.get("intent_type")

    if parser_intent_type in ("", None, "informational") and intent_seo:
        intent_type = intent_seo
        intent_source = "examiner_intent"
    else:
        intent_type = (
            parser_intent_type
            or intent_seo
            or ("transactional" if content_type in ["landing_page", "service_page"] else "informational")
        )
        intent_source = "parser_or_fallback"

    return {
        "content_type": content_type,
        "page_type": page_type,
        "blueprint_id": blueprint_id,
        "intent_type": intent_type,
        "decision_source": source,
        "intent_source": intent_source,
        "parser_content_type": parser_content_type,
        "parser_page_type": parser_page_type,
        "parser_blueprint_id": parser_blueprint_id,
        "intent_page_type": intent_page_type,
        "intent_blueprint": intent_blueprint,
        "intent_seo": intent_seo,
    }



def create_internal_opportunity(workspace_id, raw_request, requested_by=None, telegram_chat_id=None, telegram_message_id=None):
    workspace = find_workspace(workspace_id)

    if not workspace:
        raise RuntimeError(f"Workspace not found: {workspace_id}")

    folder_path = workspace.get("folder_path")
    if not folder_path:
        raise RuntimeError(f"Workspace has no folder_path: {workspace_id}")

    opportunities_path = SOFIA_ROOT / folder_path / "external_opportunities.json"

    data = load_json(
        opportunities_path,
        {
            "version": "1.0",
            "workspace_id": workspace_id,
            "opportunities": []
        }
    )

    if "version" not in data:
        data["version"] = "1.0"

    data["workspace_id"] = workspace_id

    if "opportunities" not in data:
        data["opportunities"] = []

    opportunities = data["opportunities"]

    parsed_request = parse_examiner_request(
        workspace_id=workspace_id,
        raw_text=raw_request,
        use_ai=True
    )

    if not parsed_request.get("requires_opportunity", True):
        command_type = parsed_request.get("command_type", "unknown")
        routing_target = parsed_request.get("routing_target", "unknown")
        raise RuntimeError(
            "Parsed examiner request is not a content opportunity. "
            f"command_type={command_type}, routing_target={routing_target}. "
            "Route this request through the Sofia coordinator instead."
        )

    topic = (
        parsed_request.get("human_title")
        or parsed_request.get("title")
        or parsed_request.get("clean_request")
        or clean_topic(raw_request)
    ).strip()

    target_keyword = (
        parsed_request.get("short_target_keyword")
        or parsed_request.get("target_keyword")
        or topic
    ).strip()

    language = normalize_language(workspace.get("language", "en"))

    examiner_profile_path = (
        SOFIA_ROOT
        / folder_path
        / "examiner_intelligence_profile.json"
    )

    examiner_profile = load_examiner_profile(
        examiner_profile_path
    )

    examiner_intent_model = build_examiner_intent_model(
        raw_request,
        profile=examiner_profile,
        workspace_context={
            "workspace_id": workspace_id,
            "language": language,
            "country": workspace.get("country"),
        },
    )

    blueprint_decision = build_blueprint_decision(
        parsed_request,
        examiner_intent_model,
        raw_request,
    )

    content_type = blueprint_decision.get("content_type")
    page_type = blueprint_decision.get("page_type")
    blueprint_id = blueprint_decision.get("blueprint_id")
    intent_type = blueprint_decision.get("intent_type")

    sensitivity = parsed_request.get("sensitivity", "normal")
    requires_manual_review = bool(parsed_request.get("requires_manual_review", sensitivity != "normal"))

    opportunity_id = next_opportunity_id(opportunities, workspace)
    language = normalize_language(workspace.get("language", "en"))

    country = workspace.get("market_code") or workspace.get("country") or ""
    cannibalization = simple_cannibalization_check(target_keyword, workspace)
    opportunity_validation = build_opportunity_validation_report(
        parsed_request=parsed_request,
        examiner_intent_model=examiner_intent_model,
        blueprint_decision=blueprint_decision,
        sensitivity=sensitivity,
        cannibalization=cannibalization,
    )

    seo_brief = build_seo_brief(target_keyword, workspace, content_type)

    # Override deterministic SEO fields with parser-clean fields.
    clean_slug = (
        parsed_request.get("short_slug")
        or parsed_request.get("suggested_slug")
        or slugify(target_keyword)
    )
    seo_brief["focus_keyphrase"] = target_keyword
    seo_brief["page_title"] = parsed_request.get("human_title") or topic
    seo_title_source = parsed_request.get("seo_title") or parsed_request.get("human_title") or topic
    seo_brief["seo_title"] = (
        f"{seo_title_source} | Polígrafo España" if language == "es" else seo_title_source
    )[:70].rstrip(" -|,.;:")
    seo_brief["slug"] = clean_slug
    seo_brief["meta_description"] = (
        f"{target_keyword}. Información profesional sobre el uso responsable, "
        f"límites y contexto de la evaluación poligráfica en España."
        if language == "es"
        else seo_brief.get("meta_description", "")
    )[:155]
    seo_brief.setdefault("suggested_headings", {})
    seo_brief["suggested_headings"]["h1"] = parsed_request.get("human_title") or topic
    seo_brief["image_alt_text"] = parsed_request.get("image_topic") or topic
    seo_brief["image_filename"] = f"{clean_slug}.jpg"

    strategy_brief = build_strategy_brief(topic, content_type)

    if sensitivity in ["high", "manual_review"]:
        strategy_brief.setdefault("warnings", [])
        strategy_brief["warnings"].extend([
            "Sensitive topic: avoid predicting future behaviour, dangerousness, recidivism, or rehabilitation success.",
            "Frame the polygraph only as a complementary tool for specific, reviewable questions.",
            "Emphasize consent, professional limits, confidentiality, and examiner review."
        ])
        strategy_brief["sensitivity"] = sensitivity
        strategy_brief["requires_manual_review"] = True

    opportunity = {
        "id": opportunity_id,
        "created_at": today(),
        "updated_at": now_iso(),
        "country": str(country).upper() if len(str(country)) <= 3 else country,
        "language": language,
        "source": "telegram_group",
        "source_type": "internal_trigger",
        "source_signal_id": "",
        "topic": topic,
        "raw_request": raw_request,
        "requested_by": requested_by or "",
        "telegram_chat_id": str(telegram_chat_id or ""),
        "telegram_message_id": str(telegram_message_id or ""),
        "opportunity_type": "examiner_requested_topic",
        "recommended_content_type": content_type,
        "page_type": page_type,
        "blueprint_id": blueprint_id,
        "intent_type": intent_type,
        "target_keyword": target_keyword,
        "suggested_slug": seo_brief.get("slug", ""),
        "sensitivity": sensitivity,
        "requires_manual_review": requires_manual_review,
        "parsed_request": parsed_request,
        "examiner_intent_model": examiner_intent_model,
        "blueprint_decision": blueprint_decision,
        "opportunity_validation": opportunity_validation,
        "priority": "high",
        "confidence": 0.95,
        "status": "validated",
        "related_keywords": list(dict.fromkeys([
            target_keyword,
            topic
        ])),
        "detected_concepts": list(dict.fromkeys([
            "examiner_originated_content_request",
            examiner_intent_model.get("business_domain", ""),
            examiner_intent_model.get("intent_id", ""),
            examiner_intent_model.get("issue_id", ""),
            examiner_intent_model.get("investigation_type", ""),
            examiner_intent_model.get("visitor_profile", ""),
        ])),
        "business_reason": (
            "Created from an examiner-originated Telegram request inside the workspace group. "
            f"Examiner intent: {examiner_intent_model.get('client_problem', '')}. "
            f"Visitor profile: {examiner_intent_model.get('visitor_profile', '')}."
        ),
        "risk_notes": [
            "Manual examiner review required before draft generation.",
            "Confirm local legal and ethical considerations before publication."
        ],
        "recommended_action": "send_to_examiner_for_validation",
        "cannibalization_status": cannibalization["status"],
        "local_topic_status": "allowed",
        "review_status": "pending_examiner",
        "cannibalization_notes": cannibalization["notes"],
        "cannibalization_details": cannibalization.get("details", {}),
        "local_topic_notes": (
            "Internal examiner request parsed by Sofia examiner request parser. "
            f"Sensitivity: {sensitivity}. "
            f"Examiner intent confidence: {examiner_intent_model.get('confidence', '')}."
        ),
        "language_mismatch": False,
        "language_notes": "Language taken from workspace configuration.",
        "geo_relevance": "workspace_specific",
        "geo_notes": "Created inside a mapped Telegram workspace group.",
        "validated_at": now_iso(),
        "seo_brief": seo_brief,
        "content_strategy_brief": strategy_brief,
        "telegram_notified": False,
        "internal_trigger": {
            "created_from": "telegram_group_message",
            "workspace_id": workspace_id,
            "raw_request": raw_request,
            "parsed_request": parsed_request,
            "examiner_intent_model": examiner_intent_model,
            "requested_by": requested_by or "",
            "telegram_chat_id": str(telegram_chat_id or ""),
            "telegram_message_id": str(telegram_message_id or ""),
            "created_at": now_iso()
        }
    }

    opportunities.append(opportunity)
    save_json(opportunities_path, data)

    return opportunity, opportunities_path


def main():
    print("=== Sofia: Create Internal Opportunity ===\n")

    if len(sys.argv) < 3:
        print("Usage:")
        print('python app/create_internal_opportunity.py WORKSPACE_ID "Sofia, create a landing page about corporate theft polygraph testing"')
        return

    workspace_id = sys.argv[1]
    raw_request = " ".join(sys.argv[2:]).strip()

    opportunity, path = create_internal_opportunity(
        workspace_id=workspace_id,
        raw_request=raw_request
    )

    print("Internal opportunity created successfully.")
    print(f"Workspace: {workspace_id}")
    print(f"Opportunity: {opportunity.get('id')}")
    print(f"Topic: {opportunity.get('topic')}")
    print(f"Content type: {opportunity.get('recommended_content_type')}")
    print(f"Cannibalization: {opportunity.get('cannibalization_status')}")
    print(f"Saved to: {path}")


if __name__ == "__main__":
    main()