#!/usr/bin/env python3
"""
Insert uploaded in-article images into assembled WordPress content.

Placements supported:
- after_h2_2
- after_h2_3
- before_faq

Default fallback:
- after_h2_2
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from app.workspace_paths import get_workspace_draft_registry_path
from app.gutenberg_blocks import render_image_block


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def find_draft(registry, draft_id):
    for draft in registry.get("drafts", []):
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def get_content(draft):
    return (
        draft.get("wordpress_content")
        or draft.get("assembled_wordpress_content")
        or draft.get("html_content")
        or draft.get("generated_content", {}).get("content", "")
    )


def set_content(draft, content):
    # Save inserted image blocks into every downstream content field that may
    # be used by create_wordpress_draft.py or update_wordpress_draft.py.
    draft["wordpress_content"] = content
    draft["assembled_wordpress_content"] = content
    draft["html_content"] = content


def choose_alignment(index):
    return "right" if index % 2 == 0 else "left"


def build_image_block(slot, index):
    metadata = slot.get("image_metadata") or {}
    slot_id = slot.get("slot_id", f"in_article_{index + 1}")

    block = render_image_block(
        media_id=slot.get("media_id"),
        image_url=slot.get("wordpress_url"),
        alt_text=metadata.get("alt_text", ""),
        caption="",
        alignment=choose_alignment(index),
    )

    return (
        f"<!-- sofia:image-slot:start {slot_id} -->\n"
        f"{block}\n"
        f"<!-- sofia:image-slot:end {slot_id} -->"
    )


def insert_after_h2_number(content, block, h2_number=2):
    matches = list(re.finditer(r"<h2[^>]*>.*?</h2>", content, flags=re.I | re.S))

    if len(matches) < h2_number:
        return content, False

    target = matches[h2_number - 1]
    insert_pos = target.end()

    # Prefer inserting after the first paragraph following that H2.
    paragraph = re.search(r"</p>", content[insert_pos:], flags=re.I)
    if paragraph:
        insert_pos = insert_pos + paragraph.end()

    return content[:insert_pos] + "\n\n" + block + "\n\n" + content[insert_pos:], True


def insert_before_faq(content, block):
    patterns = [
        r"<!-- wp:yoast/faq-block",
        r"<h2[^>]*>\s*Preguntas frecuentes\s*</h2>",
        r"<h2[^>]*>\s*Frequently Asked Questions\s*</h2>",
        r"<h2[^>]*>\s*FAQ\s*</h2>",
    ]

    for pattern in patterns:
        match = re.search(pattern, content, flags=re.I | re.S)
        if match:
            return content[:match.start()] + "\n\n" + block + "\n\n" + content[match.start():], True

    return content + "\n\n" + block, True



def insert_before_cta(content, block):
    patterns = [
        r"<h2[^>]*>\s*¿Necesita orientación[^<]*</h2>",
        r"<h2[^>]*>\s*Contacto Confidencial\s*</h2>",
        r"<h2[^>]*>\s*Contacte con nosotros\s*</h2>",
        r"<!--\s*sofia:contact-cta",
    ]

    for pattern in patterns:
        match = re.search(pattern, content, flags=re.I | re.S)
        if match:
            return content[:match.start()] + "\n\n" + block + "\n\n" + content[match.start():], True

    return content + "\n\n" + block, True


def already_inserted(content, media_id, slot_id=None):
    if slot_id and f"sofia:image-slot:start {slot_id}" in content:
        return True

    return f"wp-image-{media_id}" in content or f'"id":{media_id}' in content


def main():
    if len(sys.argv) != 3:
        print("Usage:")
        print("python -m app.image_assets.insert_in_article_images WORKSPACE_ID DRAFT_ID")
        sys.exit(1)

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]

    registry_path = get_workspace_draft_registry_path(workspace_id)
    registry = load_json(registry_path)
    draft = find_draft(registry, draft_id)

    if not draft:
        raise SystemExit(f"Draft not found: {draft_id}")

    content = get_content(draft)

    if not content:
        raise SystemExit("No WordPress/html content found in draft.")

    preparation = draft.get("image_asset_preparation") or {}
    slots = preparation.get("in_article_images") or []

    inserted = []
    skipped = []

    for index, slot in enumerate(slots):
        if not slot.get("uploaded") or not slot.get("media_id") or not slot.get("wordpress_url"):
            skipped.append({
                "slot_id": slot.get("slot_id"),
                "reason": "not uploaded or missing media_id/wordpress_url",
            })
            continue

        slot_id = slot.get("slot_id")

        #
        # Prevent duplicate Sofia image blocks.
        #
        if slot_id and f"sofia:image-slot:start {slot_id}" in content:
            skipped.append({
                "slot_id": slot_id,
                "reason": "already inserted (slot marker)",
            })
            continue

        if already_inserted(
            content,
            slot.get("media_id"),
            slot_id=slot_id,
        ):
            skipped.append({
                "slot_id": slot_id,
                "reason": "already inserted",
            })
            continue

        block = build_image_block(slot, index)
        placement = slot.get("image_metadata", {}).get("placement") or slot.get("placement")

        if placement == "after_h2_2":
            content, ok = insert_after_h2_number(content, block, h2_number=2)
        elif placement == "after_h2_3":
            content, ok = insert_after_h2_number(content, block, h2_number=3)
        elif placement == "after_h2_4":
            content, ok = insert_after_h2_number(content, block, h2_number=4)
        elif placement == "before_faq":
            # Legacy image placement. Images should not be inserted near FAQ.
            placement = "before_cta"
            content, ok = insert_before_cta(content, block)
        elif placement == "before_cta":
            content, ok = insert_before_cta(content, block)
        else:
            placement = "after_h2_2"
            content, ok = insert_after_h2_number(content, block, h2_number=2)

        if ok:
            inserted.append({
                "slot_id": slot.get("slot_id"),
                "media_id": slot.get("media_id"),
                "placement": placement,
            })

    set_content(draft, content)

    draft["in_article_images_inserted"] = {
        "inserted_count": len(inserted),
        "inserted": inserted,
        "skipped": skipped,
    }

    save_json(registry_path, registry)

    print(json.dumps(draft["in_article_images_inserted"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
