import json
from pathlib import Path
from datetime import datetime, timezone


SOFIA_ROOT = Path(__file__).resolve().parents[1]

WORKSPACE_ID = "local.ao"
LOCAL_SITE_PATH = SOFIA_ROOT / "sites" / "local_sites" / "ao"

SIGNALS_FILE = LOCAL_SITE_PATH / "external_signals.json"
OPPORTUNITIES_FILE = LOCAL_SITE_PATH / "external_opportunities.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_next_opportunity_id(opportunities: list, country_code: str) -> str:
    max_num = 0
    prefix = f"OPP-{country_code}-"

    for opp in opportunities:
        opp_id = opp.get("id", "")
        if opp_id.startswith(prefix):
            try:
                num = int(opp_id.replace(prefix, ""))
                max_num = max(max_num, num)
            except ValueError:
                continue

    return f"{prefix}{max_num + 1:03d}"


def opportunity_exists(opportunities: list, topic: str) -> bool:
    topic_norm = topic.strip().lower()

    for opp in opportunities:
        if opp.get("topic", "").strip().lower() == topic_norm:
            return True

    return False


def map_priority(priority_hint: str) -> str:
    if priority_hint == "high":
        return "high"
    if priority_hint == "medium":
        return "medium"
    return "low"


def build_opportunity(signal: dict, opp_id: str) -> dict:
    topic = signal.get("raw_signal", "")
    priority_hint = signal.get("priority_hint", "low")

    return {
        "id": opp_id,
        "created_at": now(),
        "updated_at": now(),
        "country": signal.get("country"),
        "language": signal.get("language"),
        "source": signal.get("source"),
        "source_signal_id": signal.get("id"),
        "topic": topic,
        "opportunity_type": "blog_topic",
        "recommended_content_type": "blog_post",
        "intent_type": "informational",
        "priority": map_priority(priority_hint),
        "confidence": 0.7,
        "status": "new",
        "related_keywords": [topic],
        "detected_concepts": signal.get("detected_concepts", []),
        "business_reason": "Detected from real user search behavior (Google suggestions).",
        "risk_notes": [],
        "recommended_action": "send_to_examiner_for_validation",
        "cannibalization_status": "unchecked",
        "local_topic_status": "unchecked",
        "review_status": "pending_examiner"
    }


def main():
    print("=== Sofia: Convert Signals to Opportunities ===\n")

    signals_data = load_json(SIGNALS_FILE)
    opportunities_data = load_json(OPPORTUNITIES_FILE)

    signals = signals_data.get("signals", [])
    opportunities = opportunities_data.get("opportunities", [])

    created = 0
    country_code = WORKSPACE_ID.split(".")[-1].upper()

    for signal in signals:
        if signal.get("status") != "processed":
            continue

        if signal.get("classification") != "relevant":
            continue

        topic = signal.get("raw_signal", "")

        if opportunity_exists(opportunities, topic):
            continue

        opp_id = get_next_opportunity_id(opportunities, country_code)

        new_opp = build_opportunity(signal, opp_id)
        opportunities.append(new_opp)

        signal["converted_to_opportunity"] = True
        signal["opportunity_id"] = opp_id

        created += 1

        print(f"Created {opp_id} from signal: {topic}")

    opportunities_data["opportunities"] = opportunities
    signals_data["signals"] = signals

    save_json(OPPORTUNITIES_FILE, opportunities_data)
    save_json(SIGNALS_FILE, signals_data)

    print(f"\nTotal opportunities created: {created}")


if __name__ == "__main__":
    main()