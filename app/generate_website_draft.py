import json
import re
import sys
import requests
from pathlib import Path
from datetime import datetime, timezone

from seo_field_rules import normalize_seo_fields
from workspace_paths import (
    get_workspace_draft_registry_path,
    empty_draft_registry,
)

from content_knowledge import (
    build_knowledge_package,
    format_package_for_prompt,
)


BASE_DIR = Path(__file__).resolve().parent.parent

WORKSPACES_FILE = BASE_DIR / "data" / "workspaces.json"
PROMPT_FILE = BASE_DIR / "prompts" / "website_content_prompt.md"
# Deprecated: draft registries are now workspace-level.
GLOBAL_DRAFT_REGISTRY_FILE = BASE_DIR / "sites" / "draft_registry.json"

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:14b"


def load_json(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path: Path, data):
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_text(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return f.read()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def find_workspace(workspaces_data, workspace_id: str):
    for workspace in workspaces_data.get("workspaces", []):
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


def slugify(text):
    text = text.lower().strip()
    replacements = {
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u",
        "ç": "c",
        "ñ": "n"
    }

    for original, replacement in replacements.items():
        text = text.replace(original, replacement)

    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def infer_locale(language: str, workspace_id: str, site_target: str):
    language = (language or "").lower()
    workspace_id = (workspace_id or "").lower()
    site_target = (site_target or "").lower()

    if language in ["pt", "pt-pt"]:
        if "br" in workspace_id or "brasil" in site_target:
            return "pt-BR"
        return "pt-PT"

    if language == "pt-br":
        return "pt-BR"

    if language in ["en", "en-us", "en-gb"]:
        return "en-US"

    if language in ["es", "es-es"]:
        return "es-ES"

    if language in ["fr", "fr-fr"]:
        return "fr-FR"

    return language


def load_internal_links(workspace_folder: Path):
    suggestions_file = workspace_folder / "internal_link_suggestions.json"
    structure_file = workspace_folder / "site_structure.json"

    links = []

    if suggestions_file.exists():
        try:
            data = load_json(suggestions_file)
            for item in data.get("suggestions", []):
                url = item.get("target_url") or item.get("url")
                anchor = item.get("anchor_text") or item.get("anchor") or ""
                if url:
                    links.append({
                        "url": url,
                        "anchor": anchor,
                        "source": "internal_link_suggestions"
                    })
        except Exception:
            pass

    if not links and structure_file.exists():
        try:
            structure = load_json(structure_file)
            for page in structure.get("pages", []):
                url = page.get("url", "")
                slug = page.get("slug", "")
                page_type = page.get("page_type", "")

                if url:
                    links.append({
                        "url": url,
                        "anchor": slug or page_type or url,
                        "source": "site_structure"
                    })
        except Exception:
            pass

    return links[:8]


def format_internal_links(internal_links):
    if not internal_links:
        return "No internal links available. If none are relevant, include no forced internal links."

    lines = []

    for link in internal_links:
        lines.append(
            f"- URL: {link.get('url', '')} | Suggested anchor: {link.get('anchor', '')}"
        )

    return "\n".join(lines)


def build_draft_context(draft, workspace):
    title = (
        draft.get("title")
        or draft.get("working_title")
        or draft.get("draft_title")
        or ""
    )

    focus_keyphrase = (
        draft.get("focus_keyphrase")
        or draft.get("target_keyword")
        or ""
    )

    secondary_keywords = draft.get("secondary_keywords", [])
    if isinstance(secondary_keywords, str):
        secondary_keywords = [secondary_keywords]

    language = draft.get("language") or workspace.get("language", "")
    site_target = draft.get("site_target") or workspace.get("domain", "")
    locale = draft.get("locale") or infer_locale(language, workspace.get("workspace_id", ""), site_target)

    return {
        "title": title,
        "focus_keyphrase": focus_keyphrase,
        "secondary_keywords": secondary_keywords,
        "language": language,
        "locale": locale,
        "site_target": site_target,
        "content_type": draft.get("content_type", "seo_page"),
        "search_intent": draft.get("search_intent", "informational and commercial"),
        "suggested_slug": draft.get("slug") or draft.get("suggested_slug") or slugify(title),
        "idea_summary": draft.get("notes") or draft.get("summary") or title,
        "market": workspace.get("market_code", ""),
        "country": workspace.get("country", ""),
        "domain": workspace.get("domain", "")
    }


def fill_prompt(
    template: str,
    draft: dict,
    workspace: dict,
    internal_links_text: str,
    knowledge_prompt: str = "",
):
    context = build_draft_context(draft, workspace)

    replacements = {
        "{{language}}": context["language"],
        "{{locale}}": context["locale"],
        "{{market}}": context["market"],
        "{{country}}": context["country"],
        "{{content_type}}": context["content_type"],
        "{{idea_title}}": context["title"],
        "{{idea_summary}}": context["idea_summary"],
        "{{target_keyword}}": context["focus_keyphrase"],
        "{{focus_keyphrase}}": context["focus_keyphrase"],
        "{{secondary_keywords}}": ", ".join(context["secondary_keywords"]),
        "{{search_intent}}": context["search_intent"],
        "{{suggested_slug}}": context["suggested_slug"],
        "{{site_target}}": context["site_target"],
        "{{domain}}": context["domain"],
        "{{internal_links}}": internal_links_text,
        "{{minimum_word_count}}": "800"
    }

    prompt = template

    for key, value in replacements.items():
        prompt = prompt.replace(key, str(value))

    knowledge_rules = f"""

CONTROLLED KNOWLEDGE PACKAGE

Use the following approved professional reference material as semantic guidance only.

IMPORTANT KNOWLEDGE RULES:
- Do NOT copy knowledge blocks verbatim.
- Do NOT mirror sentence structure from the source blocks.
- Extract concepts and rewrite them naturally.
- Adapt terminology to the workspace language and country.
- Maintain professional, ethical, and legally cautious wording.
- Preserve local terminology consistency.
- Avoid duplicate-content behavior across workspaces.
- Use the knowledge blocks to strengthen:
  - professional explanations
  - FAQ quality
  - limitations
  - procedural clarity
  - ethical safeguards
  - realistic expectations
  - localized terminology
  - service explanations

{knowledge_prompt}
""".strip()

    strict_html_rules = f"""

CRITICAL OUTPUT FORMAT — STRICT HTML ONLY

Return ONLY the final page body in clean HTML.

Do NOT return Markdown.
Do NOT use Markdown headings.
Do NOT use code fences.
Do NOT include explanatory comments.
Do NOT include metadata blocks such as:
### Title:
### Meta Title:
### Meta Description:
### Slug:
### Focus Keyphrase:
### H1:
### Body Content (HTML format):

Do NOT place SEO fields inside the page body.
Sofia's Python workflow will save SEO title, focus keyphrase, slug, and meta description separately.

The response must start directly with exactly one <h1> tag.

Required HTML structure:
<h1>...</h1>
<h2>...</h2>
<p>...</p>
<h2>...</h2>
<p>...</p>
<h2>...</h2>
<p>...</p>

FAQ section requirement:
- Portuguese: use <h2>Perguntas frequentes</h2>
- Spanish: use <h2>Preguntas frecuentes</h2>
- French: use <h2>Questions fréquentes</h2>
- English: use <h2>Frequently Asked Questions</h2>

The FAQ section must include at least 4 questions using <h3>Question...</h3> followed by <p>Answer...</p>.

Minimum length:
At least 800 words.

Professional polygraph terminology:
- Do not say the polygraph detects lies directly.
- Do not describe the polygraph as infallible, infalível, infalible, infaillible, guaranteed, or 100% accurate.
- Do not present the result as legal proof.
- Explain that the polygraph records physiological responses associated with specific questions.
- Include limitations, ethical considerations, and the need for professional review.

Internal links:
Use only relevant internal links from the list if they fit naturally.
Do not force links that are not relevant.

Final reminder:
Your answer must be only clean HTML beginning with <h1>.
""".strip()

    prompt = f"{prompt}\n\n{knowledge_rules}\n\n{strict_html_rules}"

    return prompt, context


def call_ollama(prompt: str):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.4,
            "num_ctx": 8192
        }
    }

    response = requests.post(OLLAMA_URL, json=payload, timeout=600)
    response.raise_for_status()

    data = response.json()
    return data.get("response", "").strip()


