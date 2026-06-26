import json
import re
import sys
from pathlib import Path

from page_blueprints import resolve_blueprint_id


SOFIA_ROOT = Path(__file__).resolve().parents[1]
PAGE_TYPE_RULES_FILE = SOFIA_ROOT / "data" / "page_type_rules.json"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_text(value: str) -> str:
    value = str(value or "").lower()
    value = re.sub(r"[^a-zA-ZÀ-ÿ0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def load_page_type_rules():
    if not PAGE_TYPE_RULES_FILE.exists():
        raise FileNotFoundError(f"Missing page type rules file: {PAGE_TYPE_RULES_FILE}")

    return load_json(PAGE_TYPE_RULES_FILE)


def score_rule(text: str, rule: dict) -> int:
    score = 0
    normalized_text = normalize_text(text)

    for signal in rule.get("signals", []):
        signal = normalize_text(signal)
        if signal and signal in normalized_text:
            score += int(rule.get("signal_weight", 10))

    for strong_signal in rule.get("strong_signals", []):
        strong_signal = normalize_text(strong_signal)
        if strong_signal and strong_signal in normalized_text:
            score += int(rule.get("strong_signal_weight", 25))

    return score


def classify_page_type(title="", topic="", keyword="", content_type="", user_requested_type=""):
    rules_data = load_page_type_rules()
    page_type_rules = rules_data.get("page_type_rules", {})

    text = " ".join([
        str(title or ""),
        str(topic or ""),
        str(keyword or ""),
        str(content_type or ""),
        str(user_requested_type or "")
    ])

    normalized_user_type = normalize_text(user_requested_type)

    # Respect explicit user/examiner intent if configured as alias.
    aliases = rules_data.get("explicit_type_aliases", {})
    for canonical_type, alias_list in aliases.items():
        for alias in alias_list:
            if normalize_text(alias) == normalized_user_type:
                blueprint_id = resolve_blueprint_id(page_type=canonical_type)
                return {
                    "page_type": canonical_type,
                    "blueprint_id": blueprint_id,
                    "intent_type": page_type_rules.get(canonical_type, {}).get("intent_type", ""),
                    "confidence": 0.98,
                    "classification_source": "explicit_user_type",
                    "classification_reason": f"Explicit user type matched alias: {alias}"
                }

    scored = []

    for page_type, rule in page_type_rules.items():
        score = score_rule(text, rule)

        if score <= 0:
            continue

        scored.append((score, page_type, rule))

    if scored:
        priority_order = rules_data.get("page_type_priority_order", [])
        priority_map = {
            page_type: index
            for index, page_type in enumerate(priority_order)
        }

        priority_bonus = rules_data.get("page_type_priority_bonus", {})

        # Sort by adjusted score:
        # raw score + configured priority bonus.
        # This prevents broad pillar terms from overriding specific intent
        # such as pricing, city, authority, or educational intent.
        scored.sort(
            key=lambda item: (
                item[0] + int(priority_bonus.get(item[1], 0)),
                -priority_map.get(item[1], 999)
            ),
            reverse=True
        )

        best_score, page_type, rule = scored[0]

        confidence = min(0.95, 0.5 + (best_score / 100))

        return {
            "page_type": page_type,
            "blueprint_id": resolve_blueprint_id(page_type=page_type),
            "intent_type": rule.get("intent_type", ""),
            "confidence": round(confidence, 2),
            "classification_source": "deterministic_rules",
            "classification_reason": f"Matched configured signals with score {best_score}."
        }

    fallback_type = rules_data.get("default_page_type", "blog_post")

    return {
        "page_type": fallback_type,
        "blueprint_id": resolve_blueprint_id(page_type=fallback_type),
        "intent_type": page_type_rules.get(fallback_type, {}).get("intent_type", "informational"),
        "confidence": 0.45,
        "classification_source": "fallback",
        "classification_reason": "No configured page type signals matched."
    }


def classify_opportunity(opportunity: dict):
    return classify_page_type(
        title=opportunity.get("title", ""),
        topic=opportunity.get("topic_label") or opportunity.get("topic", ""),
        keyword=opportunity.get("target_keyword") or opportunity.get("focus_keyphrase", ""),
        content_type=opportunity.get("content_type", ""),
        user_requested_type=opportunity.get("requested_page_type", "")
    )


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print('python app/page_type_classifier.py "metodología del polígrafo"')
        return

    text = " ".join(sys.argv[1:])
    result = classify_page_type(title=text, topic=text, keyword=text)

    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
