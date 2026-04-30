import json
import re
import sys
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]
DRAFT_REGISTRY_FILE = SOFIA_ROOT / "sites" / "draft_registry.json"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_draft(drafts, draft_id):
    for draft in drafts:
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def count_tag(content, tag):
    return len(re.findall(f"<{tag}", content, re.IGNORECASE))


def detect_english_headings(content):
    english_words = ["practical", "examples", "introduction"]
    issues = []

    for word in english_words:
        if re.search(rf"<h[1-3][^>]*>.*{word}.*</h[1-3]>", content, re.IGNORECASE):
            issues.append(f"English heading detected: {word}")

    return issues

def load_language_profile_for_draft(draft):
    workspace_path = draft.get("workspace_path", "")
    if not workspace_path:
        return {}

    profile_path = SOFIA_ROOT / workspace_path / "language_profile.json"

    if not profile_path.exists():
        return {}

    return load_json(profile_path)

def validate_word_count(content, language_profile):
    issues = []

    quality_rules = language_profile.get("content_quality_rules", {})
    minimum_word_count = quality_rules.get("minimum_word_count", 800)

    text = re.sub(r"<[^>]+>", " ", content)
    words = re.findall(r"\b\w+\b", text, re.UNICODE)

    if len(words) < minimum_word_count:
        issues.append(f"Content too short: {len(words)} words. Minimum required: {minimum_word_count}")

    return issues

def detect_invalid_tags(content):
    issues = []

    if "<soft_contact>" in content:
        issues.append("Invalid custom tag detected: <soft_contact>")

    if "</br>" in content:
        issues.append("Invalid HTML tag detected: </br>")

    return issues


def detect_risky_claims(content, language_profile):
    issues = []

    risky_rules = language_profile.get("risky_phrase_rules", {})
    risky_patterns = risky_rules.get("forbidden_phrases", [])

    fallback_patterns = [
        "100%",
        "guaranteed",
        "certified",
        "legally accepted",
        "legally admissible"
    ]

    for pattern in risky_patterns + fallback_patterns:
        if re.search(re.escape(pattern), content, re.IGNORECASE):
            issues.append(f"Risky claim detected: {pattern}")

    return issues


def validate_faq(content):
    issues = []

    faq_heading_patterns = [
        r"perguntas frequentes",
        r"frequentes perguntas",
        r"perguntas e respostas",
        r"faq",
        r"frequently asked questions",
        r"preguntas frecuentes",
        r"questions fréquentes"
    ]

    has_faq_heading = any(
        re.search(rf"<h2[^>]*>.*{pattern}.*</h2>", content, re.IGNORECASE)
        for pattern in faq_heading_patterns
    )

    if not has_faq_heading:
        issues.append("Missing FAQ <h2> section")

    faq_questions = re.findall(r"<h3", content, re.IGNORECASE)

    if len(faq_questions) < 4:
        issues.append("FAQ has fewer than 4 questions")

    return issues


def validate_structure(content):
    issues = []

    h1_count = count_tag(content, "h1")

    if h1_count != 1:
        issues.append(f"Invalid H1 count: {h1_count}")

    return issues


def main():
    print("=== Sofia: Validate Generated Content ===\n")

    if len(sys.argv) != 2:
        print("Usage:")
        print("python app/validate_generated_content.py DRAFT-0005")
        return

    draft_id = sys.argv[1]

    draft_data = load_json(DRAFT_REGISTRY_FILE)
    drafts = draft_data.get("drafts", [])

    draft = find_draft(drafts, draft_id)

    if not draft:
        print(f"Draft not found: {draft_id}")
        return

    content = draft.get("generated_content", {}).get("content", "")

    if not content:
        print("No content found.")
        return
    
    language_profile = load_language_profile_for_draft(draft)

    issues = []

    issues += validate_structure(content)
    issues += validate_faq(content)
    issues += detect_english_headings(content)
    issues += detect_invalid_tags(content)
    issues += detect_risky_claims(content, language_profile)
    issues += validate_word_count(content, language_profile)

    status = "passed" if not issues else "failed"

    draft["validation"] = {
        "status": status,
        "issues": issues
    }

    save_json(DRAFT_REGISTRY_FILE, draft_data)

    print(f"Validation status: {status}")

    if issues:
        print("\nIssues found:")
        for issue in issues:
            print(f"- {issue}")


if __name__ == "__main__":
    main()