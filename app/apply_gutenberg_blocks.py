#!/usr/bin/env python3
"""
Sofia Apply Gutenberg Blocks

Config-driven transformer.
No AI calls.
No WordPress API calls.
No language-specific hardcoding.

Purpose:
- Insert configured reusable/presentation blocks into drafts.
- Keep workspace/language wording and block IDs in JSON files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


SOFIA_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = SOFIA_ROOT / "app"
SITES_DIR = SOFIA_ROOT / "sites" / "local_sites"
DATA_DIR = SOFIA_ROOT / "data"

sys.path.insert(0, str(APP_DIR))

from workspace_paths import find_draft_any_workspace, get_workspace_draft_registry_path  # noqa: E402
from gutenberg_blocks import render_named_block, render_yoast_faq_block  # noqa: E402


def load_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_workspace_dir(workspace_id: str) -> Path:
    workspace_id = str(workspace_id or "").strip()

    direct = SITES_DIR / workspace_id
    if direct.exists():
        return direct

    if workspace_id.startswith("local."):
        short_id = workspace_id.split(".", 1)[1]
        short_path = SITES_DIR / short_id
        if short_path.exists():
            return short_path

    return direct


def load_draft(workspace_id: str, draft_id: str) -> Tuple[Path, Dict[str, Any], Dict[str, Any]]:
    registry_path = get_workspace_draft_registry_path(workspace_id)
    registry = load_json(registry_path, {"drafts": []})

    for draft in registry.get("drafts", []):
        if draft.get("draft_id") == draft_id:
            return registry_path, registry, draft

    raise RuntimeError(f"Draft not found in workspace registry: {workspace_id} {draft_id}")


def load_draft_auto(draft_id: str) -> Tuple[str, Path, Dict[str, Any], Dict[str, Any]]:
    workspace_id, _ = find_draft_any_workspace(draft_id)
    if not workspace_id:
        raise RuntimeError(f"Draft not found in any workspace registry: {draft_id}")

    registry_path, registry, draft = load_draft(workspace_id, draft_id)
    return workspace_id, registry_path, registry, draft


def merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def load_presentation_config(workspace_id: str) -> Dict[str, Any]:
    """
    Load page presentation from:
    1. data/page_blueprints.json
    2. workspace/page_presentation.json
    3. workspace/language_profile.json

    Later files override earlier files.
    """
    workspace_dir = resolve_workspace_dir(workspace_id)

    sources = [
        load_json(DATA_DIR / "page_blueprints.json", {}),
        load_json(workspace_dir / "page_presentation.json", {}),
        load_json(workspace_dir / "language_profile.json", {}),
    ]

    config: Dict[str, Any] = {}

    for source in sources:
        if isinstance(source, dict):
            config = merge_dicts(config, source)

    return config


def get_content(draft: Dict[str, Any]) -> str:
    generated = draft.get("generated_content")
    if isinstance(generated, dict):
        content = generated.get("content")
        if content:
            return str(content)
    return str(draft.get("html_content") or "")


def set_content(draft: Dict[str, Any], content: str) -> None:
    if not isinstance(draft.get("generated_content"), dict):
        draft["generated_content"] = {}
    draft["generated_content"]["content"] = content
    draft["html_content"] = content


def infer_page_type(draft: Dict[str, Any]) -> str:
    page_plan = draft.get("page_plan") or {}
    strategy = draft.get("strategy") or {}

    for source in (draft, page_plan, strategy):
        if not isinstance(source, dict):
            continue
        for key in ("page_type", "blueprint_id", "content_type", "template_type"):
            value = source.get(key)
            if value:
                return str(value).strip()

    return ""


def block_already_present(content: str, block_html: str) -> bool:
    return bool(block_html and block_html.strip() in content)


def find_faq_start(content: str) -> int:
    # Prefer the visible FAQ heading before the Yoast block.
    patterns = [
        r'<!--\s*wp:heading\s*-->\s*<h2[^>]*>\s*[^<]*(preguntas|perguntas|questions|faq)[^<]*</h2>\s*<!--\s*/wp:heading\s*-->',
        r'<h2[^>]*>\s*Preguntas\s+frecuentes\s*</h2>',
        r'<h2[^>]*>\s*Preguntas\s+Frecuentes\s*</h2>',
        r'<h2[^>]*>\s*Perguntas\s+frequentes\s*</h2>',
        r'<h2[^>]*>\s*Questions\s+fréquentes\s*</h2>',
        r'<h2[^>]*>\s*Frequently\s+asked\s+questions\s*</h2>',
        r'<h2[^>]*>\s*FAQ\s*</h2>',
        r'<!--\s*wp:yoast/faq-block\b',
    ]

    for pattern in patterns:
        match = re.search(pattern, content, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.start()

    return -1


def find_after_faq_position(content: str) -> int:
    """
    Insert after the complete FAQ block.

    If Yoast FAQ exists, place content after:
      <!-- /wp:yoast/faq-block -->

    Never place content between:
      <!-- wp:heading -->
      <h2>...</h2>
      <!-- /wp:heading -->
    """
    content = str(content or "")

    yoast_close = re.search(
        r'<!--\s*/wp:yoast/faq-block\s*-->',
        content,
        flags=re.IGNORECASE,
    )

    if yoast_close:
        return yoast_close.end()

    faq_start = find_faq_start(content)
    if faq_start < 0:
        return len(content)

    search_from = faq_start + 1
    next_h2 = re.search(r'<h2[^>]*>', content[search_from:], flags=re.IGNORECASE)

    if next_h2:
        return search_from + next_h2.start()

    return len(content)


def insert_before_faq(content: str, block_html: str) -> Tuple[str, bool]:
    if not block_html or block_already_present(content, block_html):
        return content, False

    pos = find_faq_start(content)
    if pos < 0:
        pos = len(content)

    return content[:pos].rstrip() + "\n\n" + block_html.strip() + "\n\n" + content[pos:].lstrip(), True


def insert_after_faq(content: str, block_html: str) -> Tuple[str, bool]:
    if not block_html or block_already_present(content, block_html):
        return content, False

    pos = find_after_faq_position(content)

    return content[:pos].rstrip() + "\n\n" + block_html.strip() + "\n\n" + content[pos:].lstrip(), True


def insert_after_intro(content: str, block_html: str) -> Tuple[str, bool]:
    if not block_html or block_already_present(content, block_html):
        return content, False

    matches = list(re.finditer(r'</p>', content, flags=re.IGNORECASE))
    if not matches:
        return content.rstrip() + "\n\n" + block_html.strip() + "\n", True

    pos = matches[0].end()
    return content[:pos].rstrip() + "\n\n" + block_html.strip() + "\n\n" + content[pos:].lstrip(), True


def insert_after_main_content(content: str, block_html: str) -> Tuple[str, bool]:
    if not block_html or block_already_present(content, block_html):
        return content, False

    return content.rstrip() + "\n\n" + block_html.strip() + "\n", True



def insert_after_h2_number(content: str, block_html: str, h2_number: int) -> Tuple[str, bool]:
    if not block_html or block_already_present(content, block_html):
        return content, False

    matches = list(re.finditer(r"<h2[^>]*>.*?</h2>", content, flags=re.IGNORECASE | re.DOTALL))

    if len(matches) < h2_number:
        return insert_after_main_content(content, block_html)

    target = matches[h2_number - 1]
    insert_pos = target.end()

    paragraph = re.search(r"</p>", content[insert_pos:], flags=re.IGNORECASE)
    if paragraph:
        insert_pos = insert_pos + paragraph.end()

    return content[:insert_pos].rstrip() + "\n\n" + block_html.strip() + "\n\n" + content[insert_pos:].lstrip(), True


def insert_block_at_position(content: str, position: str, block_html: str) -> Tuple[str, bool]:
    position = str(position or "").strip()

    h2_match = re.match(r"after_h2_(\d+)$", position)
    if h2_match:
        return insert_after_h2_number(content, block_html, int(h2_match.group(1)))

    if position == "before_faq":
        return insert_before_faq(content, block_html)

    if position == "after_faq":
        return insert_after_faq(content, block_html)

    if position == "after_intro":
        return insert_after_intro(content, block_html)

    if position == "after_main_content":
        return insert_after_main_content(content, block_html)

    return insert_after_main_content(content, block_html)



def configured_headings(block_config: Dict[str, Any]) -> List[str]:
    headings: List[str] = []

    for key in ("match_headings", "cleanup_headings", "headings"):
        value = block_config.get(key)
        if isinstance(value, list):
            headings.extend([str(v).strip() for v in value if str(v).strip()])
        elif isinstance(value, str) and value.strip():
            headings.append(value.strip())

    title = str(block_config.get("title") or "").strip()
    if title:
        headings.append(title)

    return list(dict.fromkeys(headings))


def remove_configured_section(content: str, block_config: Dict[str, Any]) -> Tuple[str, bool]:
    headings = configured_headings(block_config)
    if not headings:
        return content, False

    heading_pattern = "|".join(re.escape(h) for h in headings)

    pattern = (
        r'<h2[^>]*>\s*(?:'
        + heading_pattern
        + r')\s*</h2>\s*'
        r'((?:(?!<h2[^>]*>).)*?)'
        r'(?=<h2[^>]*>|<!--\s*wp:heading\b|$)'
    )

    updated, count = re.subn(
        pattern,
        "",
        content,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )

    return updated, count > 0


def cleanup_legacy_section_for_block(
    content: str,
    block_name: str,
    gutenberg_blocks: Dict[str, Any],
) -> Tuple[str, bool]:
    block_config = gutenberg_blocks.get(block_name) or {}
    if not isinstance(block_config, dict):
        return content, False

    if not block_config.get("remove_legacy_section", True):
        return content, False

    return remove_configured_section(content, block_config)



def get_faq_config(presentation_config: Dict[str, Any]) -> Dict[str, Any]:
    faq_config = presentation_config.get("faq") or {}
    return faq_config if isinstance(faq_config, dict) else {}


def get_faq_heading_pattern(faq_config: Dict[str, Any]) -> re.Pattern | None:
    headings = faq_config.get("match_headings") or []

    if isinstance(headings, str):
        headings = [headings]

    headings = [str(h).strip() for h in headings if str(h).strip()]

    if not headings:
        headings = [
            "Preguntas frecuentes",
            "Preguntas Frecuentes",
            "FAQ",
            "Frequently asked questions",
            "Perguntas frequentes",
            "Questions fréquentes",
        ]

    heading_pattern = "|".join(re.escape(h) for h in headings)

    return re.compile(
        r'<h2[^>]*>\s*(' + heading_pattern + r')\s*</h2>',
        flags=re.IGNORECASE | re.DOTALL,
    )


def remove_plain_faq_sections_after_yoast(content: str, faq_config: Dict[str, Any]) -> Tuple[str, bool]:
    """
    If a Yoast FAQ block already exists, remove any additional legacy FAQ
    sections in plain <h2> + <h3>/<p> format after the Yoast block.

    This prevents duplicated visible FAQ sections when content has already
    been converted to Yoast FAQ format.
    """
    if "<!-- wp:yoast/faq-block" not in content:
        return content, False

    close_match = re.search(
        r'<!--\s*/wp:yoast/faq-block\s*-->',
        content,
        flags=re.IGNORECASE,
    )

    if not close_match:
        return content, False

    before = content[:close_match.end()]
    after = content[close_match.end():]
    changed = False

    while True:
        heading, faqs, start, end = extract_plain_faq_section(after, faq_config)

        if start < 0 or end <= start:
            break

        # Only remove real FAQ sections, not accidental heading matches.
        if not faqs:
            break

        after = after[:start].rstrip() + "\n\n" + after[end:].lstrip()
        changed = True

    return before + after, changed


def extract_plain_faq_section(content: str, faq_config: Dict[str, Any]) -> Tuple[str, List[Dict[str, str]], int, int]:
    """
    Extract FAQ section from H2 + H3/P format.

    Returns:
    - heading text
    - faqs
    - start index
    - end index
    """
    pattern = get_faq_heading_pattern(faq_config)
    if not pattern:
        return "", [], -1, -1

    heading_match = pattern.search(content)
    if not heading_match:
        return "", [], -1, -1

    heading_text = heading_match.group(1).strip()
    start = heading_match.start()

    after_heading_start = heading_match.end()
    after_heading = content[after_heading_start:]

    next_h2 = re.search(r'<h2[^>]*>', after_heading, flags=re.IGNORECASE)
    end = len(content)

    if next_h2:
        end = after_heading_start + next_h2.start()

    faq_body = content[after_heading_start:end]

    item_pattern = re.compile(
        r'<h3[^>]*>\s*(.*?)\s*</h3>\s*'
        r'<p[^>]*>\s*(.*?)\s*</p>',
        flags=re.IGNORECASE | re.DOTALL,
    )

    faqs: List[Dict[str, str]] = []

    for match in item_pattern.finditer(faq_body):
        question = re.sub(r'<[^>]+>', ' ', match.group(1))
        answer = re.sub(r'<[^>]+>', ' ', match.group(2))

        question = re.sub(r'\s+', ' ', question).strip()
        answer = re.sub(r'\s+', ' ', answer).strip()

        if question and answer:
            faqs.append({
                "question": question,
                "answer": answer,
            })

    return heading_text, faqs, start, end


def apply_yoast_faq_block(content: str, presentation_config: Dict[str, Any]) -> Tuple[str, bool]:
    faq_config = get_faq_config(presentation_config)

    if not faq_config.get("enabled", False):
        return content, False

    if str(faq_config.get("mode") or "").strip() != "yoast_faq_block":
        return content, False

    if "<!-- wp:yoast/faq-block" in content:
        return remove_plain_faq_sections_after_yoast(content, faq_config)

    heading, faqs, start, end = extract_plain_faq_section(content, faq_config)

    if start < 0 or end <= start or not faqs:
        return content, False

    rendered = render_yoast_faq_block(
        faqs=faqs,
        heading=heading or "Preguntas frecuentes",
    )

    if not rendered:
        return content, False

    updated = content[:start].rstrip() + "\n\n" + rendered.strip() + "\n\n" + content[end:].lstrip()

    updated, cleaned_extra = remove_plain_faq_sections_after_yoast(updated, faq_config)

    return updated, True


def apply_gutenberg_blocks(content: str, presentation_config: Dict[str, Any], page_type: str) -> Tuple[str, List[str]]:
    applied: List[str] = []

    gutenberg_blocks = presentation_config.get("gutenberg_blocks") or {}
    page_types = presentation_config.get("page_types") or {}

    page_config = page_types.get(page_type) or {}
    positions = page_config.get("blocks") or {}

    if not isinstance(gutenberg_blocks, dict) or not isinstance(positions, dict):
        return content, applied

    # Normalize FAQ presentation first so block placement uses the final FAQ structure.
    content, faq_changed = apply_yoast_faq_block(content, presentation_config)
    if faq_changed:
        applied.append("faq:yoast_faq_block")

    for position, block_names in positions.items():
        if not isinstance(block_names, list):
            continue

        for block_name in reversed(block_names):
            block_name = str(block_name or "").strip()
            if not block_name:
                continue

            block_html = render_named_block(
                block_name=block_name,
                gutenberg_blocks_config=gutenberg_blocks,
                fallback_html="",
            )

            if not block_html:
                continue

            content, changed = insert_block_at_position(content, position, block_html)
            if changed:
                content, cleaned = cleanup_legacy_section_for_block(
                    content=content,
                    block_name=block_name,
                    gutenberg_blocks=gutenberg_blocks,
                )
                applied.append(f"{position}:{block_name}" + (":cleaned" if cleaned else ""))

    return content, applied


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply configured reusable Gutenberg blocks to a Sofia draft.")
    parser.add_argument("workspace_or_draft", help="Workspace ID or draft ID")
    parser.add_argument("draft_id", nargs="?", help="Draft ID if workspace ID was provided")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without saving")
    args = parser.parse_args()

    if args.draft_id:
        workspace_id = args.workspace_or_draft
        draft_id = args.draft_id
        registry_path, registry, draft = load_draft(workspace_id, draft_id)
    else:
        draft_id = args.workspace_or_draft
        workspace_id, registry_path, registry, draft = load_draft_auto(draft_id)

    page_type = infer_page_type(draft)
    if not page_type:
        print("No page_type found for draft.")
        return

    presentation_config = load_presentation_config(workspace_id)

    content = get_content(draft)
    if not content.strip():
        print("No content found in draft.")
        return

    updated_content, applied = apply_gutenberg_blocks(content, presentation_config, page_type)

    if not applied:
        print(f"No reusable Gutenberg blocks applied for page_type: {page_type}")
        return

    print(f"Gutenberg blocks applied: {', '.join(applied)}")

    if args.dry_run:
        print("\n--- PREVIEW ---\n")
        print(updated_content)
        return

    set_content(draft, updated_content)
    draft["draft_status"] = "gutenberg_blocks_applied"

    registry["scope"] = "workspace"
    registry["workspace_id"] = workspace_id
    save_json(registry_path, registry)

    print(f"Draft updated: {draft_id}")
    print(f"Page type: {page_type}")
    print(f"Workspace registry: {registry_path}")


if __name__ == "__main__":
    main()
