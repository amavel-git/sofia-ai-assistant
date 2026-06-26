import json
import sys
from pathlib import Path
from datetime import datetime, timezone

from intake_intelligence_normalizer import normalize_opportunity_for_intake
from opportunity_intelligence import analyze_opportunity


SOFIA_ROOT = Path(__file__).resolve().parents[1]
SITES_ROOT = SOFIA_ROOT / "sites"
INTAKE_FILE = SITES_ROOT / "content_intake.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return {"opportunities": data}

    return data


def save_json(path: Path, data: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def resolve_workspace(workspace_id: str) -> dict:
    """
    Workspace-aware resolver.

    Expected local workspace format:
      local.es -> sites/local_sites/es
      local.ao -> sites/local_sites/ao
      local.pt -> sites/local_sites/pt
    """

    if not workspace_id:
        raise ValueError("Missing workspace_id")

    if workspace_id.startswith("local."):
        country_code = workspace_id.split(".", 1)[1]
        workspace_path = Path("sites") / "local_sites" / country_code
        local_site_path = SOFIA_ROOT / workspace_path

        if not local_site_path.exists():
            raise FileNotFoundError(f"Workspace path not found: {local_site_path}")

        workspace_settings = load_workspace_settings(local_site_path)

        domain = (
            workspace_settings.get("domain")
            or workspace_settings.get("site_target")
            or workspace_settings.get("website")
            or ""
        )

        language = (
            workspace_settings.get("language")
            or workspace_settings.get("default_language")
            or infer_language_from_country(country_code)
        )

        review_queue_name = f"{country_code}_local_review_queue"

        return {
            "workspace_id": workspace_id,
            "workspace_type": "local_market",
            "workspace_path": str(workspace_path).replace("\\", "/"),
            "local_site_path": local_site_path,
            "opportunities_file": local_site_path / "external_opportunities.json",
            "site_target": domain,
            "language": language,
            "review_queue": review_queue_name,
            "country_code": country_code,
        }

    raise ValueError(f"Unsupported workspace_id format: {workspace_id}")


def load_workspace_settings(local_site_path: Path) -> dict:
    """
    Best-effort loader. Sofia workspaces may not all use the same settings file yet.
    This keeps the converter operational while the workspace schema is being stabilized.
    """

    candidate_files = [
        "workspace_settings.json",
        "site_settings.json",
        "site_profile.json",
        "local_content_profile.json",
        "market_intelligence.json",
    ]

    merged = {}

    for filename in candidate_files:
        path = local_site_path / filename
        if not path.exists():
            continue

        try:
            data = load_json(path)
        except Exception:
            continue

        if isinstance(data, dict):
            merged.update(flatten_known_settings(data))

    return merged


def flatten_known_settings(data: dict) -> dict:
    """
    Extract common workspace values from different Sofia JSON structures.
    """

    output = {}

    for key in [
        "domain",
        "site_target",
        "website",
        "language",
        "default_language",
        "workspace_id",
    ]:
        if data.get(key):
            output[key] = data.get(key)

    # market_intelligence.json often stores domain at the root.
    if data.get("domain"):
        output["domain"] = data["domain"]

    # Some profile files may store nested site data.
    site = data.get("site") or data.get("website_profile") or {}
    if isinstance(site, dict):
        for key in ["domain", "site_target", "website", "language", "default_language"]:
            if site.get(key):
                output[key] = site.get(key)

    return output


def infer_language_from_country(country_code: str) -> str:
    defaults = {
        "ao": "pt",
        "pt": "pt",
        "br": "pt-BR",
        "es": "es",
        "fr": "fr",
        "be": "fr",
        "tr": "tr",
        "in": "en",
    }
    return defaults.get(country_code, "en")


def get_next_intake_id(content_ideas: list) -> str:
    max_num = 0

    for item in content_ideas:
        intake_id = item.get("intake_id", "")
        if intake_id.startswith("INTAKE-"):
            try:
                num = int(intake_id.replace("INTAKE-", ""))
                max_num = max(max_num, num)
            except ValueError:
                continue

    return f"INTAKE-{max_num + 1:04d}"


def get_opportunity_id(opportunity: dict) -> str:
    return (
        opportunity.get("opportunity_id")
        or opportunity.get("id")
        or opportunity.get("candidate_id")
        or opportunity.get("source_candidate_id")
        or ""
    )


def already_converted(content_ideas: list, opportunity_id: str) -> bool:
    for item in content_ideas:
        if item.get("source_opportunity_id") == opportunity_id:
            return True
    return False


def build_intake_from_opportunity(opportunity: dict, intake_id: str, workspace: dict) -> dict:
    related_keywords = opportunity.get("related_keywords", [])

    seo_brief = opportunity.get("seo_brief", {}) or {}

    visible_topic = (
        opportunity.get("localized_topic")
        or opportunity.get("topic_label")
        or opportunity.get("workspace_language_topic")
        or opportunity.get("raw_signal")
        or opportunity.get("title")
        or opportunity.get("topic")
        or ""
    )

    intake_intelligence = normalize_opportunity_for_intake(opportunity, workspace)
    opportunity_intelligence = analyze_opportunity(opportunity, workspace)

    target_keyword = (
        opportunity_intelligence.get("recommended_focus_keyphrase")
        or intake_intelligence.get("focus_keyphrase")
        or seo_brief.get("focus_keyphrase")
        or opportunity.get("target_keyword")
        or opportunity.get("primary_keyword")
        or visible_topic
    )

    opportunity_id = get_opportunity_id(opportunity)

    return {
        "intake_id": intake_id,
        "created_at": today(),
        "created_by": "sofia_external_intelligence",
        "workspace_type": workspace["workspace_type"],
        "workspace_id": workspace["workspace_id"],
        "workspace_path": workspace["workspace_path"],
        "language": opportunity.get("language", workspace["language"]),
        "site_target": workspace["site_target"],
        "content_type": (
            opportunity.get("recommended_content_type")
            or opportunity.get("content_type")
            or "service_page"
        ),
        "idea_title": (
            opportunity_intelligence.get("recommended_h1")
            or intake_intelligence.get("page_h1")
            or seo_brief.get("page_title")
            or visible_topic
        ),
        "normalized_title": opportunity_intelligence.get("recommended_title", ""),
        "page_h1": opportunity_intelligence.get("recommended_h1", ""),
        "issue": opportunity_intelligence.get("issue", ""),
        "sector": opportunity_intelligence.get("sector", ""),
        "sector_id": opportunity_intelligence.get("sector_id", ""),
        "service_angle": opportunity_intelligence.get("service_angle", ""),
        "topic_family": opportunity_intelligence.get("topic_family", ""),
        "visual_topic_family": opportunity_intelligence.get("visual_topic_family", ""),
        "recommended_seo_title": opportunity_intelligence.get("recommended_seo_title", ""),
        "recommended_meta_description": opportunity_intelligence.get("recommended_meta_description", ""),
        "topic": opportunity.get("topic", ""),
        "topic_label": opportunity.get("topic_label", ""),
        "localized_topic": opportunity.get("localized_topic", ""),
        "idea_summary": (
            opportunity.get("business_reason")
            or opportunity.get("rationale")
            or opportunity.get("notes")
            or ""
        ),
        "target_keyword": target_keyword,
        "secondary_keywords": related_keywords[1:] if isinstance(related_keywords, list) else [],
        "search_intent": opportunity.get("intent_type") or opportunity.get("intent") or "informational_transactional",

        "page_type": opportunity.get("page_type"),
        "blueprint_id": opportunity.get("blueprint_id"),
        "intent_type": opportunity.get("intent_type"),

        "page_type_classification": opportunity.get(
            "page_type_classification",
            {}
        ),

        "suggested_slug": (
            opportunity_intelligence.get("recommended_slug")
            or intake_intelligence.get("suggested_slug")
            or opportunity.get("suggested_slug", "")
        ),
        "source": "external_intelligence",
        "source_platform": opportunity.get("source", ""),
        "source_opportunity_id": opportunity_id,
        "priority": opportunity.get("priority", "normal"),
        "status": "new",
        "cannibalization_check": {
            "checked": False,
            "result": "not_checked",
            "notes": ""
        },
        "draft_conversion": {
            "converted": False,
            "draft_id": "",
            "converted_at": ""
        },
        "review_routing": {
            "target_queue": workspace["review_queue"],
            "routed": False,
            "routed_at": ""
        },
        "notes": "Created automatically from approved Sofia external opportunity.",
        "intake_intelligence": intake_intelligence,
        "opportunity_intelligence": opportunity_intelligence,
        "seo_brief": opportunity.get("seo_brief", {}),
        "content_strategy_brief": opportunity.get("content_strategy_brief", {}),
        "draft_input": opportunity.get("draft_input", {})
    }


def main():
    print("=== Sofia: Convert Approved Opportunities to Intake ===\n")

    if len(sys.argv) < 2:
        raise SystemExit("Usage: python app/convert_opportunity_to_intake.py <workspace_id> [--refresh-intelligence]")

    refresh_intelligence = "--refresh-intelligence" in sys.argv

    workspace_id = sys.argv[1]
    workspace = resolve_workspace(workspace_id)

    print(f"Workspace: {workspace['workspace_id']}")
    print(f"Workspace path: {workspace['workspace_path']}")
    print(f"Opportunities file: {workspace['opportunities_file']}")
    print(f"Site target: {workspace['site_target'] or '(missing)'}")
    print(f"Language: {workspace['language']}\n")

    opportunities_data = load_json(workspace["opportunities_file"])
    intake_data = load_json(INTAKE_FILE)

    opportunities = opportunities_data.get("opportunities", [])
    content_ideas = intake_data.get("content_ideas", [])

    if refresh_intelligence:
        opportunities_by_id = {
            get_opportunity_id(opp): opp
            for opp in opportunities
            if get_opportunity_id(opp)
        }

        refreshed = 0

        for item in content_ideas:
            opportunity_id = item.get("source_opportunity_id", "")
            if not opportunity_id:
                continue

            opp = opportunities_by_id.get(opportunity_id)
            if not opp:
                continue

            item["intake_intelligence"] = normalize_opportunity_for_intake(
                opp,
                workspace,
            )
            item["opportunity_intelligence"] = analyze_opportunity(
                opp,
                workspace,
            )
            item["content_strategy_brief"] = opp.get("content_strategy_brief", {})
            refreshed += 1

        intake_data["content_ideas"] = content_ideas
        save_json(INTAKE_FILE, intake_data)

        print("Intake intelligence refresh completed.")
        print(f"Entries refreshed: {refreshed}")
        return

    approved = [
        opp for opp in opportunities
        if opp.get("status") == "approved"
        and opp.get("review_status") == "approved_by_examiner"
    ]

    if not approved:
        print("No approved opportunities ready for intake conversion.")
        return

    created_count = 0

    for opp in approved:
        opportunity_id = get_opportunity_id(opp)

        if not opportunity_id:
            print("Skipped opportunity with missing opportunity_id/id/candidate_id.")
            continue

        if already_converted(content_ideas, opportunity_id):
            print(f"Skipped {opportunity_id}: already exists in content_intake.json")
            continue

        intake_id = get_next_intake_id(content_ideas)
        intake_entry = build_intake_from_opportunity(opp, intake_id, workspace)

        content_ideas.append(intake_entry)

        opp["status"] = "converted_to_intake"
        opp["review_status"] = "intake_created"
        opp["intake_id"] = intake_id
        opp["converted_to_intake_at"] = now_utc()

        print(f"Created {intake_id} from {opportunity_id}")
        created_count += 1

    intake_data["content_ideas"] = content_ideas
    opportunities_data["workspace_id"] = workspace["workspace_id"]
    opportunities_data["opportunities"] = opportunities

    save_json(INTAKE_FILE, intake_data)
    save_json(workspace["opportunities_file"], opportunities_data)

    print("\nConversion completed.")
    print(f"New intake entries created: {created_count}")


if __name__ == "__main__":
    main()