import json
import os
import urllib.request
from pathlib import Path
import sys

from workspace_paths import (
    find_draft_any_workspace,
    get_workspace_draft_registry_path,
)

SOFIA_ROOT = Path(__file__).resolve().parents[1]

DRAFT_REGISTRY_FILE = SOFIA_ROOT / "sites" / "draft_registry.json"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("SOFIA_MODEL", "qwen2.5:7b")


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def call_ollama(prompt):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False
    }

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(request, timeout=600) as response:
        result = json.loads(response.read().decode("utf-8"))

    return result.get("response", "").strip()


def find_draft(drafts, draft_id):
    for draft in drafts:
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def load_link_suggestions(workspace_path):
    path = SOFIA_ROOT / workspace_path / "internal_link_suggestions.json"
    return load_json(path).get("internal_link_suggestions", [])


def get_allowed_targets(suggestions):
    targets = []

    for item in suggestions:
        if item.get("status") != "suggested":
            continue

        if item.get("link_type") not in ["conversion", "supporting_information", "topic_related", "silo_support"]:
            continue

        targets.append({
            "target_url": item.get("target_url", ""),
            "target_page_type": item.get("target_page_type", ""),
            "link_type": item.get("link_type", ""),
            "priority": item.get("priority", ""),
            "reason": item.get("reason", "")
        })

    # keep prompt small
    return targets[:20]


def build_prompt(content, allowed_targets):
    return f"""
You are Sofia, an SEO internal linking assistant.

Your task:
Suggest up to 3 internal links for the HTML content below.

Rules:
- Use ONLY target_url values from the allowed target list.
- Do NOT invent URLs.
- Do NOT use generic anchors such as "click here", "read more", or "saiba mais" unless no better option exists.
- Choose natural anchor text that already appears in the content whenever possible.
- Anchor text should be short, natural, and SEO-relevant.
- Do not suggest more than one link to the same target URL.
- Prefer one conversion link, one supporting information link, and one related service link if appropriate.
- Return ONLY valid JSON.
- Do not include markdown fences.

Return format:
{{
  "links": [
    {{
      "target_url": "...",
      "anchor_text": "...",
      "reason": "..."
    }}
  ]
}}

Allowed target list:
{json.dumps(allowed_targets, ensure_ascii=False, indent=2)}

HTML content:
{content}
""".strip()


def extract_json(text):
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        raise ValueError("AI response did not contain JSON object.")

    return json.loads(text[start:end + 1])


def validate_ai_links(ai_links, allowed_targets):
    allowed_urls = {item["target_url"] for item in allowed_targets}
    validated = []

    seen = set()

    for link in ai_links:
        target_url = link.get("target_url", "")
        anchor_text = link.get("anchor_text", "").strip()

        if target_url not in allowed_urls:
            continue

        if target_url in seen:
            continue

        if not anchor_text:
            continue

        validated.append({
            "target_url": target_url,
            "anchor_text": anchor_text,
            "reason": link.get("reason", "")
        })

        seen.add(target_url)

        if len(validated) >= 3:
            break

    return validated


def load_draft_registry_for_draft(draft_id):
    workspace_id, draft = find_draft_any_workspace(draft_id)

    if not workspace_id or not draft:
        raise RuntimeError(f"Draft not found in any workspace registry: {draft_id}")

    registry_path = get_workspace_draft_registry_path(workspace_id)
    registry_data = load_json(registry_path)

    return workspace_id, registry_path, registry_data, draft


def main():
    print("=== Sofia: Optimize Internal Link Anchors ===\n")

    if len(sys.argv) != 2:
        print("Usage:")
        print("python app/optimize_internal_link_anchors.py DRAFT-0005")
        return

    draft_id = sys.argv[1]

    try:
        workspace_id, draft_registry_file, draft_data, draft = load_draft_registry_for_draft(draft_id)
    except Exception as e:
        print(f"ERROR: {e}")
        return

    if not draft:
        print(f"Draft not found: {draft_id}")
        return

    if draft.get("draft_status") not in ["content_generated", "internal_links_added"]:
        print(f"Draft not ready for anchor optimization. Current status: {draft.get('draft_status')}")
        return

    content = draft.get("generated_content", {}).get("content", "")
    if not content:
        print("Draft has no generated content.")
        return

    suggestions = load_link_suggestions(draft.get("workspace_path", ""))
    allowed_targets = get_allowed_targets(suggestions)

    if not allowed_targets:
        print("No allowed internal link targets found.")
        return

    prompt = build_prompt(content, allowed_targets)

    try:
        response = call_ollama(prompt)
        parsed = extract_json(response)
    except Exception as e:
        print(f"AI anchor optimization failed: {e}")
        return

    validated_links = validate_ai_links(parsed.get("links", []), allowed_targets)

    draft["ai_internal_link_suggestions"] = {
        "model": OLLAMA_MODEL,
        "links": validated_links
    }

    draft_data["scope"] = "workspace"
    draft_data["workspace_id"] = workspace_id
    save_json(draft_registry_file, draft_data)

    print(f"AI anchor suggestions created for {draft_id}")
    print(f"Validated suggestions: {len(validated_links)}")
    print(f"Workspace registry: {draft_registry_file}")


if __name__ == "__main__":
    main()