import argparse
import json
from copy import deepcopy
from pathlib import Path
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
SITES_ROOT = ROOT / "sites" / "local_sites"
WORKSPACES_FILE = ROOT / "data" / "workspaces.json"


RUNTIME_EMPTY_FILES = {
    "draft_registry.json": {
        "scope": "workspace",
        "workspace_id": None,
        "drafts": []
    },
    "job_registry.json": {
        "workspace_id": None,
        "jobs": []
    },
    "local_review_queue.json": {},
    "social_review_queue.json": {},
    "content_opportunities.json": [],
    "external_opportunities.json": [],
    "external_signals.json": [],
    "positioning_snapshots.json": {
        "workspace_id": None,
        "snapshots": []
    },
    "competitor_scrape_log.json": {
        "workspace_id": None,
        "scrapes": []
    },
    "content_variants.json": {
        "workspace_id": None,
        "variants": []
    }
}


FOUNDATION_FILES = [
    "country_profile.json",
    "language_profile.json",
    "local_content_profile.json",
    "local_intelligence_profile.json",
    "local_signal_terms.json",
    "local_topic_overrides.json",
    "site_structure.json",
    "internal_link_suggestions.json",
    "market_intelligence.json",
    "market_intelligence_candidates.json",
    "page_presentation.json",
    "image_guidelines.json",
    "wordpress_config.json",
    "content_inventory.json",
    "site_content_memory.json"
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def replace_values(obj, replacements):
    if isinstance(obj, dict):
        return {k: replace_values(v, replacements) for k, v in obj.items()}

    if isinstance(obj, list):
        return [replace_values(v, replacements) for v in obj]

    if isinstance(obj, str):
        value = obj
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value

    return obj


def workspace_folder(workspace_id: str):
    suffix = workspace_id.split(".", 1)[-1]
    return SITES_ROOT / suffix


def make_empty_runtime_payload(filename, workspace_id):
    payload = deepcopy(RUNTIME_EMPTY_FILES[filename])

    if isinstance(payload, dict):
        payload["workspace_id"] = workspace_id

    return payload


def normalize_page_presentation(data, workspace_id, domain, language, country):
    data = deepcopy(data or {})
    data["workspace_id"] = workspace_id
    data.setdefault("version", "1.0")

    data.setdefault("cta_strategy", {})
    data["cta_strategy"].setdefault("position", ["after_intro", "before_faq", "final_section"])
    data["cta_strategy"].setdefault("type", "contact")
    data["cta_strategy"].setdefault("style", "soft")
    data["cta_strategy"].setdefault("repeat_allowed", True)

    data.setdefault("faq", {})
    data["faq"].setdefault("enabled", True)
    data["faq"].setdefault("format", "html")
    data["faq"].setdefault("position", "before_final_cta")
    data["faq"].setdefault("minimum_questions", 4)
    data["faq"].setdefault("maximum_questions", 6)

    data.setdefault("internal_links", {})
    data["internal_links"].setdefault("enabled", True)
    data["internal_links"].setdefault("strategy", "contextual")
    data["internal_links"].setdefault("minimum_links", 2)
    data["internal_links"].setdefault("target_links", 4)
    data["internal_links"].setdefault("maximum_links", 8)

    data.setdefault("images", {})
    data["images"].setdefault("enabled", True)
    data["images"].setdefault("featured_image", True)
    data["images"].setdefault("in_article_images", 2)
    data["images"].setdefault("generate_metadata", True)
    data["images"].setdefault("include_alt_text", True)
    data["images"].setdefault("include_filename", True)
    data["images"].setdefault("include_caption", True)
    data["images"].setdefault("include_prompt", True)
    data["images"].setdefault("preferred_style", "professional_realistic")
    data["images"].setdefault("preferred_format", "landscape")
    data["images"].setdefault("featured_image_aspect_ratio", "16:9")
    data["images"].setdefault("in_article_image_aspect_ratio", "16:9")
    data["images"].setdefault("placements", {
        "featured_image": "page_featured_image",
        "in_article_images": ["after_intro", "before_faq"]
    })

    data.setdefault("trust_blocks", {})
    data["trust_blocks"].setdefault("enabled", True)
    data["trust_blocks"].setdefault("position", "before_faq")

    data.setdefault("gutenberg", {})
    data["gutenberg"].setdefault("enabled", False)
    data["gutenberg"].setdefault("faq_format", "html")
    data["gutenberg"].setdefault("cta_block", None)
    data["gutenberg"].setdefault("trust_block", None)

    data.setdefault("wordpress", {})
    data["wordpress"].setdefault("cms", "wordpress")
    data["wordpress"].setdefault("editor", "gutenberg")
    data["wordpress"]["language"] = language
    data["wordpress"]["country"] = country
    data["wordpress"]["domain"] = domain

    return data


def normalize_market_intelligence(data, workspace_id, domain):
    data = deepcopy(data or {})
    data["workspace_id"] = workspace_id
    data["domain"] = domain
    data.setdefault("version", "1.0")
    data.setdefault("last_updated", now_iso())
    data.setdefault("competitors", [])
    data.setdefault("market_topics", [])
    data.setdefault("local_language_notes", [])
    data.setdefault("opportunity_rules", {})
    data.setdefault("source_notes", [])
    return data


def normalize_market_candidates(data, workspace_id, domain):
    data = deepcopy(data or {})
    data["workspace_id"] = workspace_id
    data["domain"] = domain
    data.setdefault("version", "1.0")
    data.setdefault("last_updated", None)
    data.setdefault("candidate_competitors", [])
    data.setdefault("candidate_market_topics", [])
    data.setdefault("candidate_language_notes", [])
    data.setdefault("candidate_opportunity_rules", [])
    data.setdefault("candidate_positioning_observations", [])
    data.setdefault("review_log", [])
    return data


def normalize_site_memory(data, workspace_id, domain, language, market_code):
    data = deepcopy(data or {})
    data.setdefault("workspace_info", {})
    data["workspace_info"]["workspace_id"] = workspace_id
    data["workspace_info"]["domain"] = domain
    data["workspace_info"]["language"] = language
    data["workspace_info"]["market_code"] = market_code
    data.setdefault("published_content", [])
    data.setdefault("draft_content", [])
    data.setdefault("content_topics", [])
    data.setdefault("keyword_index", [])
    data.setdefault("protected_topics", [])
    data.setdefault("cannibalization_notes", [])
    data.setdefault("content_opportunities", [])
    return data


def normalize_image_guidelines(data, workspace_id):
    data = deepcopy(data or {})
    data["workspace_id"] = workspace_id
    data.setdefault("version", "1.0")
    data.setdefault("featured_image", {
        "preferred_style": "professional_realistic",
        "aspect_ratio": "16:9"
    })
    data.setdefault("general_rules", [])
    data.setdefault("preferred_elements", [])
    data.setdefault("avoid_elements", [])
    data.setdefault("polygraph_rules", [])
    data.setdefault("industry_specific", {})
    data.setdefault("topic_mapping", {})
    return data


def convert_image_profile_to_guidelines(image_profile, workspace_id):
    profile = deepcopy(image_profile or {})

    visual = profile.get("visual_style", {}) or {}

    return {
        "workspace_id": workspace_id,
        "version": profile.get("version", "1.0"),
        "featured_image": {
            "preferred_style": visual.get("preferred_style", "professional_realistic"),
            "aspect_ratio": "16:9"
        },
        "general_rules": [
            "Use realistic professional environments.",
            "Use natural lighting when possible.",
            "Prefer documentary-style photography.",
            "Represent adults in professional settings.",
            "Avoid exaggerated emotional expressions."
        ],
        "preferred_elements": visual.get("preferred_settings", []),
        "avoid_elements": visual.get("avoid", []),
        "polygraph_rules": [
            "Polygraph equipment may appear but should not dominate the image.",
            "Human interaction should remain central.",
            "Avoid unrealistic lie detector screens.",
            "Do not imply guaranteed truth detection.",
            "Do not imply legal authority."
        ],
        "industry_specific": {},
        "topic_mapping": {}
    }


def update_workspaces_json(workspace_id, folder_path, domain, language, country, market_code, dry_run=False):
    if WORKSPACES_FILE.exists():
        data = load_json(WORKSPACES_FILE)
    else:
        data = {"workspaces": []}

    workspaces = data.setdefault("workspaces", [])

    existing = None
    for workspace in workspaces:
        if workspace.get("workspace_id") == workspace_id:
            existing = workspace
            break

    payload = {
        "workspace_id": workspace_id,
        "folder_path": folder_path,
        "draft_registry_path": f"sites/local_sites/{market_code}/draft_registry.json",
        "domain": domain,
        "language": language,
        "country": country,
        "market_code": market_code,
        "wordpress": {
            "enabled": False,
            "username_env": f"WP_{market_code.upper()}_USERNAME",
            "password_env": f"WP_{market_code.upper()}_PASSWORD",
            "default_status": "draft",
            "content_endpoint": "pages"
        }
    }

    if existing:
        existing.update({k: v for k, v in payload.items() if k not in ["wordpress"]})
        existing.setdefault("wordpress", payload["wordpress"])
        action = "updated"
    else:
        workspaces.append(payload)
        action = "created"

    if not dry_run:
        save_json(WORKSPACES_FILE, data)

    return action


def bootstrap_workspace(args):
    target_id = args.workspace_id
    template_id = args.template

    target_dir = workspace_folder(target_id)
    template_dir = workspace_folder(template_id)

    market_code = target_id.split(".", 1)[-1]
    template_market_code = template_id.split(".", 1)[-1]

    domain = args.domain.rstrip("/")
    language = args.language
    locale = args.locale
    country = args.country

    replacements = {
        template_id: target_id,
        f"local.{template_market_code}": target_id,
        "https://poligrafoangola.com": domain,
        "poligrafoangola.com": domain.replace("https://", "").replace("http://", ""),
        "Angola": country,
        "AO": market_code.upper(),
        "pt-PT": locale,
        "pt": language,
        "Portuguese": "Spanish" if language.startswith("es") else language,
        "Português": "Español" if language.startswith("es") else language
    }

    target_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "created": [],
        "updated": [],
        "skipped_existing": [],
        "missing_template": [],
        "validated": [],
        "errors": []
    }

    # Foundation files
    for filename in FOUNDATION_FILES:
        target_path = target_dir / filename

        if target_path.exists() and not args.overwrite:
            report["skipped_existing"].append(filename)
            continue

        template_path = template_dir / filename

        if filename == "image_guidelines.json" and not template_path.exists():
            image_profile_path = target_dir / "image_profile.json"
            if image_profile_path.exists():
                data = convert_image_profile_to_guidelines(load_json(image_profile_path), target_id)
                save_json(target_path, data)
                report["created"].append(filename)
                continue

        if template_path.exists():
            data = load_json(template_path)
            data = replace_values(data, replacements)
        else:
            data = {}
            report["missing_template"].append(filename)

        if filename == "page_presentation.json":
            data = normalize_page_presentation(data, target_id, domain, language, country)
        elif filename == "market_intelligence.json":
            data = normalize_market_intelligence(data, target_id, domain)
        elif filename == "market_intelligence_candidates.json":
            data = normalize_market_candidates(data, target_id, domain)
        elif filename == "site_content_memory.json":
            data = normalize_site_memory(data, target_id, domain, language, market_code)
        elif filename == "image_guidelines.json":
            data = normalize_image_guidelines(data, target_id)

        save_json(target_path, data)
        report["updated" if target_path.exists() else "created"].append(filename)

    # Runtime files
    for filename in RUNTIME_EMPTY_FILES:
        target_path = target_dir / filename

        if target_path.exists() and not args.overwrite_runtime:
            report["skipped_existing"].append(filename)
            continue

        payload = make_empty_runtime_payload(filename, target_id)
        save_json(target_path, payload)
        report["updated" if target_path.exists() else "created"].append(filename)

    workspaces_action = update_workspaces_json(
        workspace_id=target_id,
        folder_path=f"sites/local_sites/{market_code}",
        domain=domain,
        language=language,
        country=country,
        market_code=market_code,
        dry_run=args.dry_run
    )

    report["updated"].append(f"data/workspaces.json ({workspaces_action})")

    # Validate JSON files
    for path in sorted(target_dir.glob("*.json")):
        try:
            load_json(path)
            report["validated"].append(path.name)
        except Exception as e:
            report["errors"].append(f"{path.name}: {e}")

    return report


def print_report(report):
    print("\n=== Workspace Bootstrap Report ===")

    for key in ["created", "updated", "skipped_existing", "missing_template", "validated", "errors"]:
        items = report.get(key, [])
        print(f"\n{key}: {len(items)}")
        for item in items:
            print(f"- {item}")


def main():
    parser = argparse.ArgumentParser(description="Bootstrap a Sofia local workspace from a template workspace.")
    parser.add_argument("workspace_id", help="Target workspace id, e.g. local.es")
    parser.add_argument("--template", default="local.ao", help="Template workspace id, default local.ao")
    parser.add_argument("--domain", required=True, help="Target domain, e.g. https://poligrafoespana.com")
    parser.add_argument("--language", required=True, help="Target language, e.g. es")
    parser.add_argument("--locale", required=True, help="Target locale, e.g. es-ES")
    parser.add_argument("--country", required=True, help="Target country, e.g. Spain")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing foundation files")
    parser.add_argument("--overwrite-runtime", action="store_true", help="Overwrite runtime queue/registry files")
    parser.add_argument("--dry-run", action="store_true", help="Prepare report without updating data/workspaces.json")

    args = parser.parse_args()
    report = bootstrap_workspace(args)
    print_report(report)

    if report.get("errors"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()