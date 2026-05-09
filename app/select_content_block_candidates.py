#!/usr/bin/env python3
import json
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone


SOFIA_ROOT = Path(__file__).resolve().parents[1]

INPUT_FILE = SOFIA_ROOT / "data" / "source_knowledge" / "content_block_candidates.json"
OUTPUT_FILE = SOFIA_ROOT / "data" / "source_knowledge" / "review_content_block_candidates.json"

MAX_PER_LANGUAGE_CATEGORY = 5
MIN_WORDS = 120
MAX_WORDS = 260

PRIORITY_CATEGORIES = [
    "polygraph_process",
    "examiner_qualifications",
    "ethics",
    "quality_standards",
    "confidentiality",
    "limitations",
    "price_variables",
    "theft",
    "infidelity",
    "legal_tests",
    "sexual_harassment",
    "pre_employment",
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def normalize_space(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def word_count(text):
    return len([w for w in normalize_space(text).split(" ") if w.strip()])


def fingerprint(text):
    text = normalize_space(text).lower()
    text = re.sub(r"[^a-z0-9à-ÿа-яёçğıöşü]+", " ", text)
    words = text.split()
    return " ".join(words[:80])


def score_candidate(candidate):
    score = 0

    category = candidate.get("category")
    text = candidate.get("text", "")
    wc = word_count(text)
    risk = candidate.get("risk_level", "")
    tags = candidate.get("tags", [])
    source_title = candidate.get("source_title", "") or ""

    if category in PRIORITY_CATEGORIES:
        score += 30

    if 140 <= wc <= 240:
        score += 20
    elif 120 <= wc <= 260:
        score += 10

    if risk in {"standard", "guarded_safe"}:
        score += 15
    elif risk == "sensitive_context":
        score += 8
    elif risk == "requires_manual_review":
        score -= 20

    useful_tags = {
        "procedure",
        "methodology",
        "ethics",
        "privacy",
        "confidentiality",
        "limitations",
        "quality",
        "professional_standards",
        "corporate_investigation",
        "specific_issue",
        "pricing",
        "quote",
    }

    score += len(set(tags).intersection(useful_tags)) * 3

    if source_title:
        score += 3

    risky_phrases = [
        "100%",
        "garantizado",
        "garantido",
        "guaranteed",
        "infalível",
        "infalible",
        "infallible",
        "infaillible",
        "legal proof",
        "prueba legal",
        "prova legal",
    ]

    text_lower = text.lower()
    if any(phrase in text_lower for phrase in risky_phrases):
        score -= 30

    return score


def main():
    print("=== Sofia: Select Content Block Candidates for Review ===\n")

    if not INPUT_FILE.exists():
        print(f"ERROR: Input file not found: {INPUT_FILE}")
        return

    data = load_json(INPUT_FILE)
    candidates = data.get("candidates", [])

    selected = []
    seen_fingerprints = set()
    buckets = defaultdict(list)

    for candidate in candidates:
        category = candidate.get("category")
        language = candidate.get("language")
        text = candidate.get("text", "")

        if category not in PRIORITY_CATEGORIES:
            continue

        wc = word_count(text)

        if wc < MIN_WORDS:
            continue

        if wc > MAX_WORDS:
            continue

        fp = fingerprint(text)
        if fp in seen_fingerprints:
            continue

        seen_fingerprints.add(fp)

        buckets[(language, category)].append(candidate)

    for key, items in buckets.items():
        items.sort(key=score_candidate, reverse=True)

        for candidate in items[:MAX_PER_LANGUAGE_CATEGORY]:
            candidate = dict(candidate)
            candidate["review_status"] = "needs_human_review"
            candidate["selection_score"] = score_candidate(candidate)
            selected.append(candidate)

    selected.sort(
        key=lambda c: (
            str(c.get("language")),
            PRIORITY_CATEGORIES.index(c.get("category"))
            if c.get("category") in PRIORITY_CATEGORIES
            else 999,
            -int(c.get("selection_score", 0)),
        )
    )

    output = {
        "version": "0.1",
        "created_for": "Sofia SEO Assistant",
        "created_at": now_iso(),
        "source_file": str(INPUT_FILE.relative_to(SOFIA_ROOT)),
        "approved_for_drafting": False,
        "notes": [
            "These candidates were selected for human review.",
            "Do not use directly in Sofia drafting.",
            "Only approved candidates should be appended to data/approved_content_blocks.json.",
            "Approved blocks must be used as semantic guidance, not copy-paste text."
        ],
        "selection_rules": {
            "max_per_language_category": MAX_PER_LANGUAGE_CATEGORY,
            "min_words": MIN_WORDS,
            "max_words": MAX_WORDS,
            "priority_categories": PRIORITY_CATEGORIES,
        },
        "candidate_count": len(selected),
        "candidates": selected,
    }

    save_json(OUTPUT_FILE, output)

    print(f"Selected candidates: {len(selected)}")
    print(f"Saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()