import json
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]

PAGE_BLUEPRINTS_FILE = SOFIA_ROOT / "data" / "page_blueprints.json"
SECTION_LIBRARY_FILE = SOFIA_ROOT / "data" / "section_library.json"
CONTENT_TAXONOMY_FILE = SOFIA_ROOT / "data" / "content_taxonomy.json"
WORKSPACES_ROOT = SOFIA_ROOT / "sites" / "local_sites"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_optional_json(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}
    return load_json(path)


def workspace_slug(workspace_id: str) -> str:
    """
    Convert workspace_id like local.es into folder slug es.
    """
    value = str(workspace_id or "").strip()

    if not value:
        raise ValueError("workspace_id is required")

    if value.startswith("local."):
        return value.split(".", 1)[1]

    return value


def workspace_path(workspace_id: str) -> Path:
    return WORKSPACES_ROOT / workspace_slug(workspace_id)


def load_page_blueprints():
    if not PAGE_BLUEPRINTS_FILE.exists():
        raise FileNotFoundError(f"Missing page blueprints file: {PAGE_BLUEPRINTS_FILE}")

    return load_json(PAGE_BLUEPRINTS_FILE)


def load_section_library():
    return load_optional_json(SECTION_LIBRARY_FILE, default={})


def load_content_taxonomy():
    return load_optional_json(CONTENT_TAXONOMY_FILE, default={})


def load_page_presentation(workspace_id: str):
    path = workspace_path(workspace_id) / "page_presentation.json"

    if not path.exists():
        raise FileNotFoundError(f"Missing page presentation file: {path}")

    return load_json(path)


def load_optional_page_presentation(workspace_id: str):
    if not workspace_id:
        return {}

    path = workspace_path(workspace_id) / "page_presentation.json"
    return load_optional_json(path, default={})


def list_blueprints():
    data = load_page_blueprints()
    return sorted((data.get("page_blueprints") or {}).keys())


def get_blueprint(blueprint_id: str):
    data = load_page_blueprints()
    blueprints = data.get("page_blueprints") or {}

    blueprint_id = str(blueprint_id or "").strip()

    if not blueprint_id:
        return None

    return blueprints.get(blueprint_id)


def get_default_blueprint_id(fallback: str = "landing_page"):
    data = load_page_blueprints()
    supported = data.get("supported_page_types") or []

    if fallback in supported:
        return fallback

    if supported:
        return supported[0]

    return "landing_page"


def resolve_blueprint_id(page_type: str = "", blueprint_id: str = ""):
    data = load_page_blueprints()
    blueprints = data.get("page_blueprints") or {}

    blueprint_id = str(blueprint_id or "").strip()
    page_type = str(page_type or "").strip()

    if blueprint_id and blueprint_id in blueprints:
        return blueprint_id

    if page_type and page_type in blueprints:
        return page_type

    return get_default_blueprint_id()


def get_blueprint_sections(blueprint_id: str):
    blueprint = get_blueprint(blueprint_id)

    if not blueprint:
        return []

    return blueprint.get("sections") or []


def get_required_sections(blueprint_id: str):
    return [
        section
        for section in get_blueprint_sections(blueprint_id)
        if section.get("required")
    ]


def get_optional_sections(blueprint_id: str):
    return [
        section
        for section in get_blueprint_sections(blueprint_id)
        if not section.get("required")
    ]


def get_topic_intelligence(topic_key: str):
    taxonomy = load_content_taxonomy()
    topics = taxonomy.get("topics") or {}

    topic_key = str(topic_key or "").strip()

    if not topic_key:
        return {}

    return topics.get(topic_key, {})


def enrich_sections_with_library(sections: list, section_library: dict):
    """
    Add section-type writing intelligence from section_library.json
    without mutating the original blueprint sections.
    """
    library_sections = (section_library or {}).get("sections") or {}
    enriched = []

    for section in sections or []:
        section_copy = dict(section)
        section_type = section_copy.get("type")
        library_entry = library_sections.get(section_type, {})

        if library_entry:
            section_copy["section_intelligence"] = library_entry

        enriched.append(section_copy)

    return enriched