def extract_markdown_field(content, field_name):
    pattern = rf"###\s*{re.escape(field_name)}\s*:\s*(.*?)(?=\n\s*###|\Z)"
    match = re.search(pattern, content, flags=re.IGNORECASE | re.DOTALL)

    if not match:
        return ""

    return match.group(1).strip()


def clean_generated_content(content):
    content = str(content or "").strip()

    if content.startswith("```html"):
        content = content.replace("```html", "", 1).strip()

    if content.startswith("```"):
        content = content.replace("```", "", 1).strip()

    if content.endswith("```"):
        content = content[:-3].strip()

    # If Ollama returns a Markdown package, extract only the body section.
    markdown_package_markers = [
        "### Title:",
        "### Meta Title:",
        "### Meta Description:",
        "### Slug:",
        "### Focus Keyphrase:",
        "### H1:",
        "### Body Content"
    ]

    if any(marker.lower() in content.lower() for marker in markdown_package_markers):
        h1_text = extract_markdown_field(content, "H1") or extract_markdown_field(content, "Title")
        body = (
            extract_markdown_field(content, "Body Content (HTML format)")
            or extract_markdown_field(content, "Body Content")
            or content
        )

        content = body.strip()

        if h1_text and "<h1" not in content.lower():
            content = f"<h1>{h1_text}</h1>\n\n{content}"

    return content


def extract_meta_description(content, focus_keyphrase):
    text = re.sub(r"<[^>]+>", " ", content)
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) <= 155:
        return text

    description = text[:155].rsplit(" ", 1)[0]

    if focus_keyphrase and focus_keyphrase.lower() not in description.lower():
        description = f"{focus_keyphrase}: {description}"

    return description[:155]


