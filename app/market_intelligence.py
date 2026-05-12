import json
from datetime import datetime, timezone
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]
SITES_ROOT = SOFIA_ROOT / "sites"
LOCAL_SITES_ROOT = SITES_ROOT / "local_sites"


def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_workspace_folder(workspace_id):
    """
    Converts workspace_id like local.ao into:
    sites/local_sites/ao
    """
    if not workspace_id.startswith("local."):
        raise ValueError(f"Unsupported workspace_id format: {workspace_id}")

    workspace_slug = workspace_id.split(".", 1)[1]
    workspace_folder = LOCAL_SITES_ROOT / workspace_slug

    if not workspace_folder.exists():
        raise FileNotFoundError(f"Workspace folder not found: {workspace_folder}")

    return workspace_folder


def get_market_intelligence_path(workspace_id):
    return get_workspace_folder(workspace_id) / "market_intelligence.json"


def default_market_intelligence(workspace_id, domain=""):
    return {
        "version": "1.0",
        "workspace_id": workspace_id,
        "domain": domain,
        "last_updated": utc_now_iso(),
        "schema_notes": {
            "purpose": "External market, competitor, terminology, and opportunity intelligence only. Not approved drafting content.",
            "drafting_rule": "Do not use competitor or market intelligence as direct drafting source material unless separately approved into controlled knowledge blocks."
        },
        "competitors": [],
        "market_topics": [],
        "local_language_notes": {
            "primary_language": "",
            "secondary_languages": [],
            "formal_terms": [],
            "common_terms": [],
            "high_conversion_terms": [],
            "terms_to_avoid": [],
            "regional_variations": [],
            "notes": []
        },
        "opportunity_rules": {
            "preferred_content_types": [],
            "avoid_topics": [],
            "sensitive_topics": [],
            "requires_manual_review": True
        },
        "source_notes": []
    }


def load_market_intelligence(workspace_id):
    path = get_market_intelligence_path(workspace_id)

    if not path.exists():
        raise FileNotFoundError(
            f"market_intelligence.json not found for {workspace_id}: {path}"
        )

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if data.get("workspace_id") != workspace_id:
        raise ValueError(
            f"Workspace mismatch in {path}: expected {workspace_id}, found {data.get('workspace_id')}"
        )

    return data


def save_market_intelligence(workspace_id, data):
    path = get_market_intelligence_path(workspace_id)

    if data.get("workspace_id") != workspace_id:
        raise ValueError(
            f"Refusing to save market intelligence with mismatched workspace_id: {data.get('workspace_id')}"
        )

    data["last_updated"] = utc_now_iso()

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return path


def ensure_market_intelligence_exists(workspace_id, domain=""):
    path = get_market_intelligence_path(workspace_id)

    if path.exists():
        return path

    data = default_market_intelligence(workspace_id, domain=domain)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return path


def normalize_domain(domain):
    domain = domain.strip().lower()
    domain = domain.replace("https://", "").replace("http://", "")
    domain = domain.strip("/")
    return domain


def competitor_exists(data, domain):
    normalized = normalize_domain(domain)

    for competitor in data.get("competitors", []):
        existing = normalize_domain(competitor.get("domain", ""))
        if existing == normalized:
            return True

    return False


def get_market_intelligence_candidates_path(workspace_id):
    return get_workspace_folder(workspace_id) / "market_intelligence_candidates.json"


def load_market_intelligence_candidates(workspace_id):
    path = get_market_intelligence_candidates_path(workspace_id)

    if not path.exists():
        raise FileNotFoundError(
            f"market_intelligence_candidates.json not found for {workspace_id}: {path}"
        )

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if data.get("workspace_id") != workspace_id:
        raise ValueError(
            f"Workspace mismatch in candidate intelligence file: expected {workspace_id}, found {data.get('workspace_id')}"
        )

    return data


def save_market_intelligence_candidates(workspace_id, data):
    path = get_market_intelligence_candidates_path(workspace_id)

    if data.get("workspace_id") != workspace_id:
        raise ValueError(
            f"Refusing to save candidate intelligence with mismatched workspace_id: {data.get('workspace_id')}"
        )

    data["last_updated"] = utc_now_iso()

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return path


def ensure_market_intelligence_candidates_exists(workspace_id, domain=""):
    path = get_market_intelligence_candidates_path(workspace_id)

    if path.exists():
        return path

    data = {
        "version": "1.0",
        "workspace_id": workspace_id,
        "domain": domain,
        "last_updated": utc_now_iso(),
        "purpose": (
            "Reviewable candidate intelligence only. "
            "Nothing in this file is trusted until promoted into market_intelligence.json."
        ),
        "candidate_competitors": [],
        "candidate_market_topics": [],
        "candidate_language_notes": [],
        "candidate_opportunity_rules": [],
        "candidate_positioning_observations": [],
        "review_log": []
    }

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return path