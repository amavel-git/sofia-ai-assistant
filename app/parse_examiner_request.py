#!/usr/bin/env python3
"""
Sofia Examiner Request Parser

Purpose:
- Convert natural examiner Telegram messages into structured content requests.
- Keep telegram_listener.py lightweight.
- Use qwen2.5:7b when available.
- Fall back to deterministic parsing if Ollama fails.

Example:
  Sofía, crea una página sobre el uso del polígrafo en libertad condicional

Output:
  clean title/topic/keyword/slug/page_type/sensitivity
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path
from typing import Any, Dict
from datetime import datetime, timezone


SOFIA_ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = SOFIA_ROOT / "data" / "workspaces.json"
EXAMINER_REQUEST_INTELLIGENCE_PATH = SOFIA_ROOT / "data" / "examiner_request_intelligence.json"

DEFAULT_MODEL = os.getenv("SOFIA_EXAMINER_PARSER_MODEL", "qwen2.5:7b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


ALLOWED_PAGE_TYPES = {
    "landing_page",
    "service_page",
    "city_page",
    "pillar_page",
    "authority_page",
    "educational_page",
    "blog_post",
    "faq_page",
}

ALLOWED_INTENTS = {
    "transactional",
    "commercial",
    "informational",
    "mixed",
    "local_transactional",
}

ALLOWED_SENSITIVITY = {
    "normal",
    "manual_review",
    "high",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_examiner_request_intelligence() -> Dict[str, Any]:
    return load_json(
        EXAMINER_REQUEST_INTELLIGENCE_PATH,
        {
            "version": "fallback",
            "sensitivity_terms": {},
            "page_type_terms": {},
            "city_terms": {}
        }
    )


def language_terms(section: Dict[str, Any], language: str) -> list[str]:
    language = normalize_language(language)
    terms = []
    terms.extend(section.get(language, []) or [])

    # PT variants currently use the generic pt bucket.
    if language.startswith("pt"):
        terms.extend(section.get("pt", []) or [])

    # English terms are useful as fallback because examiners may mix languages.
    if language != "en":
        terms.extend(section.get("en", []) or [])

    return list(dict.fromkeys([str(t).strip() for t in terms if str(t).strip()]))


def contains_any_term(text: str, terms: list[str]) -> bool:
    normalized_text = strip_accents(text).lower()
    for term in terms:
        normalized_term = strip_accents(term).lower()
        if normalized_term and normalized_term in normalized_text:
            return True
    return False


def find_workspace(workspace_id: str) -> Dict[str, Any]:
    data = load_json(WORKSPACES_PATH, {"workspaces": []})
    for workspace in data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return {}


def normalize_language(language: str) -> str:
    language = str(language or "en").strip().lower()
    if language.startswith("pt"):
        return "pt"
    if language.startswith("es"):
        return "es"
    if language.startswith("fr"):
        return "fr"
    if language.startswith("en"):
        return "en"
    return language[:2] if language else "en"


def strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def slugify(text: str) -> str:
    text = strip_accents(str(text or "").strip().lower())
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "examiner-request"


def clean_command_text(raw_text: str) -> str:
    original = str(raw_text or "").strip()
    text = original

    # Normalize only for matching; keep original accents in final clean text.
    normalized = strip_accents(text).lower()

    # Remove initial Sofia mention, with or without accent.
    if re.match(r"^\s*sofia\b", normalized):
        text = re.sub(
            r"^\s*sof[ií]a\s*[,:\-–—]?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

    # Remove common command phrases in EN/ES/PT/FR.
    command_patterns = [
        # Spanish
        r"^(por favor\s+)?(crea|crear|haz|hazme|prepara|preparar|genera|generar|escribe|redacta)\s+",
        r"^(una|un)\s+",
        r"^(p[aá]gina|pagina|landing|art[ií]culo|articulo|contenido|post)\s+",
        r"^(sobre|acerca de|para|de)\s+",

        # Portuguese
        r"^(por favor\s+)?(cria|criar|faz|faz-me|prepara|preparar|gera|gerar|escreve|redige)\s+",
        r"^(uma|um)\s+",
        r"^(p[aá]gina|pagina|artigo|conte[uú]do|conteudo|post)\s+",
        r"^(sobre|acerca de|para|de|em)\s+",

        # English
        r"^(please\s+)?(create|make|write|prepare|generate|draft)\s+",
        r"^(a|an)\s+",
        r"^(page|landing page|article|blog post|content|post)\s+",
        r"^(about|on|for)\s+",

        # French
        r"^(s'il te pla[iî]t\s+|svp\s+)?(cr[eé]e|cr[eé]er|fais|pr[eé]pare|pr[eé]parer|g[eé]n[eè]re|g[eé]n[eé]rer|r[eé]dige)\s+",
        r"^(une|un)\s+",
        r"^(page|article|contenu|post)\s+",
        r"^(sur|pour|de|concernant)\s+",
    ]

    changed = True
    while changed:
        changed = False
        for pattern in command_patterns:
            new_text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
            if new_text != text:
                text = new_text
                changed = True

    text = re.sub(r"\s+", " ", text).strip(" .,:;–—-")
    return text or original


def infer_page_type(clean_text: str, language: str = "en") -> str:
    intelligence = load_examiner_request_intelligence()
    page_type_terms = intelligence.get("page_type_terms", {}) or {}
    city_terms = intelligence.get("city_terms", {}) or {}

    if contains_any_term(clean_text, language_terms(city_terms, language)):
        return "city_page"

    if contains_any_term(clean_text, language_terms(page_type_terms.get("pricing_page", {}), language)):
        return "pricing_page"

    if contains_any_term(clean_text, language_terms(page_type_terms.get("educational_page", {}), language)):
        return "educational_page"

    if contains_any_term(clean_text, language_terms(page_type_terms.get("authority_page", {}), language)):
        return "authority_page"

    normalized = strip_accents(clean_text).lower()
    if any(word in normalized for word in ["guia", "guide", "pillar", "hub", "completa", "complete", "principal"]):
        return "pillar_page"

    return "landing_page"


def infer_sensitivity(clean_text: str, language: str = "en") -> str:
    intelligence = load_examiner_request_intelligence()
    sensitivity_terms = intelligence.get("sensitivity_terms", {}) or {}

    if contains_any_term(clean_text, language_terms(sensitivity_terms, language)):
        return "high"

    return "normal"


def infer_intent(page_type: str) -> str:
    if page_type == "city_page":
        return "local_transactional"
    if page_type in {"authority_page", "educational_page", "blog_post", "faq_page"}:
        return "informational"
    if page_type == "pillar_page":
        return "mixed"
    return "transactional"


def shorten_keyword(text: str, language: str = "es", country: str = "") -> str:
    normalized = strip_accents(text).lower()

    if "libertad condicional" in normalized or "reinsercion" in normalized:
        return "polígrafo libertad condicional España" if language == "es" else "polygraph probation"

    if "violencia domestica" in normalized:
        return "polígrafo violencia doméstica España" if language == "es" else "polygraph domestic violence"

    words = [w for w in re.split(r"\s+", str(text or "").lower()) if len(w) > 3]
    keyword = " ".join(words[:7]).strip()

    if language == "es" and country.lower() == "spain" and "españa" not in keyword:
        keyword = f"{keyword} España"

    return keyword.strip()


def build_image_topic(text: str, language: str = "es") -> str:
    normalized = strip_accents(text).lower()

    if "libertad condicional" in normalized or "reinsercion" in normalized:
        return "consulta profesional y revisión documental en contexto de supervisión"

    if "violencia" in normalized:
        return "revisión profesional de información sensible y preguntas específicas"

    if language == "es":
        return "consulta profesional y revisión de preguntas"
    if language == "pt":
        return "consulta profissional e revisão de perguntas"
    if language == "fr":
        return "consultation professionnelle et révision des questions"

    return "professional consultation and question review"


def infer_command_type(raw_text: str, clean_text: str, language: str = "en") -> str:
    intelligence = load_examiner_request_intelligence()
    aliases = intelligence.get("command_aliases", {}) or {}

    combined = f"{raw_text} {clean_text}"

    # Check more specific operational commands first.
    priority = [
        "show_failed_jobs",
        "show_active_workspaces",
        "diagnose_workspace",
        "add_competitor",
        "show_jobs",
        "create_content",
    ]

    for command_type in priority:
        terms = language_terms(aliases.get(command_type, {}), language)
        if contains_any_term(combined, terms):
            return command_type

    # If the cleaned request is substantial and Sofia was addressed, assume content creation.
    if re.search(r"\bsof[ií]a\b", raw_text, flags=re.I) and len(clean_text.split()) >= 4:
        return "create_content"

    return "unknown"


def command_confidence(command_type: str, ai_confidence: float = 0.70) -> float:
    if command_type == "unknown":
        return 0.25
    if command_type == "create_content":
        return max(ai_confidence, 0.70)
    return max(ai_confidence, 0.80)


def command_routing(command_type: str) -> dict:
    if command_type == "create_content":
        return {
            "is_content_request": True,
            "requires_opportunity": True,
            "routing_target": "content_opportunity"
        }

    if command_type == "add_competitor":
        return {
            "is_content_request": False,
            "requires_opportunity": False,
            "routing_target": "market_intelligence"
        }

    if command_type in {"show_jobs", "show_failed_jobs"}:
        return {
            "is_content_request": False,
            "requires_opportunity": False,
            "routing_target": "job_status"
        }

    if command_type == "show_active_workspaces":
        return {
            "is_content_request": False,
            "requires_opportunity": False,
            "routing_target": "workspace_status"
        }

    if command_type == "diagnose_workspace":
        return {
            "is_content_request": False,
            "requires_opportunity": False,
            "routing_target": "admin_diagnostics"
        }

    return {
        "is_content_request": False,
        "requires_opportunity": False,
        "routing_target": "unknown"
    }


def deterministic_parse(workspace_id: str, raw_text: str) -> Dict[str, Any]:
    workspace = find_workspace(workspace_id)
    language = normalize_language(workspace.get("language", "es"))
    country = workspace.get("country", "")
    clean = clean_command_text(raw_text)
    command_type = infer_command_type(raw_text, clean, language=language)
    routing = command_routing(command_type)
    page_type = infer_page_type(clean, language=language)
    sensitivity = infer_sensitivity(clean, language=language)
    intent = infer_intent(page_type)

    # Keep title human-friendly but not too long.
    title = clean[0].upper() + clean[1:] if clean else "Solicitud de contenido"
    if len(title) > 120:
        title = title[:117].rstrip() + "..."

    keyword = clean.lower()
    keyword = re.sub(r"\b(el|la|los|las|un|una|sobre|para|con|como|herramienta|complementaria)\b", "", keyword, flags=re.I)
    keyword = re.sub(r"\s+", " ", keyword).strip()
    if language == "es" and "polígrafo" in clean.lower() and "españa" not in clean.lower() and country.lower() == "spain":
        keyword = f"{keyword} España".strip()

    slug = slugify(keyword or clean)

    return {
        "parser_version": "deterministic_v1",
        "parser_model": "",
        "ai_used": False,
        "confidence": 0.70,
        "intent": command_type,
        "command_type": command_type,
        "is_content_request": routing["is_content_request"],
        "requires_opportunity": routing["requires_opportunity"],
        "routing_target": routing["routing_target"],
        "language": language,
        "country": country,
        "raw_request": raw_text,
        "clean_request": clean,
        "title": title,
        "topic": clean,
        "target_keyword": keyword or clean,
        "suggested_slug": slug,
        "page_type": page_type,
        "recommended_content_type": page_type,
        "intent_type": intent,
        "sensitivity": sensitivity,
        "requires_manual_review": sensitivity != "normal",
        "detected_concepts": ["examiner_originated_content_request"],
        "quality_warnings": [
            "Parsed with deterministic fallback. Review SEO fields before publication."
        ],
        "notes": [],
        "human_title": title,
        "seo_title": title,
        "page_topic": clean,
        "image_topic": build_image_topic(clean, language=language),
        "short_target_keyword": shorten_keyword(clean, language=language, country=country),
        "short_slug": slugify(shorten_keyword(clean, language=language, country=country)),
        "created_at": now_iso(),
    }


def extract_json_object(text: str) -> Dict[str, Any]:
    text = str(text or "").strip()

    # Remove markdown fences if the model ignores instructions.
    text = re.sub(r"^```(?:json)?", "", text, flags=re.I).strip()
    text = re.sub(r"```$", "", text).strip()

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response.")

    return json.loads(text[start:end + 1])


def call_ollama(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 45) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "top_p": 0.8,
            "num_ctx": 4096,
        },
    }

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))

    return data.get("response", "")


def build_ai_prompt(workspace_id: str, raw_text: str, fallback: Dict[str, Any]) -> str:
    workspace = find_workspace(workspace_id)
    language = normalize_language(workspace.get("language", fallback.get("language", "es")))
    country = workspace.get("country", "")

    return f"""
