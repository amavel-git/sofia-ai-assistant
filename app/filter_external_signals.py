import json
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]

WORKSPACE_ID = "local.ao"
LOCAL_SITE_PATH = SOFIA_ROOT / "sites" / "local_sites" / "ao"

SIGNALS_FILE = LOCAL_SITE_PATH / "external_signals.json"
GLOBAL_RULES_FILE = SOFIA_ROOT / "data" / "signal_filter_rules.json"
LOCAL_TERMS_FILE = LOCAL_SITE_PATH / "local_signal_terms.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def detect_concepts(text: str, concept_terms: dict):
    text_lower = text.lower()
    matched_concepts = []

    for concept, terms in concept_terms.items():
        for term in terms:
            if term in text_lower:
                matched_concepts.append(concept)
                break

    return matched_concepts


def classify_signal(concepts, rules):
    reject = set(rules["concept_filters"]["reject_concepts"])
    business = set(rules["concept_filters"]["business_concepts"])
    informational = set(rules["concept_filters"]["informational_concepts"])
    high_intent = set(rules["concept_filters"]["high_intent_concepts"])

    concepts_set = set(concepts)

    if concepts_set & reject:
        return "noise", "low"

    if concepts_set & high_intent:
        return "relevant", "high"

    if concepts_set & business:
        return "relevant", "medium"

    if concepts_set & informational:
        return "relevant", "medium"

    return "needs_review", "low"


def main():
    print("=== Sofia: Filter External Signals ===\n")

    signals_data = load_json(SIGNALS_FILE)
    global_rules = load_json(GLOBAL_RULES_FILE)
    local_terms_data = load_json(LOCAL_TERMS_FILE)

    signals = signals_data.get("signals", [])
    concept_terms = local_terms_data.get("concept_terms", {})

    updated = 0

    for signal in signals:
        if signal.get("status") != "new":
            continue

        raw_text = signal.get("raw_signal", "")

        concepts = detect_concepts(raw_text, concept_terms)
        classification, priority = classify_signal(concepts, global_rules)

        signal["detected_concepts"] = concepts
        signal["classification"] = classification
        signal["priority_hint"] = priority
        signal["status"] = "processed"

        updated += 1

        print(f"{signal['id']}: {raw_text}")
        print(f"  Concepts: {concepts}")
        print(f"  Classification: {classification}")
        print(f"  Priority: {priority}\n")

    signals_data["signals"] = signals
    save_json(SIGNALS_FILE, signals_data)

    print(f"\nSignals processed: {updated}")


if __name__ == "__main__":
    main()