def resolve_blueprint_for_workspace(
    workspace_id: str,
    blueprint_id: str = "",
    page_type: str = "",
    topic_key: str = "",
):
    """
    Resolve global blueprint + workspace presentation + section library
    + optional topic intelligence into one normalized package.

    This does not generate content.
    It prepares deterministic planning data for later generation.
    """
    resolved_blueprint_id = resolve_blueprint_id(
        page_type=page_type,
        blueprint_id=blueprint_id,
    )

    blueprint = get_blueprint(resolved_blueprint_id)
    if not blueprint:
        raise ValueError(f"Unknown blueprint_id: {resolved_blueprint_id}")

    presentation = load_page_presentation(workspace_id)
    section_library = load_section_library()
    taxonomy = load_content_taxonomy()
    topic_intelligence = get_topic_intelligence(topic_key)

    raw_sections = blueprint.get("sections") or []
    enriched_sections = enrich_sections_with_library(raw_sections, section_library)

    required_sections = [
        section for section in enriched_sections if section.get("required")
    ]

    optional_sections = [
        section for section in enriched_sections if not section.get("required")
    ]

    validation_requirements = blueprint.get("validation_requirements") or {}
    image_requirements = blueprint.get("image_requirements") or {}

    return {
        "workspace_id": workspace_id,
        "blueprint_id": resolved_blueprint_id,
        "blueprint": blueprint,
        "presentation": presentation,
        "section_library": section_library,
        "taxonomy_version": taxonomy.get("version"),
        "topic_key": topic_key,
        "topic_intelligence": topic_intelligence,
        "sections": enriched_sections,
        "required_sections": required_sections,
        "optional_sections": optional_sections,
        "validation_requirements": validation_requirements,
        "image_requirements": image_requirements,
        "presentation_preferences": {
            "faq": presentation.get("faq") or {},
            "cta_strategy": presentation.get("cta_strategy") or {},
            "trust_blocks": presentation.get("trust_blocks") or {},
            "strategic_links": presentation.get("strategic_links") or {},
            "layout_preferences": presentation.get("layout_preferences") or {},
            "image_strategy": presentation.get("image_strategy") or {},
            "rendering": presentation.get("rendering") or {},
            "validation_preferences": presentation.get("validation_preferences") or {},
        },
    }


def build_prompt_text_from_resolved_package(package: dict):
    blueprint_id = package.get("blueprint_id", "")
    blueprint = package.get("blueprint") or {}
    sections = package.get("sections") or {}
    presentation = package.get("presentation") or {}
    topic_intelligence = package.get("topic_intelligence") or {}

    prompt_lines = [
        f"Use page blueprint: {blueprint_id}.",
        f"Blueprint description: {blueprint.get('description', '')}",
    ]

    drafting_instructions = blueprint.get("drafting_instructions", {}) or {}

    if drafting_instructions:
        prompt_lines.append("")
        prompt_lines.append("Blueprint drafting instructions:")

        search_intent = drafting_instructions.get("search_intent", "")
        if search_intent:
            prompt_lines.append(f"- Search intent: {search_intent}")

        opening_rule = drafting_instructions.get("opening_rule", "")
        if opening_rule:
            prompt_lines.append(f"- Opening rule: {opening_rule}")

        structure_guidance = drafting_instructions.get("structure_guidance", []) or []
        if structure_guidance:
            prompt_lines.append("- Structure guidance:")
            for item in structure_guidance:
                prompt_lines.append(f"  - {item}")

        ai_engine_guidance = drafting_instructions.get("ai_engine_guidance", []) or []
        if ai_engine_guidance:
            prompt_lines.append("- Search and AI-engine guidance:")
            for item in ai_engine_guidance:
                prompt_lines.append(f"  - {item}")

        faq_guidance = drafting_instructions.get("faq_guidance", "")
        if faq_guidance:
            prompt_lines.append(f"- FAQ guidance: {faq_guidance}")

        cta_guidance = drafting_instructions.get("cta_guidance", "")
        if cta_guidance:
            prompt_lines.append(f"- CTA guidance: {cta_guidance}")

        avoid = drafting_instructions.get("avoid", []) or []
        if avoid:
            prompt_lines.append("- Avoid:")
            for item in avoid:
                prompt_lines.append(f"  - {item}")

    if topic_intelligence:
        prompt_lines.append("")
        prompt_lines.append("Topic intelligence:")
        prompt_lines.append(f"- Topic: {topic_intelligence.get('label', '')}")

        section_focus = topic_intelligence.get("section_focus") or {}
        for focus_key in [
            "problem",
            "consequences",
            "investigation_challenges",
            "polygraph_role",
            "limitations",
            "faq",
        ]:
            values = section_focus.get(focus_key) or []
            if values:
                prompt_lines.append(f"- {focus_key}:")
                for value in values:
                    prompt_lines.append(f"  - {value}")

    presentation_preferences = package.get("presentation_preferences") or {}
    if presentation_preferences:
        prompt_lines.append("")
        prompt_lines.append("Workspace presentation preferences:")

        faq = presentation_preferences.get("faq") or {}
        if faq:
            prompt_lines.append(
                f"- FAQ format: {faq.get('preferred_format') or faq.get('default_format') or 'standard_html'}"
            )

        cta = presentation_preferences.get("cta_strategy") or {}
        if cta:
            prompt_lines.append(
                f"- CTA tone: {cta.get('default_tone', 'professional')}"
            )
            avoid_cta = cta.get("avoid") or []
            if avoid_cta:
                prompt_lines.append("- CTA must avoid:")
                for item in avoid_cta:
                    prompt_lines.append(f"  - {item}")

        image_strategy = presentation_preferences.get("image_strategy") or {}
        if image_strategy:
            prompt_lines.append(
                f"- Image style: {image_strategy.get('preferred_style', '')}"
            )

    prompt_lines.append("")
    prompt_lines.append("Required page sections:")

    for section in sections:
        required = "required" if section.get("required") else "optional"
        prompt_lines.append(
            f"- {section.get('id', '')} "
            f"({section.get('type', '')}, {required}): "
            f"{section.get('purpose', '')}"
        )

        section_intelligence = section.get("section_intelligence") or {}
        writing_guidance = section_intelligence.get("writing_guidance") or []
        if writing_guidance:
            prompt_lines.append("  Writing guidance:")
            for item in writing_guidance:
                prompt_lines.append(f"  - {item}")

    return "\n".join(prompt_lines)