You are Sofia's examiner request parser.

Return ONLY valid JSON. No markdown. No explanation.

Workspace:
- workspace_id: {workspace_id}
- country: {country}
- language: {language}

Raw examiner message:
{raw_text}

Task:
Extract the actual content request. Remove command words such as:
"Sofia", "Sofía", "crea", "hazme", "prepara", "create", "write", "make", "cria", "faz", "crée".

Never include "Sofia", "Sofía", "crea una página", "hazme una página", or similar command words in title, topic, keyword, slug, image topic, or SEO fields.

Return this exact JSON schema:
{{
  "intent": "create_content|add_competitor|show_jobs|show_failed_jobs|diagnose_workspace|show_active_workspaces|analyze_market|compare_workspaces|help|unknown",
  "command_type": "create_content|add_competitor|show_jobs|show_failed_jobs|diagnose_workspace|show_active_workspaces|analyze_market|compare_workspaces|help|unknown",
  "is_content_request": true,
  "requires_opportunity": true,
  "routing_target": "content_opportunity|market_intelligence|job_status|workspace_status|admin_diagnostics|unknown",
  "language": "{language}",
  "clean_request": "...",
  "title": "...",
  "topic": "...",
  "target_keyword": "...",
  "short_target_keyword": "...",
  "suggested_slug": "...",
  "short_slug": "...",
  "human_title": "...",
  "seo_title": "...",
  "page_topic": "...",
  "image_topic": "...",
  "page_type": "landing_page|service_page|city_page|pillar_page|authority_page|educational_page|blog_post|faq_page",
  "recommended_content_type": "landing_page|service_page|city_page|pillar_page|authority_page|educational_page|blog_post|faq_page",
  "intent_type": "transactional|commercial|informational|mixed|local_transactional",
  "sensitivity": "normal|manual_review|high",
  "requires_manual_review": true,
  "confidence": 0.0,
  "detected_concepts": [],
  "quality_warnings": [],
  "notes": []
}}

