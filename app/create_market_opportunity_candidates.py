import argparse
import json
from pathlib import Path
from datetime import datetime, timezone

from page_type_classifier import classify_page_type


ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = ROOT / "data" / "workspaces.json"

ALLOWED_ACTIONS = {
    "high_priority_gap",
    "consider_content"
}

EXCLUDED_ACTIONS = {
    "handled_by_other_workspace",
    "manual_review_required",
    "already_covered",
    "already_covered_monitor",
    "monitor",
    "low_priority_monitor",
    "out_of_scope"
}


TOPIC_LABELS = {
    "es-ES": {
        "methodology": "metodología del polígrafo",
        "appointment_booking": "solicitud de una prueba de polígrafo",
        "question_formulation": "formulación de preguntas",
        "technology": "tecnología y equipos de polígrafo",
        "false_positives": "falsos positivos",
        "inconclusive_results": "resultados inconclusos",
        "countermeasures": "contramedidas",
        "procedure": "procedimiento de la prueba de polígrafo",
        "anxiety_medication": "ansiedad, medicación y polígrafo",
        "city_cordoba": "Córdoba",
        "city_granada": "Granada",
        "city_toledo": "Toledo",
        "city_zaragoza": "Zaragoza",
        "city_alicante": "Alicante",
        "city_cadiz": "Cádiz",
        "city_las_palmas": "Las Palmas",
        "city_tenerife": "Tenerife",
        "city_valladolid": "Valladolid"
    }
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_workspace(workspaces, workspace_id):
    for workspace in workspaces.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def get_workspace_folder(workspace):
    return ROOT / workspace["folder_path"]


def load_existing_candidates(path):
    if not path.exists():
        return {
            "version": "1.0",
            "candidates": []
        }

    data = load_json(path)

    if isinstance(data, list):
        return {
            "version": "1.0",
            "candidates": data
        }

    data.setdefault("version", "1.0")
    data.setdefault("candidates", [])
    return data


def candidate_exists(existing_candidates, topic):
    for candidate in existing_candidates:
        if candidate.get("topic") == topic:
            return True
    return False


def make_candidate_id(existing_candidates, workspace_id):
    prefix = f"OPP-{workspace_id.split('.')[-1].upper()}"
    numbers = []

    for item in existing_candidates:
        cid = item.get("candidate_id") or item.get("opportunity_id") or ""
        if cid.startswith(prefix):
            try:
                numbers.append(int(cid.split("-")[-1]))
            except Exception:
                pass

    next_number = max(numbers) + 1 if numbers else 1
    return f"{prefix}-{next_number:04d}"


def load_language_profile(folder):
    try:
        return load_json(folder / "language_profile.json")
    except Exception:
        return {}


def get_workspace_language(folder):
    profile = load_language_profile(folder)
    return profile.get("locale", "en-US")


def get_topic_label(topic, locale, language_profile=None):
    language_profile = language_profile or {}
    labels = language_profile.get("topic_labels", {}) or {}

    if topic in labels:
        return labels.get(topic)

    fallback_labels = TOPIC_LABELS.get(locale, {})
    return fallback_labels.get(topic)


def topic_to_title(topic, locale, language_profile=None, page_type=""):
    title_map = {
        "methodology": "Página educativa sobre metodología del polígrafo",
        "appointment_booking": "Página sobre cómo solicitar una prueba de polígrafo",
        "city_cordoba": "Página local de prueba de polígrafo en Córdoba",
        "city_granada": "Página local de prueba de polígrafo en Granada",
        "city_toledo": "Página local de prueba de polígrafo en Toledo",
        "city_zaragoza": "Página local de prueba de polígrafo en Zaragoza",
        "city_alicante": "Página local de prueba de polígrafo en Alicante",
        "city_cadiz": "Página local de prueba de polígrafo en Cádiz",
        "city_valladolid": "Página local de prueba de polígrafo en Valladolid"
    }

    language_profile = language_profile or {}
    label = get_topic_label(topic, locale, language_profile)

    templates = language_profile.get("topic_title_templates", {}) or {}
    template = templates.get(page_type) or templates.get("default")

    if template and label:
        return template.replace("{topic_label}", label)

    if topic in title_map:
        return title_map[topic]

    if label:
        return f"Oportunidad de contenido sobre {label}"

    humanized = topic.replace("_", " ")

    if locale.startswith("es"):
        return f"Oportunidad de contenido sobre {humanized}"

    return f"Content opportunity: {humanized}"


def topic_to_content_type(topic):
    if topic.startswith("city_"):
        return "landing_page"

    if topic in ["methodology", "procedure", "question_formulation", "false_positives", "inconclusive_results"]:
        return "blog_post"

    if topic == "appointment_booking":
        return "service_page"

    return "blog_post"


def topic_to_priority(market_topic):
    action = market_topic.get("recommended_action")
    competitors = market_topic.get("competitor_coverage_count", 0)

    if action == "high_priority_gap":
        return "high"

    if competitors >= 6:
        return "medium_high"

    return "medium"


def create_candidate(workspace_id, market_topic, existing_candidates, locale, language_profile=None):
    language_profile = language_profile or {}
    topic = market_topic.get("topic", "")
    candidate_id = make_candidate_id(existing_candidates, workspace_id)

    content_type = topic_to_content_type(topic)

    preliminary_classification = classify_page_type(
        title=topic,
        topic=get_topic_label(topic, locale, language_profile) or topic,
        content_type=content_type,
    )

    page_type = preliminary_classification.get("page_type")

    title = topic_to_title(
        topic,
        locale,
        language_profile=language_profile,
        page_type=page_type
    )

    classification = classify_page_type(
        title=title,
        topic=get_topic_label(topic, locale, language_profile) or topic,
        content_type=content_type,
    )

    return {
        "candidate_id": candidate_id,
        "workspace_id": workspace_id,
        "source": "market_intelligence",
        "source_type": "market_topic_gap",
        "status": "candidate_for_review",
        "created_at": now_iso(),
        "topic": topic,
        "topic_label": get_topic_label(topic, locale, language_profile),
        "localized_topic": get_topic_label(topic, locale, language_profile),
        "title": title,
        "content_type": content_type,
        "page_type": classification.get("page_type"),
        "blueprint_id": classification.get("blueprint_id"),
        "intent_type": classification.get("intent_type"),
        "page_type_classification": {
            "confidence": classification.get("confidence"),
            "source": classification.get("classification_source"),
            "reason": classification.get("classification_reason")
        },
        "priority": topic_to_priority(market_topic),
        "recommended_action": market_topic.get("recommended_action"),
        "our_coverage_pages": market_topic.get("our_coverage_pages", 0),
        "competitor_coverage_count": market_topic.get("competitor_coverage_count", 0),
        "competitor_total_pages": market_topic.get("competitor_total_pages", 0),
        "competitors_covering": market_topic.get("competitors_covering", []),
        "rationale": (
            f"Competitors cover this topic on {market_topic.get('competitor_total_pages', 0)} pages "
            f"across {market_topic.get('competitor_coverage_count', 0)} competitor sites, "
            f"while our current coverage is {market_topic.get('our_coverage_pages', 0)} pages."
        ),
        "human_review_required": True,
        "notes": []
    }


def main():
    parser = argparse.ArgumentParser(description="Create reviewable market opportunity candidates from market_intelligence.json.")
    parser.add_argument("workspace_id", help="Workspace ID, e.g. local.es")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, args.workspace_id)

    if not workspace:
        print(f"Workspace not found: {args.workspace_id}")
        raise SystemExit(1)

    folder = get_workspace_folder(workspace)
    market_path = folder / "market_intelligence.json"
    candidates_path = folder / "market_intelligence_candidates.json"

    market = load_json(market_path)
    candidates_data = load_existing_candidates(candidates_path)
    existing_candidates = candidates_data.get("candidates", [])

    language_profile = load_language_profile(folder)
    locale = get_workspace_language(folder)

    created = []
    skipped = []

    for topic in market.get("market_topics", []):
        action = topic.get("recommended_action")
        topic_name = topic.get("topic")

        if action in EXCLUDED_ACTIONS:
            skipped.append((topic_name, action, "excluded_action"))
            continue

        if action not in ALLOWED_ACTIONS:
            skipped.append((topic_name, action, "not_allowed"))
            continue

        if candidate_exists(existing_candidates, topic_name):
            skipped.append((topic_name, action, "already_exists"))
            continue

        candidate = create_candidate(
            args.workspace_id,
            topic,
            existing_candidates + created,
            locale,
            language_profile=language_profile
        )
        created.append(candidate)

    print("\n=== Market Opportunity Candidate Creation ===")
    print(f"Workspace: {args.workspace_id}")
    print(f"Created: {len(created)}")
    print(f"Skipped: {len(skipped)}")

    if created:
        print("\nCreated candidates:")
        for c in created:
            print(f"- {c['candidate_id']} | {c['topic']} | {c['priority']} | {c['title']}")

    if args.dry_run:
        print("\nDry run only. No file updated.")
        return

    existing_candidates.extend(created)
    candidates_data["workspace_id"] = args.workspace_id
    candidates_data["last_updated"] = now_iso()
    candidates_data["candidates"] = existing_candidates

    save_json(candidates_path, candidates_data)
    print(f"\nUpdated: {candidates_path}")


if __name__ == "__main__":
    main()