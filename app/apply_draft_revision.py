import json
import os
import sys
import urllib.request
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from workspace_paths import get_workspace_draft_registry_path

from content_knowledge import (
    build_knowledge_package,
    format_package_for_prompt,
)


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

WORKSPACES_PATH = ROOT / "data" / "workspaces.json"
# Deprecated: draft registries are now workspace-level.
GLOBAL_DRAFT_REGISTRY_PATH = ROOT / "sites" / "draft_registry.json"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("SOFIA_MODEL", "qwen2.5:14b")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def find_workspace(workspaces, workspace_id):
    for workspace in workspaces.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def get_drafts(draft_registry):
    if isinstance(draft_registry, dict) and "drafts" in draft_registry:
        return draft_registry["drafts"]
    if isinstance(draft_registry, list):
        return draft_registry
    return []


def find_draft(draft_registry, draft_id):
    for draft in get_drafts(draft_registry):
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def get_review_items(review_queue):
    if isinstance(review_queue, dict) and "review_items" in review_queue:
        return review_queue["review_items"]
    if isinstance(review_queue, dict) and "reviews" in review_queue:
        return review_queue["reviews"]
    if isinstance(review_queue, list):
        return review_queue
    return []


def find_review(review_queue, draft_id):
    for review in get_review_items(review_queue):
        if review.get("draft_id") == draft_id:
            return review
    return None


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


def get_current_content(draft):
    generated = draft.get("generated_content", {})
    if generated.get("content"):
        return generated.get("content")

    previous = draft.get("previous_generated_content", {})
    if previous.get("content"):
        return previous.get("content")

    if draft.get("html_content"):
        return draft.get("html_content")

    return ""


def word_count(text: str) -> int:
    return len((text or "").split())


def build_revision_prompt(
    draft,
    workspace,
    current_content,
    revision_note,
    knowledge_prompt="",
):
    language = draft.get("language") or workspace.get("language") or "pt"
    country = workspace.get("country", "")
    target_keyword = draft.get("target_keyword") or draft.get("focus_keyphrase") or ""
    title = draft.get("working_title") or draft.get("title") or ""

    current_words = word_count(current_content)

    return f"""
You are Sofia, an SEO and GEO content assistant for professional polygraph websites.

Your task:
Revise the existing HTML content according to the examiner's instruction.

STRICT RULES:
- Output ONLY the revised HTML body content.
- Do NOT include explanations before or after the HTML.
- Preserve the original language: {language}.
- Preserve the original topic and search intent.
- Keep the content professional, realistic, and locally appropriate for: {country}.
- Keep valid HTML only.
- Use only these tags: <h1>, <h2>, <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, <a>.
- Keep exactly one <h1>.
- Preserve internal links whenever possible.
- Preserve FAQ sections whenever possible.
- Do NOT remove useful content unnecessarily.
- Do NOT shorten the document aggressively.
- Revised content should normally remain near the original length.
- Current content length: approximately {current_words} words.
- Target minimum after revision: 800 words.
- Preserve SEO relevance for the target keyword: {target_keyword}.
- Keep the title/topic aligned with: {title}.
- Do not make exaggerated claims.
- Do not claim legal admissibility, guaranteed accuracy, certification, infallibility, or 100% certainty.
- Do not invent addresses, phone numbers, prices, offices, or examiner names.
- If the examiner instruction refers to travel or availability, phrase it cautiously.

APPROVED KNOWLEDGE BASE:
{knowledge_prompt}

EXAMINER REVISION INSTRUCTION:
{revision_note}

CURRENT HTML CONTENT:
{current_content}
""".strip()