def build_page_blueprint_package(source: dict, workspace_id: str = ""):
    """
    Build a normalized blueprint package from structural source data.

    Source may include:
    - blueprint_id
    - page_type
    - content_type
    - title
    - target_keyword
    - search_intent
    - topic_key

    If workspace_id is provided, the package includes workspace presentation.
    """
    source = source or {}

    blueprint_id = resolve_blueprint_id(
        page_type=(
            source.get("page_type")
            or source.get("content_type")
            or ""
        ),
        blueprint_id=source.get("blueprint_id", ""),
    )

    topic_key = (
        source.get("topic_key")
        or source.get("topic")
        or source.get("topic_id")
        or ""
    )

    if workspace_id:
        package = resolve_blueprint_for_workspace(
            workspace_id=workspace_id,
            blueprint_id=blueprint_id,
            topic_key=topic_key,
        )
    else:
        blueprint = get_blueprint(blueprint_id) or {}
        section_library = load_section_library()
        sections = enrich_sections_with_library(
            blueprint.get("sections") or [],
            section_library,
        )

        package = {
            "workspace_id": "",
            "blueprint_id": blueprint_id,
            "blueprint": blueprint,
            "presentation": {},
            "section_library": section_library,
            "topic_key": topic_key,
            "topic_intelligence": get_topic_intelligence(topic_key),
            "sections": sections,
            "required_sections": [
                section for section in sections if section.get("required")
            ],
            "optional_sections": [
                section for section in sections if not section.get("required")
            ],
            "validation_requirements": blueprint.get("validation_requirements") or {},
            "image_requirements": blueprint.get("image_requirements") or {},
            "presentation_preferences": {},
        }

    package["source"] = source
    package["prompt_text"] = build_prompt_text_from_resolved_package(package)

    return package


def validate_blueprints():
    data = load_page_blueprints()

    errors = []

    supported = set(data.get("supported_page_types") or [])
    blueprints = data.get("page_blueprints") or {}
    section_library = data.get("section_library") or {}

    external_section_library = load_section_library()
    external_sections = (external_section_library.get("sections") or {})

    for blueprint_id in supported:
        if blueprint_id not in blueprints:
            errors.append(f"Supported page type has no blueprint: {blueprint_id}")

    for blueprint_id, blueprint in blueprints.items():
        if blueprint_id not in supported:
            errors.append(f"Blueprint not listed in supported_page_types: {blueprint_id}")

        sections = blueprint.get("sections") or []

        if not sections:
            errors.append(f"Blueprint has no sections: {blueprint_id}")

        for section in sections:
            section_id = section.get("id")
            section_type = section.get("type")

            if not section_id:
                errors.append(f"Blueprint {blueprint_id} has section without id")

            if not section_type:
                errors.append(f"Blueprint {blueprint_id} has section without type")
                continue

            if section_type not in section_library and section_type not in external_sections:
                errors.append(
                    f"Blueprint {blueprint_id} section {section_id} "
                    f"uses unknown section type: {section_type}"
                )

    return errors


def main():
    errors = validate_blueprints()

    if errors:
        print("Page blueprint validation failed:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    print("Page blueprints OK")
    print("Available blueprints:")
    for blueprint_id in list_blueprints():
        print(f"- {blueprint_id}")


if __name__ == "__main__":
    main()