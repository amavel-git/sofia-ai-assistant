import json
import sys
from pathlib import Path
from datetime import datetime, timezone


SOFIA_ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = SOFIA_ROOT / "data" / "workspaces.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def find_workspace(workspaces_data: dict, workspace_id: str):
    for workspace in workspaces_data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace

    return None


def get_workspace_folder(workspace: dict) -> Path:
    folder_path = workspace.get("folder_path", "")

    if not folder_path:
        raise ValueError(
            f"Workspace has no folder_path: {workspace.get('workspace_id')}"
        )

    return SOFIA_ROOT / folder_path


def slugify_text(value: str) -> str:
    value = str(value or "").strip().lower()

    replacements = {
        "á": "a", "à": "a", "â": "a", "ã": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u",
        "ç": "c",
        "ñ": "n",
    }

    for source, replacement in replacements.items():
        value = value.replace(source, replacement)

    import re
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value


def load_language_profile(workspace_folder: Path) -> dict:
    path = workspace_folder / "language_profile.json"

    if not path.exists():
        return {}

    try:
        return load_json(path)
    except Exception:
        return {}


def get_topic_label(opp: dict, language_profile: dict) -> str:
    topic = (
        opp.get("topic")
        or opp.get("target_keyword")
        or opp.get("title")
        or ""
    )

    topic_labels = language_profile.get("topic_labels", {}) or {}
    if topic in topic_labels:
        return topic_labels[topic]

    return topic


def apply_page_type_seo_template(seo: dict, opp: dict, language_profile: dict) -> dict:
    seo = dict(seo or {})

    page_type = (
        opp.get("page_type")
        or opp.get("blueprint_id")
        or opp.get("recommended_content_type")
        or ""
    )

    templates = language_profile.get("page_type_seo_templates", {}) or {}
    template = templates.get(page_type) or {}

    if not template:
        return seo

    topic = get_topic_label(opp, language_profile)
    topic_slug = slugify_text(topic)

    values = {
        "topic": topic,
        "topic_slug": topic_slug,
    }

    for key in [
        "focus_keyphrase",
        "page_title",
        "seo_title",
        "slug",
        "meta_description",
        "image_alt_text",
        "image_filename",
    ]:
        template_value = template.get(key)

        if not template_value:
            continue

        try:
            rendered = template_value.format(**values)
        except Exception:
            rendered = template_value

        if rendered:
            seo[key] = rendered

    return seo



def build_draft_input(opp: dict, workspace_id: str, language_profile: dict = None) -> dict:
    language_profile = language_profile or {}
    seo = opp.get("seo_brief", {}) or {}
    seo = apply_page_type_seo_template(seo, opp, language_profile)
    strategy = opp.get("content_strategy_brief", {}) or {}

    return {
        "generated_at": now(),
        "source": "sofia_external_intelligence",
        "opportunity_id": opp.get("id", ""),
        "workspace_id": opp.get("workspace_id") or workspace_id,
        "language": opp.get("language", ""),
        "country": opp.get("country", ""),
        "topic": opp.get("topic", ""),
        "content_type": opp.get("recommended_content_type", ""),

        "page_type": opp.get("page_type", ""),
        "blueprint_id": opp.get("blueprint_id", ""),
        "intent_type": opp.get("intent_type", ""),

        "page_type_classification": opp.get(
            "page_type_classification",
            {}
        ),

        "priority": opp.get("priority", ""),
        "detected_concepts": opp.get("detected_concepts", []),
        "cluster_concept": opp.get("cluster_concept", ""),
        "related_keywords": opp.get("related_keywords", []),

        "seo": {
            "focus_keyphrase": seo.get("focus_keyphrase", ""),
            "page_title": seo.get("page_title", ""),
            "seo_title": seo.get("seo_title", ""),
            "slug": seo.get("slug", ""),
            "meta_description": seo.get("meta_description", ""),
            "suggested_headings": seo.get("suggested_headings", {}),
            "image_alt_text": seo.get("image_alt_text", ""),
            "image_filename": seo.get("image_filename", "")
        },

        "strategy": {
            "strategy_version": strategy.get("strategy_version", ""),
            "content_goal": strategy.get("content_goal", ""),
            "target_audience": strategy.get("target_audience", ""),
            "recommended_angle": strategy.get("recommended_angle", ""),
            "required_sections": strategy.get("required_sections", []),
            "warnings": strategy.get("warnings", []),
            "conversion_goal": strategy.get("conversion_goal", ""),
            "internal_linking_notes": strategy.get("internal_linking_notes", []),

            "page_blueprint": strategy.get("page_blueprint", {}),
            "content_focus": strategy.get("content_focus", {}),
            "faq_strategy": strategy.get("faq_strategy", {}),
            "conversion_strategy": strategy.get("conversion_strategy", {}),
            "quality_controls": strategy.get("quality_controls", {})
        },

        "quality_controls": {
            "avoid_legal_guarantees": True,
            "avoid_absolute_accuracy_claims": True,
            "avoid_unverified_local_law_claims": True,
            "requires_examiner_review_before_publication": True,
            "avoid_generic_polygraph_filler": True,
            "prefer_topic_specific_faqs": True
        }
    }


def main():
    print("=== Sofia: Generate Draft Input ===\n")

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python app/generate_draft_input.py WORKSPACE_ID")
        print("  python app/generate_draft_input.py WORKSPACE_ID --force")
        print("Example:")
        print("  python app/generate_draft_input.py local.ao")
        return

    workspace_id = sys.argv[1]
    force = "--force" in sys.argv

    workspaces_data = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces_data, workspace_id)

    if not workspace:
        print(f"Workspace not found: {workspace_id}")
        return

    workspace_folder = get_workspace_folder(workspace)
    language_profile = load_language_profile(workspace_folder)
    opportunities_file = workspace_folder / "external_opportunities.json"

    data = load_json(opportunities_file)
    opportunities = data.get("opportunities", [])

    updated = 0

    for opp in opportunities:
        if opp.get("status") not in [
            "validated",
            "approved",
            "converted_to_intake"
        ]:
            continue

        if opp.get("draft_input") and not force:
            continue

        if not opp.get("seo_brief"):
            print(f"Skipped {opp.get('id')}: missing seo_brief")
            continue

        if not opp.get("content_strategy_brief"):
            print(f"Skipped {opp.get('id')}: missing content_strategy_brief")
            continue

        opp["draft_input"] = build_draft_input(opp, workspace_id, language_profile=language_profile)
        opp["updated_at"] = now()
        updated += 1

        print(f"{opp.get('id')}: {opp.get('topic')}")
        print("  Draft input created/updated\n")

    data["opportunities"] = opportunities
    save_json(opportunities_file, data)

    print(f"Draft inputs created/updated: {updated}")


if __name__ == "__main__":
    main()