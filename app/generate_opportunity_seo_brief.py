import json
import re
import sys
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]

WORKSPACES_FILE = SOFIA_ROOT / "data" / "workspaces.json"
WORKSPACE_ID = sys.argv[1] if len(sys.argv) > 1 else ""


def resolve_workspace_path(workspace_id: str) -> Path:
    if not workspace_id:
        raise ValueError("Missing workspace id")

    workspaces = load_json(WORKSPACES_FILE)

    for workspace in workspaces.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            folder_path = workspace.get("folder_path", "")
            if not folder_path:
                raise ValueError(f"Workspace has no folder_path: {workspace_id}")
            return SOFIA_ROOT / folder_path

    raise ValueError(f"Unknown workspace: {workspace_id}")


LOCAL_SITE_PATH = None
OPPORTUNITIES_FILE = None
LANGUAGE_PROFILE_FILE = None


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def slugify(text: str) -> str:
    text = text.lower().strip()

    replacements = {
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "õ": "o", "ô": "o",
        "ú": "u",
        "ç": "c",
        "ñ": "n",
    }

    for original, replacement in replacements.items():
        text = text.replace(original, replacement)

    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)

    return text.strip("-")


def apply_template(template: str, values: dict) -> str:
    result = template

    for key, value in values.items():
        result = result.replace("{" + key + "}", str(value))

    return result


def get_language_code(language_profile: dict) -> str:
    return (
        str(language_profile.get("language", ""))
        or str(language_profile.get("locale", ""))
        or str(language_profile.get("region", {}).get("language", ""))
        or "en"
    ).lower()


def get_country_name(language_profile: dict) -> str:
    return language_profile.get("region", {}).get("country_name", "")


def get_country_slug(language_profile: dict) -> str:
    country_name = get_country_name(language_profile)
    return slugify(country_name)


def localize_topic_from_seed(topic_seed: str, topic_profile: dict, language_profile: dict) -> str:
    """
    Converts Sofia's language-neutral topic seed into an examiner-facing topic
    using the workspace language.

    The signal conversion layer should remain language-neutral.
    This SEO brief layer is responsible for localizing the topic.
    """

    topic_seed = str(topic_seed or "").strip()
    tags = set(topic_profile.get("topic_tags", []) or [])
    language = get_language_code(language_profile)
    country_name = get_country_name(language_profile)

    if not topic_seed:
        return ""

    # Portuguese workspaces
    if language.startswith("pt"):
        if {"warehouse", "logistics", "missing_goods"} & tags:
            return f"testes de polígrafo para investigação de desaparecimento de mercadorias em centros logísticos em {country_name}"

        if "fuel_diversion" in tags:
            return f"testes de polígrafo para investigação de desvios de combustível em {country_name}"

        if "procurement_fraud" in tags:
            return f"testes de polígrafo para investigação de fraude em compras e procurement em {country_name}"

        if "financial_fraud" in tags or "improper_payments" in tags:
            return f"testes de polígrafo para investigação de pagamentos indevidos e fraude financeira em {country_name}"

        if "internal_theft" in tags:
            return f"testes de polígrafo para investigação de furtos internos em empresas em {country_name}"

    # Spanish workspaces
    if language.startswith("es"):
        if {"warehouse", "logistics", "missing_goods"} & tags:
            return f"pruebas de polígrafo para investigar la desaparición de mercancías en centros logísticos en {country_name}"

        if "fuel_diversion" in tags:
            return f"pruebas de polígrafo para investigar desvíos de combustible en {country_name}"

        if "procurement_fraud" in tags:
            return f"pruebas de polígrafo para investigar fraude en compras y proveedores en {country_name}"

        if "financial_fraud" in tags or "improper_payments" in tags:
            return f"pruebas de polígrafo para investigar pagos indebidos y fraude financiero en {country_name}"

        if "internal_theft" in tags:
            return f"pruebas de polígrafo para investigar robos internos en empresas en {country_name}"

    # French workspaces
    if language.startswith("fr"):
        if {"warehouse", "logistics", "missing_goods"} & tags:
            return f"tests polygraphiques pour enquêter sur la disparition de marchandises dans les centres logistiques en {country_name}"

        if "fuel_diversion" in tags:
            return f"tests polygraphiques pour enquêter sur les détournements de carburant en {country_name}"

        if "procurement_fraud" in tags:
            return f"tests polygraphiques pour enquêter sur la fraude aux achats et fournisseurs en {country_name}"

        if "financial_fraud" in tags or "improper_payments" in tags:
            return f"tests polygraphiques pour enquêter sur les paiements indus et la fraude financière en {country_name}"

        if "internal_theft" in tags:
            return f"tests polygraphiques pour enquêter sur les vols internes en entreprise en {country_name}"

    # English / fallback
    if {"warehouse", "logistics", "missing_goods"} & tags:
        return f"polygraph testing for missing goods in logistics centers in {country_name}"

    if "fuel_diversion" in tags:
        return f"polygraph testing for fuel diversion investigations in {country_name}"

    if "procurement_fraud" in tags:
        return f"polygraph testing for procurement fraud investigations in {country_name}"

    if "financial_fraud" in tags or "improper_payments" in tags:
        return f"polygraph testing for improper payments and financial fraud investigations in {country_name}"

    if "internal_theft" in tags:
        return f"polygraph testing for internal theft investigations in {country_name}"

    return topic_seed



