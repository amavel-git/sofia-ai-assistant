#!/usr/bin/env python3
"""
Sofia Gutenberg Block Renderer

Pure deterministic renderer.
No AI calls.
No WordPress API calls.
No workspace side effects.
"""

from __future__ import annotations

import html
from typing import Any, Dict, List


def _esc(value: Any) -> str:
    return html.escape(str(value or "").strip(), quote=True)


def _clean_links(links: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    cleaned = []
    used = set()

    for item in links or []:
        url = str(item.get("url") or item.get("target_url") or "").strip()
        anchor = str(item.get("anchor") or item.get("anchor_text") or item.get("target_title") or "").strip()

        if not url or not anchor:
            continue
        if url in used:
            continue

        cleaned.append({"url": url, "anchor": anchor})
        used.add(url)

    return cleaned


def render_heading_block(text: str, level: int = 2) -> str:
    level = int(level or 2)
    if level < 1 or level > 6:
        level = 2

    attrs = "" if level == 2 else f' {{"level":{level}}}'

    return "\n".join([
        f"<!-- wp:heading{attrs} -->",
        f"<h{level}>{_esc(text)}</h{level}>",
        "<!-- /wp:heading -->",
    ])


def render_paragraph_block(text: str) -> str:
    return "\n".join([
        "<!-- wp:paragraph -->",
        f"<p>{_esc(text)}</p>",
        "<!-- /wp:paragraph -->",
    ])


def render_list_block(items: List[str]) -> str:
    safe_items = [str(i or "").strip() for i in items or [] if str(i or "").strip()]
    if not safe_items:
        return ""

    return "\n".join([
        "<!-- wp:list -->",
        "<ul>",
        *[f"<li>{item}</li>" for item in safe_items],
        "</ul>",
        "<!-- /wp:list -->",
    ])


def render_links_list_block(links: List[Dict[str, Any]]) -> str:
    cleaned = _clean_links(links)
    if not cleaned:
        return ""

    items = [
        f'<a href="{_esc(item["url"])}">{_esc(item["anchor"])}</a>'
        for item in cleaned
    ]

    return render_list_block(items)


def render_button_block(button_text: str, button_url: str) -> str:
    if not button_text or not button_url:
        return ""

    return "\n".join([
        "<!-- wp:buttons -->",
        '<div class="wp-block-buttons">',
        '<!-- wp:button -->',
        '<div class="wp-block-button">',
        f'<a class="wp-block-button__link wp-element-button" href="{_esc(button_url)}">{_esc(button_text)}</a>',
        "</div>",
        "<!-- /wp:button -->",
        "</div>",
        "<!-- /wp:buttons -->",
    ])


def render_cta_block(
    title: str,
    text: str = "",
    button_text: str = "",
    button_url: str = "",
) -> str:
    parts = [render_heading_block(title, 2)]

    if text:
        parts.append(render_paragraph_block(text))

    if button_text and button_url:
        parts.append(render_button_block(button_text, button_url))

    return "\n\n".join([p for p in parts if p])


def render_related_services_block(
    heading: str = "Servicios relacionados",
    links: List[Dict[str, Any]] | None = None,
) -> str:
    parts = [
        render_heading_block(heading, 2),
        render_links_list_block(links or []),
    ]
    return "\n\n".join([p for p in parts if p])


def render_strategic_links_block(
    heading: str = "Enlaces relacionados",
    links: List[Dict[str, Any]] | None = None,
) -> str:
    return render_related_services_block(
        heading=heading,
        links=links or [],
    )


def render_contact_block(
    title: str = "Solicite información",
    text: str = "Puede comentar su caso de forma confidencial.",
    button_text: str = "Contacto confidencial",
    button_url: str = "/contacto-poligrafo/",
) -> str:
    return render_cta_block(
        title=title,
        text=text,
        button_text=button_text,
        button_url=button_url,
    )


def render_trust_block(
    title: str = "Información profesional",
    text: str = "Los exámenes poligráficos deben realizarse mediante un protocolo estructurado y por un examinador formado.",
) -> str:
    return "\n\n".join([
        render_heading_block(title, 2),
        render_paragraph_block(text),
    ])


def render_city_cta_block(
    city: str = "",
    title: str = "",
    text: str = "",
    button_text: str = "Solicitar información",
    button_url: str = "/contacto-poligrafo/",
) -> str:
    city = str(city or "").strip()
    if not title:
        title = f"Prueba de polígrafo en {city}" if city else "Prueba de polígrafo"

    if not text:
        text = "Puede solicitar orientación inicial de forma confidencial."

    return render_cta_block(
        title=title,
        text=text,
        button_text=button_text,
        button_url=button_url,
    )


def render_faq_block(
    heading: str = "Preguntas frecuentes",
    faqs: List[Dict[str, str]] | None = None,
) -> str:
    parts = [render_heading_block(heading, 2)]

    for item in faqs or []:
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()

        if not question or not answer:
            continue

        parts.append(render_heading_block(question, 3))
        parts.append(render_paragraph_block(answer))

    return "\n\n".join([p for p in parts if p])


def render_image_block(
    media_id: int | str,
    image_url: str,
    alt_text: str = "",
    caption: str = "",
    alignment: str = "right",
    size_slug: str = "large",
    class_name: str = "sofia-inline-image",
) -> str:
    """
    Render a standard Gutenberg image block.

    Intended for Sofia in-article images.
    """
    try:
        media_id_int = int(media_id)
    except Exception:
        return ""

    if media_id_int <= 0 or not image_url:
        return ""

    alignment = str(alignment or "right").strip().lower()
    if alignment not in {"left", "right", "center", "wide", "full"}:
        alignment = "right"

    size_slug = str(size_slug or "large").strip()
    class_name = str(class_name or "sofia-inline-image").strip()

    attrs = {
        "id": media_id_int,
        "sizeSlug": size_slug,
        "linkDestination": "none",
        "align": alignment,
        "className": class_name,
    }

    import json
    attrs_json = json.dumps(attrs, ensure_ascii=False, separators=(",", ":"))

    figure_classes = " ".join([
        "wp-block-image",
        f"align{alignment}",
        f"size-{size_slug}",
        class_name,
    ])

    caption_html = ""
    if caption:
        caption_html = f"\n<figcaption>{_esc(caption)}</figcaption>"

    return "\n".join([
        f"<!-- wp:image {attrs_json} -->",
        (
            f'<figure class="{_esc(figure_classes)}">'
            f'<img src="{_esc(image_url)}" alt="{_esc(alt_text)}" '
            f'class="wp-image-{media_id_int}"/>'
            f'{caption_html}</figure>'
        ),
        "<!-- /wp:image -->",
    ])


def render_reusable_block(block_id: int | str) -> str:
    """
    Render a synced/reusable WordPress block reference.

    Example:
    <!-- wp:block {"ref":1690} /-->
    """
    try:
        ref = int(block_id)
    except Exception:
        return ""

    if ref <= 0:
        return ""

    return f'<!-- wp:block {{"ref":{ref}}} /-->'


def render_named_block(
    block_name: str,
    gutenberg_blocks_config: Dict[str, Any],
    fallback_html: str = "",
) -> str:
    """
    Render a configured block by name.

    Preferred:
    - mode: reusable_block
    - block_id: 1690

    Fallback:
    - supplied fallback_html
    """
    block_config = gutenberg_blocks_config.get(block_name, {})
    if not isinstance(block_config, dict):
        return fallback_html or ""

    if not block_config.get("enabled", False):
        return ""

    mode = str(block_config.get("mode") or "").strip()

    if mode == "reusable_block":
        reusable = render_reusable_block(block_config.get("block_id"))
        if reusable:
            return reusable

    return fallback_html or ""


def render_yoast_faq_block(
    faqs: List[Dict[str, str]],
    heading: str = "Preguntas frecuentes",
) -> str:
    """
    Render Yoast FAQ Gutenberg block markup.

    The heading remains a normal Gutenberg heading.
    The questions/answers become a Yoast FAQ block.
    """
    cleaned = []

    for item in faqs or []:
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()

        if not question or not answer:
            continue

        cleaned.append({
            "question": question,
            "answer": answer,
        })

    if not cleaned:
        return ""

    parts = [
        render_heading_block(heading, 2),
        "",
        '<!-- wp:yoast/faq-block {"questions":[]} -->',
        '<div class="schema-faq wp-block-yoast-faq-block">',
    ]

    for item in cleaned:
        parts.extend([
            '<div class="schema-faq-section">',
            f'<strong class="schema-faq-question">{_esc(item["question"])}</strong>',
            f'<p class="schema-faq-answer">{_esc(item["answer"])}</p>',
            '</div>',
        ])

    parts.extend([
        '</div>',
        '<!-- /wp:yoast/faq-block -->',
    ])

    return "\n".join(parts)



if __name__ == "__main__":
    print(render_strategic_links_block(
        heading="Enlaces relacionados",
        links=[
            {"url": "/contacto-poligrafo/", "anchor": "Contacto confidencial"},
            {"url": "/recursos-humanos/poligrafo-recursos-humanos/", "anchor": "Polígrafo para recursos humanos"},
        ],
    ))
