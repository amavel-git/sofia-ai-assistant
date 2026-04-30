import json
import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DRAFT_REGISTRY_FILE = BASE_DIR / "sites" / "draft_registry.json"


RISKY_CLAIMS = [
    "100% accurate",
    "100% accuracy",
    "guaranteed",
    "guarantee results",
    "proves the truth",
    "proves truth",
    "always accurate",
    "infallible",
    "certeza absoluta",
    "100% preciso",
    "garante resultados",
    "prova a verdade",
    "infalível"
]


def load_json(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path: Path, data):
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_generated_draft(drafts):
    for draft in drafts:
        if draft.get("draft_status") in ["content_generated", "needs_quality_review"]:
            return draft
    return None


def get_generated_content(draft):
    draft_content = draft.get("draft_content", {})
    return draft_content.get("content", "")


def extract_field(content, field_name):
    pattern = rf"{re.escape(field_name)}\s*:\s*(.+)"
    match = re.search(pattern, content, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def field_exists(content, field_name):
    # Allow variations like:
    # "Body Content:", "Body Content (HTML format):", etc.
    pattern = rf"{re.escape(field_name)}.*:"
    return bool(re.search(pattern, content, re.IGNORECASE))


def count_words(text):
    return len([w for w in text.strip().split() if w])


def validate_content(content):
    issues = []

    required_fields = [
        "Title",
        "Meta Title",
        "Meta Description",
        "Slug",
        "Focus Keyphrase",
        "H1",
        "Body Content"
    ]

    for field in required_fields:
        if not field_exists(content, field):
            issues.append(f"Missing required field: {field}")

    focus_keyphrase = extract_field(content, "Focus Keyphrase")
    if focus_keyphrase:
        if count_words(focus_keyphrase) > 4:
            issues.append("Focus Keyphrase exceeds 4 words")
    else:
        issues.append("Focus Keyphrase is empty or not detected")

    word_count = len(content.split())

    if word_count < 800:
        issues.append("Content too short (<800 words)")

    faq_questions = content.count("<h3>")

    if faq_questions < 4:
        issues.append("FAQ has fewer than 4 questions")

    if "Practical examples" in content or "Short answer" in content:
        issues.append("English heading detected")

    meta_description = extract_field(content, "Meta Description")
    if meta_description:
        if len(meta_description) > 156:
            issues.append("Meta Description is longer than 156 characters")
    else:
        issues.append("Meta Description is empty or not detected")

    slug = extract_field(content, "Slug")
    if not slug:
        issues.append("Slug is empty or not detected")

    if "<h1>" not in content:
        issues.append("Missing H1")

    if content.count("<h2>") < 4:
        issues.append("Not enough H2 sections")

    if "<h2>" not in content.lower():
        issues.append("Body content may be missing H2 headings")

    if "<p>" not in content.lower():
        issues.append("Body content may be missing paragraphs")

    content_lower = content.lower()
    for risky in ["100%", "guaranteed", "certified", "legalmente aceite"]:
        if risky.lower() in content.lower():
            issues.append(f"Risky claim detected: {risky}")

    return issues


def main():
    print("=== Sofia: Validate Website Draft ===\n")

    if not DRAFT_REGISTRY_FILE.exists():
        print(f"ERROR: draft_registry.json not found: {DRAFT_REGISTRY_FILE}")
        return

    try:
        draft_registry_data = load_json(DRAFT_REGISTRY_FILE)
    except Exception as e:
        print(f"ERROR: Could not read draft_registry.json: {e}")
        return

    drafts = draft_registry_data.get("drafts", [])
    draft = find_generated_draft(drafts)

    if not draft:
        print("No draft with status 'content_generated' found.")
        return

    draft_id = draft.get("draft_id", "")
    content = get_generated_content(draft)

    if not content:
        print(f"ERROR: Draft {draft_id} has no generated content.")
        return

    print(f"Validating draft: {draft_id}\n")

    issues = validate_content(content)

    if issues:
        validation_status = "needs_review"
    else:
        validation_status = "passed"

    draft["validation"] = {
        "status": validation_status,
        "issues": issues
    }

    if validation_status == "passed":
        draft["draft_status"] = "validated"
    else:
        draft["draft_status"] = "needs_quality_review"

    try:
        save_json(DRAFT_REGISTRY_FILE, draft_registry_data)
    except Exception as e:
        print(f"ERROR: Could not save draft_registry.json: {e}")
        return

    print(f"Validation status: {validation_status}")

    if issues:
        print("\nIssues found:")
        for issue in issues:
            print(f"- {issue}")
    else:
        print("No issues found.")


if __name__ == "__main__":
    main()