def template_value_map(topic: str, target_keyword: str, language_profile: dict) -> dict:
    topic = str(topic or "").strip()
    target_keyword = str(target_keyword or topic).strip()

    values = {
        "topic": topic,
        "topic_title": topic.capitalize(),
        "topic_slug": slugify(topic),
        "target_keyword": target_keyword,
        "target_keyword_slug": slugify(target_keyword),
        "country_name": get_country_name(language_profile),
        "country_slug": get_country_slug(language_profile),
        "city": "",
        "city_slug": ""
    }

    return values


def apply_page_type_seo_template(topic: str, content_type: str, target_keyword: str, language_profile: dict):
    templates = language_profile.get("page_type_seo_templates", {}) or {}
    template = templates.get(content_type) or templates.get("default") or {}

    if not template:
        return None

    values = template_value_map(topic, target_keyword, language_profile)

    if content_type == "city_page":
        values["city"] = topic
        values["city_slug"] = slugify(topic)

    focus_keyphrase = apply_template(
        template.get("focus_keyphrase", "{target_keyword}"),
        values
    ).strip()

    page_title = apply_template(
        template.get("page_title", "{topic}"),
        values
    ).strip()

    seo_title = apply_template(
        template.get("seo_title", "{page_title}"),
        {**values, "page_title": page_title}
    ).strip()

    slug = apply_template(
        template.get("slug", "{topic_slug}"),
        values
    ).strip()

    meta_description = apply_template(
        template.get("meta_description", "{topic}."),
        {**values, "focus_keyphrase": focus_keyphrase, "page_title": page_title}
    ).strip()

    image_alt_text = apply_template(
        template.get("image_alt_text", "{page_title}"),
        {**values, "page_title": page_title}
    ).strip()

    image_filename = apply_template(
        template.get("image_filename", "{topic_slug}.jpg"),
        values
    ).strip()

    return {
        "focus_keyphrase": focus_keyphrase,
        "page_title": page_title,
        "seo_title": seo_title,
        "slug": slugify(slug),
        "meta_description": meta_description[:155],
        "suggested_headings": build_h_structure(page_title, content_type, language_profile),
        "image_alt_text": image_alt_text,
        "image_filename": image_filename
    }

def build_h_structure(topic: str, content_type: str, language_profile: dict):
    heading_translations = language_profile.get("heading_translations", {})

    if content_type in ["landing_page", "service_page"]:
        h1_template = heading_translations.get("service_h1", "{topic}")
        h2_sections = heading_translations.get("service_sections", [])
    else:
        h1_template = heading_translations.get("blog_h1", "{topic}")
        h2_sections = heading_translations.get("blog_sections", [])

    return {
        "h1": apply_template(h1_template, {"topic": topic.capitalize()}),
        "h2": h2_sections
    }


def build_seo_brief(topic: str, content_type: str, target_keyword: str, language_profile: dict):
    template_result = apply_page_type_seo_template(
        topic=topic,
        content_type=content_type,
        target_keyword=target_keyword,
        language_profile=language_profile
    )

    if template_result:
        return template_result

    seo_templates = language_profile.get("seo_templates", {})

    country_name = get_country_name(language_profile)
    country_slug = get_country_slug(language_profile)
    slug = slugify(topic)

    values = {
        "topic": topic.capitalize(),
        "country_name": country_name,
        "country_slug": country_slug,
        "slug": slug,
        "target_keyword": target_keyword
    }

    page_type_to_template = {
        "landing_page": "meta_description_service",
        "service_page": "meta_description_service",
        "city_page": "meta_description_service",

        "educational_page": "meta_description_blog",
        "authority_page": "meta_description_blog",
        "pillar_page": "meta_description_blog",
        "faq_page": "meta_description_blog",
        "blog_post": "meta_description_blog",

        "pricing_page": "meta_description_pricing"
    }

    template_key = page_type_to_template.get(
        content_type,
        "meta_description_blog"
    )

    meta_template = seo_templates.get(template_key, "")

    if not meta_template:
        if country_name:
            meta_template = (
                "{topic}. "
                "Información profesional sobre {target_keyword} "
                "en {country_name}."
            )
        else:
            meta_template = (
                "{topic}. "
                "Información profesional sobre {target_keyword}."
            )

    return {
        "focus_keyphrase": target_keyword,
        "page_title": apply_template(seo_templates.get("page_title", "{topic}"), values),
        "seo_title": apply_template(seo_templates.get("seo_title", "{topic}"), values),
        "slug": slug,
        "meta_description": apply_template(meta_template, values),
        "suggested_headings": build_h_structure(topic, content_type, language_profile),
        "image_alt_text": apply_template(seo_templates.get("image_alt_text", "{topic}"), values),
        "image_filename": apply_template(seo_templates.get("image_filename", "{slug}.jpg"), values)
    }


