import json
import re
import sys
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]

WORKSPACE_ID = sys.argv[1] if len(sys.argv) > 1 else "local.ao"

WORKSPACE_MAP = {
    "local.ao": "sites/local_sites/ao",
    "local.es": "sites/local_sites/es",
    "global.polar": "sites/global_sites/polar"
}

if WORKSPACE_ID not in WORKSPACE_MAP:
    raise ValueError(f"Unknown workspace: {WORKSPACE_ID}")

LOCAL_SITE_PATH = SOFIA_ROOT / WORKSPACE_MAP[WORKSPACE_ID]

OPPORTUNITIES_FILE = LOCAL_SITE_PATH / "external_opportunities.json"
LANGUAGE_PROFILE_FILE = LOCAL_SITE_PATH / "language_profile.json"


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
        "ç": "c"
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


def get_country_name(language_profile: dict) -> str:
    return language_profile.get("region", {}).get("country_name", "")


def get_country_slug(language_profile: dict) -> str:
    country_name = get_country_name(language_profile)
    return slugify(country_name)


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

    if content_type in ["landing_page", "service_page"]:
        meta_template = seo_templates.get("meta_description_service", "")
    else:
        meta_template = seo_templates.get("meta_description_blog", "")

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


def main():
    print("=== Sofia: Generate Opportunity SEO Brief ===\n")

    opportunities_data = load_json(OPPORTUNITIES_FILE)
    language_profile = load_json(LANGUAGE_PROFILE_FILE)

    opportunities = opportunities_data.get("opportunities", [])

    updated = 0

    for opp in opportunities:
        if opp.get("status") != "validated":
            continue

        if opp.get("seo_brief"):
            continue

        topic = opp.get("topic", "")
        content_type = opp.get("recommended_content_type", "blog_post")
        related_keywords = opp.get("related_keywords", [])
        target_keyword = related_keywords[0] if related_keywords else topic

        seo_brief = build_seo_brief(
            topic=topic,
            content_type=content_type,
            target_keyword=target_keyword,
            language_profile=language_profile
        )

        opp["seo_brief"] = seo_brief
        updated += 1

        print(f"{opp.get('id')}: {topic}")
        print(f"  Page title: {seo_brief['page_title']}")
        print(f"  SEO title: {seo_brief['seo_title']}")
        print(f"  Slug: {seo_brief['slug']}")
        print(f"  Meta description: {seo_brief['meta_description']}\n")

    opportunities_data["opportunities"] = opportunities
    save_json(OPPORTUNITIES_FILE, opportunities_data)

    print(f"SEO briefs created: {updated}")


if __name__ == "__main__":
    main()