def main():
    if len(sys.argv) < 4:
        print("Usage:")
        print('python app/apply_draft_revision.py WORKSPACE_ID DRAFT_ID "revision note"')
        return

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]
    revision_note = " ".join(sys.argv[3:]).strip()

    if not revision_note:
        print("Revision note is empty.")
        return

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, workspace_id)

    if not workspace:
        print(f"Workspace not found: {workspace_id}")
        return

    review_queue_path = ROOT / workspace["review_queue_path"]

    if not review_queue_path.exists():
        print(f"Review queue not found: {review_queue_path}")
        return

    try:
        draft_registry_path = get_workspace_draft_registry_path(workspace_id)
    except Exception as e:
        print(f"ERROR: {e}")
        return

    if not draft_registry_path.exists():
        print(f"Workspace draft registry not found: {draft_registry_path}")
        return

    draft_registry = load_json(draft_registry_path)
    review_queue = load_json(review_queue_path)

    draft = find_draft(draft_registry, draft_id)
    review = find_review(review_queue, draft_id)

    if not draft:
        print(f"Draft not found in workspace registry: {draft_id}")
        print(f"Registry: {draft_registry_path}")
        return

    if not review:
        print(f"Review entry not found for draft: {draft_id}")
        return

    current_content = get_current_content(draft)

    if not current_content:
        print(f"No generated content found for draft: {draft_id}")
        return

    topic = (
        draft.get("working_title")
        or draft.get("title")
        or draft.get("target_keyword")
        or draft.get("focus_keyphrase")
        or ""
    )

    knowledge_package = build_knowledge_package(
        workspace_id=workspace_id,
        topic=topic,
        tags_hint=[
            "procedure",
            "ethics",
            "limitations",
            "questions",
            "faq",
            "service",
        ],
        max_blocks=6,
    )

    knowledge_prompt = format_package_for_prompt(knowledge_package)

    prompt = build_revision_prompt(
        draft=draft,
        workspace=workspace,
        current_content=current_content,
        revision_note=revision_note,
        knowledge_prompt=knowledge_prompt,
    )

    print("Applying AI revision. This may take some time...")

    try:
        revised_content = call_ollama(prompt)
    except Exception as e:
        print(f"Revision failed: {type(e).__name__}: {e}")
        return

    if not revised_content:
        print("Revision failed: empty model response.")
        return

    original_words = word_count(current_content)
    revised_words = word_count(revised_content)

    print(f"Original word count: {original_words}")
    print(f"Revised word count: {revised_words}")

    if revised_words < 700:
        print("Revision rejected: revised content became too short.")
        return

    timestamp = now_iso()

    if draft.get("generated_content"):
        draft["previous_generated_content"] = draft.get("generated_content")

    if "revision_history" not in draft:
        draft["revision_history"] = []

    draft["revision_history"].append({
        "revision_note": revision_note,
        "previous_status": draft.get("draft_status"),
        "created_at": timestamp,
        "created_by": "sofia",
        "model": OLLAMA_MODEL
    })

    draft["generated_content"] = {
        "generated_at": timestamp,
        "model": OLLAMA_MODEL,
        "format": "html",
        "language_profile_version": draft.get("generated_content", {}).get("language_profile_version", "1.0"),
        "generation_mode": "revision_from_examiner_comment",
        "revision_note": revision_note,
        "content": revised_content
    }

    draft["html_content"] = revised_content

    draft["draft_status"] = "content_revised"
    draft["wordpress_status"] = "needs_re_review"
    draft["ready_for_publishing"] = False
    draft["updated_at"] = timestamp

    draft["validation"] = {
        "status": "pending",
        "issues": []
    }

    review["status"] = "pending_review"
    review["telegram_notified"] = False
    review["telegram_notified_at"] = None
    review["examiner_decision"] = None
    review["examiner_comment"] = None
    review["decided_at"] = None
    review["ready_for_publishing"] = False
    review["sofia_revision_note"] = revision_note
    review["updated_at"] = timestamp

    draft_registry["scope"] = "workspace"
    draft_registry["workspace_id"] = workspace_id

    save_json(draft_registry_path, draft_registry)
    save_json(review_queue_path, review_queue)

    print("AI draft revision completed successfully.")
    print(f"Workspace: {workspace_id}")
    print(f"Draft: {draft_id}")
    print("Draft status: content_revised")
    print("Review status: pending_review")
    print("Telegram notification reset: false")
    print(f"Workspace registry: {draft_registry_path}")

if __name__ == "__main__":
    main()