def choose_workspace_language_topic(opp: dict, language_profile: dict) -> str:
    workspace_language = str(
        language_profile.get("language")
        or language_profile.get("locale")
        or language_profile.get("region", {}).get("language", "")
        or ""
    ).lower()

    signal_language = str(opp.get("language", "")).lower()

    raw_signal = str(opp.get("raw_signal", "") or "").strip()
    localized_topic = str(opp.get("localized_topic", "") or "").strip()
    topic = str(opp.get("topic", "") or "").strip()
    topic_seed = str(opp.get("topic_seed", "") or opp.get("normalized_topic", "") or "").strip()

    if is_internal_topic_code(localized_topic):
        localized_topic = ""

    if is_internal_topic_code(topic):
        topic = ""

    if raw_signal and signal_language and workspace_language.startswith(signal_language[:2]):
        return raw_signal

    if localized_topic:
        return localized_topic

    if topic and not is_internal_topic_code(topic):
        return topic

    return topic_seed


LOCAL_SITE_PATH = resolve_workspace_path(WORKSPACE_ID)
OPPORTUNITIES_FILE = LOCAL_SITE_PATH / "external_opportunities.json"
LANGUAGE_PROFILE_FILE = LOCAL_SITE_PATH / "language_profile.json"



def is_internal_topic_code(value: str) -> bool:
    value = str(value or "").strip()

    if not value:
        return False

    # Internal machine-style topic codes should not become public SEO terms.
    if "_" in value:
        return True

    if value.islower() and "-" not in value and " " not in value and len(value) > 18:
        return True

    return False


def get_human_topic_seed(opp: dict) -> str:
    """
    Prefer human-facing opportunity labels/titles over internal topic codes.
    This prevents values such as appointment_booking from becoming public
    SEO titles, slugs, focus keyphrases, and Telegram titles.
    """
    candidates = [
        opp.get("topic_label"),
        opp.get("title"),
        opp.get("suggested_title"),
        opp.get("page_title"),
        opp.get("normalized_topic"),
        opp.get("topic_seed"),
        opp.get("topic"),
    ]

    for value in candidates:
        value = str(value or "").strip()
        if not value:
            continue

        if is_internal_topic_code(value):
            continue

        return value

    # Last fallback: return the raw topic only if nothing better exists.
    return str(
        opp.get("topic_seed")
        or opp.get("normalized_topic")
        or opp.get("topic")
        or opp.get("title")
        or ""
    ).strip()

def main():
    print("=== Sofia: Generate Opportunity SEO Brief ===\n")

    opportunities_data = load_json(OPPORTUNITIES_FILE)
    language_profile = load_json(LANGUAGE_PROFILE_FILE)

    opportunities = opportunities_data.get("opportunities", [])

    updated = 0

    for opp in opportunities:
        if opp.get("status") not in [
            "pending_review",
            "queued_for_review",
            "validated",
            "approved",
            "converted_to_intake"
        ]:
            continue

        if opp.get("seo_brief"):
            continue

        topic_seed = get_human_topic_seed(opp)
        topic_profile = opp.get("topic_profile", {}) or {}
        content_type = (
            opp.get("page_type")
            or opp.get("recommended_content_type")
            or opp.get("content_type")
            or "blog_post"
        )

        localized_topic = choose_workspace_language_topic(
            opp,
            language_profile
        )

        if not localized_topic:
            localized_topic = localize_topic_from_seed(
                topic_seed=topic_seed,
                topic_profile=topic_profile,
                language_profile=language_profile
            )

        if not localized_topic:
            localized_topic = opp.get("topic", "")

        opp["topic_seed"] = topic_seed
        opp["localized_topic"] = localized_topic
        opp["topic"] = localized_topic

        related_keywords = opp.get("related_keywords", [])
        raw_signal = opp.get("raw_signal", "")

        target_keyword = localized_topic

        keywords = list(dict.fromkeys([
            localized_topic,
            topic_seed,
            raw_signal,
            *related_keywords
        ]))

        opp["related_keywords"] = [kw for kw in keywords if kw]

        seo_brief = build_seo_brief(
            topic=localized_topic,
            content_type=content_type,
            target_keyword=target_keyword,
            language_profile=language_profile
        )

        opp["seo_brief"] = seo_brief
        updated += 1

        print(f"{opp.get('id')}: {localized_topic}")
        print(f"  Topic seed: {topic_seed}")
        print(f"  Page title: {seo_brief['page_title']}")
        print(f"  SEO title: {seo_brief['seo_title']}")
        print(f"  Slug: {seo_brief['slug']}")
        print(f"  Meta description: {seo_brief['meta_description']}\n")

    opportunities_data["opportunities"] = opportunities
    save_json(OPPORTUNITIES_FILE, opportunities_data)

    print(f"SEO briefs created: {updated}")


if __name__ == "__main__":
    main()