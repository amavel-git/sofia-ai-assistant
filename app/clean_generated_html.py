import json
import re
import sys
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]
DRAFT_REGISTRY_FILE = SOFIA_ROOT / "sites" / "draft_registry.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_draft(drafts, draft_id):
    for d in drafts:
        if d.get("draft_id") == draft_id:
            return d
    return None


def strip_code_fences(content: str):
    # remove ```html ... ```
    return re.sub(r"```html|```", "", content, flags=re.IGNORECASE).strip()


def load_language_profile_for_draft(draft):
    workspace_path = draft.get("workspace_path", "")
    if not workspace_path:
        return {}

    profile_path = SOFIA_ROOT / workspace_path / "language_profile.json"

    if not profile_path.exists():
        return {}

    return load_json(profile_path)


def demote_extra_h1_tags(content: str):
    h1_matches = list(re.finditer(r"<h1[^>]*>.*?</h1>", content, flags=re.IGNORECASE | re.DOTALL))

    if len(h1_matches) <= 1:
        return content

    first_h1 = h1_matches[0].group(0)
    rest = content[h1_matches[0].end():]

    rest = re.sub(
        r"<h1([^>]*)>(.*?)</h1>",
        r"<h2\1>\2</h2>",
        rest,
        flags=re.IGNORECASE | re.DOTALL
    )

    return content[:h1_matches[0].end()] + rest


def normalize_faq_heading(content: str):
    faq_patterns = [
        r"<h1[^>]*>\s*(frequently asked questions|faq|perguntas frequentes|preguntas frecuentes|questions fréquentes)\s*</h1>",
        r"<h2[^>]*>\s*(frequently asked questions|faq|perguntas frequentes|preguntas frecuentes|questions fréquentes)\s*</h2>",
        r"<h3[^>]*>\s*(frequently asked questions|faq|perguntas frequentes|preguntas frecuentes|questions fréquentes)\s*</h3>"
    ]

    for pattern in faq_patterns:
        content = re.sub(
            pattern,
            "<h2>Perguntas frequentes</h2>",
            content,
            flags=re.IGNORECASE
        )

    return content


def remove_full_html_wrapper(content: str):
    # remove <!DOCTYPE>, <html>, <head>, <body> wrappers
    content = re.sub(r"<!DOCTYPE.*?>", "", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<html.*?>|</html>", "", content, flags=re.IGNORECASE)
    content = re.sub(r"<head.*?>.*?</head>", "", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<body.*?>|</body>", "", content, flags=re.IGNORECASE)
    return content.strip()


def fix_invalid_tags(content: str):
    content = content.replace("</br>", "")
    content = content.replace("<br>", "")
    content = content.replace("<br/>", "")
    return content


def remove_forbidden_phrases(content: str, language_profile: dict):
    risky_rules = language_profile.get("risky_phrase_rules", {})
    replacements = risky_rules.get("safe_replacements", {})

    for phrase, replacement in replacements.items():
        content = re.sub(
            re.escape(phrase),
            replacement,
            content,
            flags=re.IGNORECASE
        )

    return content


def fix_faq_structure(content: str):
    # convert <p><strong>Q</strong></p> → <h3>Q</h3>
    content = re.sub(
        r"<p>\s*<strong>(.*?)</strong>\s*</p>",
        r"<h3>\1</h3>",
        content,
        flags=re.IGNORECASE
    )
    return content


def ensure_faq_heading(content: str):
    # convert accidental <h1>Perguntas frequentes</h1> → <h2>
    content = re.sub(
        r"<h1>\s*Perguntas frequentes\s*</h1>",
        "<h2>Perguntas frequentes</h2>",
        content,
        flags=re.IGNORECASE
    )
    return content


def main():
    print("=== Sofia: Clean Generated HTML ===\n")

    if len(sys.argv) != 2:
        print("Usage:")
        print("python app/clean_generated_html.py DRAFT-0005")
        return

    draft_id = sys.argv[1]

    data = load_json(DRAFT_REGISTRY_FILE)
    drafts = data.get("drafts", [])

    draft = find_draft(drafts, draft_id)

    if not draft:
        print("Draft not found")
        return

    content = draft.get("generated_content", {}).get("content", "")

    if not content:
        print("No content found")
        return

    language_profile = load_language_profile_for_draft(draft)

    content = strip_code_fences(content)
    content = remove_full_html_wrapper(content)
    content = demote_extra_h1_tags(content)
    content = fix_invalid_tags(content)
    content = remove_forbidden_phrases(content, language_profile)
    content = ensure_faq_heading(content)
    content = normalize_faq_heading(content)
    content = fix_faq_structure(content)

    draft["generated_content"]["content"] = content

    save_json(DRAFT_REGISTRY_FILE, data)

    print("Content cleaned successfully.")


if __name__ == "__main__":
    main()