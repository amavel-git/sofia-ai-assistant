import json
import os
import re
import urllib.request
import sys
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]
DRAFT_REGISTRY_FILE = SOFIA_ROOT / "sites" / "draft_registry.json"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("SOFIA_MODEL", "qwen2.5:7b")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def call_ollama(prompt):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False
    }

    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(req, timeout=600) as response:
        result = json.loads(response.read().decode("utf-8"))

    return result.get("response", "").strip()


def find_draft(drafts, draft_id):
    for d in drafts:
        if d.get("draft_id") == draft_id:
            return d
    return None


def extract_minimum_word_count(issues):
    for issue in issues:
        match = re.search(r"Minimum required:\s*(\d+)", issue, re.IGNORECASE)
        if match:
            return int(match.group(1))

    return 800


def has_short_content_issue(issues):
    for issue in issues:
        if "content too short" in issue.lower():
            return True

    return False


def build_repair_prompt(content, issues):
    minimum_word_count = extract_minimum_word_count(issues)
    short_content = has_short_content_issue(issues)

    expansion_rules = ""

    if short_content:
        expansion_rules = f"""
SPECIAL EXPANSION REQUIREMENT:
- The content is too short.
- Expand the existing content to at least {minimum_word_count} words.
- Add useful, relevant, professional detail.
- Do NOT add filler text.
- Do NOT repeat the same paragraphs.
- Prefer expanding existing sections with practical explanation, limitations, process, examiner guidance, and local service considerations.
- If needed, add one or two new relevant <h2> sections.
- Preserve the original topic and search intent.
- Keep the content in the same language as the original content.
"""

    return f"""
You are Sofia, an SEO content correction assistant.

Your task:
Fix the HTML content below based ONLY on the listed issues.

STRICT RULES:
- Output ONLY clean HTML.
- Do NOT include explanations.
- Do NOT include markdown fences.
- Keep the same language as the original content.
- Keep the same topic and search intent.
- Do NOT remove important sections.
- Do NOT change the meaning of the content unless required to fix a listed issue.
- Keep SEO structure intact.
- Output ONLY valid HTML body content.
- Use exactly ONE <h1>.
- Use only standard HTML tags: <h1>, <h2>, <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, <a>.
- Do not use <br>, </br>, custom tags, markdown, or full <html>/<body> wrappers.
- Replace every heading that is not in the target website language.
- FAQ section is mandatory.
- FAQ section heading must use an <h2> tag.
- FAQ must contain at least 4 questions.
- Each FAQ question must be written as a separate <h3> question.
- Each FAQ answer must be written as one separate <p> paragraph.
- Remove or rewrite any statement about legal admissibility, legal acceptance, certification, guaranteed accuracy, or absolute certainty.
- Do not mention legally accepted, 100%, certified, guaranteed, infallible, or equivalent claims in any language.
- Do not introduce new legal, price, timing, phone, email, address, or office claims.

{expansion_rules}

ISSUES TO FIX:
{json.dumps(issues, ensure_ascii=False, indent=2)}

CONTENT TO FIX:
{content}
""".strip()


def main():
    print("=== Sofia: Repair Generated Content ===\n")

    if len(sys.argv) != 2:
        print("Usage:")
        print("python app/repair_generated_content.py DRAFT-0005")
        return

    draft_id = sys.argv[1]

    if not DRAFT_REGISTRY_FILE.exists():
        print(f"Draft registry not found: {DRAFT_REGISTRY_FILE}")
        return

    draft_data = load_json(DRAFT_REGISTRY_FILE)
    drafts = draft_data.get("drafts", [])

    draft = find_draft(drafts, draft_id)

    if not draft:
        print(f"Draft not found: {draft_id}")
        return

    validation = draft.get("validation", {})

    if validation.get("status") != "failed":
        print("Draft does not require repair.")
        return

    issues = validation.get("issues", [])
    content = draft.get("generated_content", {}).get("content", "")

    if not content:
        print("No content found.")
        return

    prompt = build_repair_prompt(content, issues)

    try:
        repaired = call_ollama(prompt)
    except Exception as e:
        print(f"Repair failed: {e}")
        return

    if not repaired:
        print("Repair failed: empty model response.")
        return

    draft["generated_content"]["content"] = repaired
    draft["repair"] = {
        "status": "completed",
        "model": OLLAMA_MODEL,
        "issues_fixed": issues
    }

    draft["validation"] = {
        "status": "pending",
        "issues": []
    }

    save_json(DRAFT_REGISTRY_FILE, draft_data)

    print("Content repaired. Run validation again.")


if __name__ == "__main__":
    main()