def main():
    print("=== Sofia: Generate Website Draft ===\n")

    if len(sys.argv) != 3:
        print("Usage:")
        print("python app/generate_website_draft.py WORKSPACE_ID DRAFT_ID")
        print("Example:")
        print("python app/generate_website_draft.py local.ao DRAFT-0001")
        return

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]

    for required_file in [WORKSPACES_FILE, PROMPT_FILE]:
        if not required_file.exists():
            print(f"ERROR: Required file not found: {required_file}")
            sys.exit(1)

    try:
        workspaces_data = load_json(WORKSPACES_FILE)
        prompt_template = load_text(PROMPT_FILE)
    except Exception as e:
        print(f"ERROR: Could not read required files: {e}")
        sys.exit(1)

    workspace = find_workspace(workspaces_data, workspace_id)

    if not workspace:
        print(f"ERROR: Workspace not found in workspaces.json: {workspace_id}")
        sys.exit(1)

    draft_registry_file = get_workspace_draft_registry_path(workspace_id)

    if draft_registry_file.exists():
        draft_registry_data = load_json(draft_registry_file)
    else:
        draft_registry_data = empty_draft_registry(workspace_id)

    draft = find_draft(draft_registry_data, draft_id)

    if not draft:
        print(f"ERROR: Draft not found in workspace draft registry: {draft_id}")
        print(f"Registry: {draft_registry_file}")
        sys.exit(1)

    workspace_folder = BASE_DIR / workspace.get("folder_path", "")
    internal_links = load_internal_links(workspace_folder)
    internal_links_text = format_internal_links(internal_links)

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
            "faq",
            "questions",
            "service",
        ],
        max_blocks=6,
    )

    knowledge_prompt = format_package_for_prompt(knowledge_package)

    prompt, context = fill_prompt(
        template=prompt_template,
        draft=draft,
        workspace=workspace,
        internal_links_text=internal_links_text,
        knowledge_prompt=knowledge_prompt,
    )

    print(f"Processing draft: {draft_id}")
    print(f"Workspace: {workspace_id}")
    print(f"Title: {context['title']}")
    print(f"Focus keyphrase: {context['focus_keyphrase']}")
    print(f"Locale: {context['locale']}")
    print(
        "Knowledge blocks used:",
        [
            block.get("block_id") or block.get("id")
            for block in knowledge_package.get("selected_blocks", [])
        ],
    )
    print("")

    try:
        generated_content = call_ollama(prompt)
    except Exception as e:
        print(f"ERROR: Ollama generation failed: {e}")
        sys.exit(1)

    if not generated_content:
        print("ERROR: Ollama returned empty content.")
        sys.exit(1)

    generated_content = clean_generated_content(generated_content)

    draft_title = draft.get("title") or context["title"]

    raw_focus_keyphrase = (
        draft.get("focus_keyphrase")
        or context["focus_keyphrase"]
        or draft.get("target_keyword")
        or draft_title
    )

    raw_slug = (
        draft.get("slug")
        or context["suggested_slug"]
        or draft.get("suggested_slug")
        or draft_title
    )

    raw_meta_description = (
        draft.get("meta_description")
        or extract_meta_description(generated_content, raw_focus_keyphrase)
    )

    raw_seo_title = (
        draft.get("seo_title")
        or draft_title
    )

    seo_fields = normalize_seo_fields(
        title=draft_title,
        focus_keyphrase=raw_focus_keyphrase,
        slug=raw_slug,
        meta_description=raw_meta_description,
        seo_title=raw_seo_title,
        fallback_topic=draft.get("target_keyword") or draft_title,
        language=context["language"]
    )

    draft["title"] = draft_title
    draft["slug"] = seo_fields["slug"]
    draft["focus_keyphrase"] = seo_fields["focus_keyphrase"]
    draft["seo_title"] = seo_fields["seo_title"]
    draft["meta_description"] = seo_fields["meta_description"]

    draft["html_content"] = generated_content

    draft["generated_content"] = {
        "generated_at": now_iso(),
        "model": OLLAMA_MODEL,
        "content_format": "html",
        "knowledge_base_used": True,
        "knowledge_topic": topic,
        "knowledge_blocks_used": [
            block.get("block_id") or block.get("id")
            for block in knowledge_package.get("selected_blocks", [])
        ],
        "content": generated_content
    }

    draft["draft_status"] = "content_generated"
    draft["html_generated_at"] = now_iso()
    draft["updated_at"] = now_iso()

    draft_registry_data["scope"] = "workspace"
    draft_registry_data["workspace_id"] = workspace_id
    save_json(draft_registry_file, draft_registry_data)

    print("Website draft generated successfully.")
    print(f"Draft ID: {draft_id}")
    print("Saved fields: html_content, generated_content.content, slug, meta_description")
    print("Knowledge base used: yes\n")
    print("Generated content preview:")
    print(generated_content[:1200])


if __name__ == "__main__":
    main()