Rules:
- command_type must describe what the examiner wants Sofia to do.
- If the examiner asks for a page, article, content, landing page, or post, command_type must be "create_content".
- If the examiner asks for status, jobs, failures, active workspaces, diagnostics, competitors, or market analysis, choose the corresponding command_type.
- Use the workspace language for title and keyword.
- For Spain, prefer "España" in Spanish text, never "Spain".
- If the topic involves violence, minors, legal supervision, offenders, therapy, treatment, probation, courts, or reintegration, set sensitivity to "high" and page_type to "authority_page" unless the user clearly asked for another type.
- Do not claim that polygraph predicts future violence, dangerousness, or rehabilitation success.
- target_keyword must be SEO-friendly and short, usually 3 to 7 words.
- short_target_keyword must be even cleaner and suitable for Yoast focus keyphrase.
- suggested_slug must be lowercase ASCII with hyphens.
- short_slug must be shorter than suggested_slug and suitable for WordPress.
- title must be clean and publishable, not a Telegram command.
- image_topic must describe a safe professional visual scene, not the legal/sensitive accusation itself.
- confidence should be between 0 and 1.

Fallback guess if unsure:
{json.dumps(fallback, ensure_ascii=False)}
""".strip()


def merge_and_validate(ai_data: Dict[str, Any], fallback: Dict[str, Any], model: str) -> Dict[str, Any]:
    data = dict(fallback)

    for key, value in ai_data.items():
        if value not in [None, "", [], {}]:
            data[key] = value

    data["parser_version"] = "ai_qwen_v1"
    data["parser_model"] = model
    data["ai_used"] = True
    data["raw_request"] = fallback.get("raw_request", "")

    data["command_type"] = (
        data.get("command_type")
        or data.get("intent")
        or fallback.get("command_type")
        or "unknown"
    )

    allowed_commands = {
        "create_content",
        "add_competitor",
        "show_jobs",
        "show_failed_jobs",
        "diagnose_workspace",
        "show_active_workspaces",
        "analyze_market",
        "compare_workspaces",
        "help",
        "unknown",
    }

    if data["command_type"] not in allowed_commands:
        data["command_type"] = fallback.get("command_type", "unknown")

    data["intent"] = data["command_type"]

    routing = command_routing(data["command_type"])
    data["is_content_request"] = routing["is_content_request"]
    data["requires_opportunity"] = routing["requires_opportunity"]
    data["routing_target"] = routing["routing_target"]

    # Sanitize forbidden command leakage.
    forbidden = re.compile(r"\bsof[ií]a\b|\bcrea\s+una\s+p[aá]gina\b|\bhazme\s+una\s+p[aá]gina\b", re.I)
    for key in ["clean_request", "title", "topic", "target_keyword"]:
        value = str(data.get(key) or "").strip()
        if forbidden.search(value):
            value = clean_command_text(value)
        data[key] = value

    data["page_type"] = str(data.get("page_type") or fallback["page_type"]).strip()
    if data["page_type"] not in ALLOWED_PAGE_TYPES:
        data["page_type"] = fallback["page_type"]

    # For examiner-originated content, keep content type aligned with the selected page blueprint.
    # This prevents downstream conflicts such as page_type=authority_page but content_type=educational_page.
    data["recommended_content_type"] = data["page_type"]

    data["intent_type"] = str(data.get("intent_type") or infer_intent(data["page_type"])).strip()
    if data["intent_type"] not in ALLOWED_INTENTS:
        data["intent_type"] = infer_intent(data["page_type"])

    data["sensitivity"] = str(data.get("sensitivity") or fallback["sensitivity"]).strip()
    if data["sensitivity"] not in ALLOWED_SENSITIVITY:
        data["sensitivity"] = fallback["sensitivity"]

    if fallback.get("sensitivity") == "high":
        data["sensitivity"] = "high"
        data["requires_manual_review"] = True

    # Remove deterministic fallback warning when AI parsing succeeded.
    warnings = data.get("quality_warnings", []) or []
    data["quality_warnings"] = [
        w for w in warnings
        if "deterministic fallback" not in str(w).lower()
    ]

    try:
        confidence = float(data.get("confidence", 0.75))
    except Exception:
        confidence = 0.75
    data["confidence"] = max(0.0, min(1.0, confidence))

    if not data.get("suggested_slug") or forbidden.search(str(data.get("suggested_slug"))):
        data["suggested_slug"] = slugify(data.get("target_keyword") or data.get("title"))

    data["suggested_slug"] = slugify(data["suggested_slug"])

    clean_text = data.get("clean_request") or data.get("topic") or data.get("title") or ""
    country = data.get("country", "")

    data["human_title"] = data.get("human_title") or data.get("title") or fallback.get("human_title", "")
    data["seo_title"] = data.get("seo_title") or data.get("human_title") or data.get("title") or ""
    data["page_topic"] = data.get("page_topic") or clean_text
    data["image_topic"] = data.get("image_topic") or build_image_topic(clean_text, language=data.get("language", "es"))

    data["short_target_keyword"] = (
        data.get("short_target_keyword")
        or shorten_keyword(clean_text, language=data.get("language", "es"), country=country)
    )

    data["short_slug"] = slugify(
        data.get("short_slug")
        or data.get("short_target_keyword")
        or data.get("target_keyword")
        or data.get("title")
    )

    data["created_at"] = now_iso()

    return data


def parse_examiner_request(workspace_id: str, raw_text: str, use_ai: bool = True) -> Dict[str, Any]:
    fallback = deterministic_parse(workspace_id, raw_text)

    if not use_ai:
        return fallback

    try:
        prompt = build_ai_prompt(workspace_id, raw_text, fallback)
        response = call_ollama(prompt, model=DEFAULT_MODEL)
        ai_data = extract_json_object(response)
        return merge_and_validate(ai_data, fallback, DEFAULT_MODEL)

    except Exception as exc:
        fallback["parser_error"] = f"{type(exc).__name__}: {exc}"
        fallback["quality_warnings"].append("AI parser failed; deterministic fallback used.")
        return fallback


def main():
    if len(sys.argv) < 3:
        print('Usage: python app/parse_examiner_request.py WORKSPACE_ID "Sofía, crea una página sobre ..."')
        print("Optional: --no-ai")
        return

    use_ai = "--no-ai" not in sys.argv
    args = [arg for arg in sys.argv[1:] if arg != "--no-ai"]

    workspace_id = args[0]
    raw_text = " ".join(args[1:]).strip()

    parsed = parse_examiner_request(workspace_id, raw_text, use_ai=use_ai)
    print(json.dumps(parsed, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
