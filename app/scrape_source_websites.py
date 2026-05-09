#!/usr/bin/env python3
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


SOFIA_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = SOFIA_ROOT / "data" / "source_sites"

REQUEST_TIMEOUT = 20
CRAWL_DELAY_SECONDS = 1
MAX_PAGES_PER_SITE = 40


SOURCE_SITES = [
    {
        "source_id": "es_poligrafoespana",
        "language": "es",
        "base_url": "https://poligrafoespana.com",
        "start_urls": ["https://poligrafoespana.com"],
    },
    {
        "source_id": "pt_poligrafobrasil",
        "language": "pt-BR",
        "base_url": "https://poligrafobrasil.com",
        "start_urls": ["https://poligrafobrasil.com"],
    },
        {
        "source_id": "pt_poligrafoportugal",
        "language": "pt-PT",
        "base_url": "https://poligrafoportugal.com",
        "start_urls": ["https://poligrafoportugal.com"],
    },
    {
        "source_id": "fr_polygraphefrance",
        "language": "fr",
        "base_url": "https://polygraphefrance.com",
        "start_urls": ["https://polygraphefrance.com"],
    },
    {
        "source_id": "en_polygraphindia",
        "language": "en",
        "base_url": "https://polygraphindia.com",
        "start_urls": ["https://polygraphindia.com"],
    },
    {
        "source_id": "tr_polygraphturkey",
        "language": "tr",
        "base_url": "https://polygraphturkey.com/tr",
        "start_urls": ["https://polygraphturkey.com/tr"],
    },
    {
        "source_id": "ru_polygraphturkey",
        "language": "ru",
        "base_url": "https://polygraphturkey.com/ru",
        "start_urls": ["https://polygraphturkey.com/ru"],
    },
]


TOPIC_KEYWORDS = {
    "infidelity": [
        "infidelidad", "infidelidade", "infidélité", "infidelity",
        "aldatma", "измена"
    ],
    "pre_employment": [
        "pre-employment", "pre empleo", "preempleo", "pré-emploi",
        "pré emploi", "admissional", "işe alım", "при приеме"
    ],
    "maintenance_testing": [
        "maintenance", "periódico", "periodic", "périodique",
        "recorrente", "rutinario", "rutinário"
    ],
    "legal_tests": [
        "legal", "judicial", "court", "tribunal", "jurídico",
        "juridique", "mahkeme", "суд"
    ],
    "theft": [
        "hurto", "robo", "furto", "theft", "vol", "hırsızlık", "краж"
    ],
    "sexual_harassment": [
        "acoso sexual", "assédio sexual", "harcèlement sexuel",
        "sexual harassment", "cinsel taciz", "сексуаль"
    ],
    "polygraph_process": [
        "como funciona", "how it works", "fonctionne", "funciona",
        "procedimento", "procedure", "proceso", "processo",
        "süreç", "процедура"
    ],
    "price_variables": [
        "precio", "preço", "price", "tarif", "tarifa", "custo",
        "cost", "fiyat", "стоимость"
    ],
    "examiner_qualifications": [
        "examinador", "examiner", "examinateur", "qualified",
        "qualifications", "formación", "formação", "sertifika"
    ],
    "ethics": [
        "ética", "ethics", "éthique", "code of ethics",
        "código de ética", "confidencialidad", "confidentiality",
        "confidentialité", "gizlilik", "этика"
    ],
    "quality_standards": [
        "standards", "estándares", "normas", "qualidade",
        "quality", "qualité", "ASTM", "APA", "NCCA", "IAIPP"
    ],
    "limitations": [
        "limitaciones", "limitações", "limitations", "limites",
        "no es infalible", "não é infalível", "not infallible",
        "infaillible", "garanti", "100%"
    ],
    "faq": [
        "faq", "preguntas frecuentes", "perguntas frequentes",
        "questions fréquentes", "frequently asked questions"
    ],
}


SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf",
    ".zip", ".rar", ".mp4", ".mp3", ".avi", ".mov", ".css", ".js"
)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_space(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def word_count(text):
    return len([w for w in normalize_space(text).split(" ") if w.strip()])


def same_domain_or_path_scope(url, base_url):
    parsed_url = urlparse(url)
    parsed_base = urlparse(base_url)

    if parsed_url.netloc != parsed_base.netloc:
        return False

    base_path = parsed_base.path.strip("/")
    url_path = parsed_url.path.strip("/")

    if base_path:
        return url_path == base_path or url_path.startswith(base_path + "/")

    return True


def should_skip_url(url):
    clean = url.lower().split("#")[0].split("?")[0]

    if any(clean.endswith(ext) for ext in SKIP_EXTENSIONS):
        return True

    skip_parts = [
        "/wp-admin", "/wp-login", "/feed", "/comments",
        "/tag/", "/author/", "/category/", "/cart", "/checkout",
        "mailto:", "tel:", "whatsapp:"
    ]

    return any(part in clean for part in skip_parts)


def fetch_html(url):
    headers = {
        "User-Agent": "SofiaKnowledgeBot/1.0 (+controlled internal content extraction)"
    }

    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()

    if "text/html" not in content_type:
        return ""

    return response.text


def extract_page(url, html, source):
    soup = BeautifulSoup(html, "html.parser")

    for element in soup(["script", "style", "noscript", "svg", "form", "iframe"]):
        element.decompose()

    title = normalize_space(soup.title.get_text(" ")) if soup.title else ""

    meta_description = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        meta_description = normalize_space(meta.get("content"))

    headings = []
    for tag in ["h1", "h2", "h3"]:
        for node in soup.find_all(tag):
            text = normalize_space(node.get_text(" "))
            if text:
                headings.append({"tag": tag, "text": text})

    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find("div", class_=re.compile("content|entry|page|post", re.I))
        or soup.body
    )

    paragraphs = []
    if main:
        for node in main.find_all(["p", "li"]):
            text = normalize_space(node.get_text(" "))
            if len(text) >= 40:
                paragraphs.append(text)

    body_text = normalize_space(" ".join(paragraphs))

    categories = detect_categories(" ".join([title, meta_description, body_text]))

    return {
        "source_id": source["source_id"],
        "source_domain": urlparse(source["base_url"]).netloc,
        "language": source["language"],
        "url": url,
        "title": title,
        "meta_description": meta_description,
        "headings": headings,
        "body_text": body_text,
        "word_count": word_count(body_text),
        "detected_categories": categories,
        "extracted_at": now_iso(),
        "temporary_extraction": True,
        "approved_for_drafting": False,
        "notes": "Temporary raw extraction only. Do not use directly for drafting. Convert to reviewed content block candidates first."
    }


def detect_categories(text):
    text_lower = str(text or "").lower()
    categories = []

    for category, keywords in TOPIC_KEYWORDS.items():
        if any(keyword.lower() in text_lower for keyword in keywords):
            categories.append(category)

    return categories


def extract_links(url, html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    links = set()

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        absolute = urljoin(url, href)
        absolute = absolute.split("#")[0].rstrip("/")

        if not absolute:
            continue

        if should_skip_url(absolute):
            continue

        if same_domain_or_path_scope(absolute, base_url):
            links.add(absolute)

    return sorted(links)


def crawl_source_site(source):
    source_id = source["source_id"]
    output_dir = OUTPUT_ROOT / source_id
    output_dir.mkdir(parents=True, exist_ok=True)

    queue = list(source["start_urls"])
    visited = set()
    pages = []

    print(f"\n=== Scraping {source_id} ===")

    while queue and len(visited) < MAX_PAGES_PER_SITE:
        url = queue.pop(0).rstrip("/")

        if url in visited:
            continue

        if should_skip_url(url):
            continue

        try:
            print(f"Fetching: {url}")
            html = fetch_html(url)

            if not html:
                visited.add(url)
                continue

            page = extract_page(url, html, source)

            if page["word_count"] >= 80:
                pages.append(page)

            visited.add(url)

            for link in extract_links(url, html, source["base_url"]):
                if link not in visited and link not in queue:
                    queue.append(link)

            time.sleep(CRAWL_DELAY_SECONDS)

        except Exception as e:
            print(f"Skipped {url}: {e}")
            visited.add(url)

    output = {
        "source_id": source_id,
        "language": source["language"],
        "base_url": source["base_url"],
        "extracted_at": now_iso(),
        "temporary_extraction": True,
        "approved_for_drafting": False,
        "pages_found": len(pages),
        "pages": pages,
    }

    output_file = output_dir / "live_content_extracts.json"

    with output_file.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved: {output_file}")
    print(f"Pages saved: {len(pages)}")


def main():
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    for source in SOURCE_SITES:
        crawl_source_site(source)

    print("\nDone.")
    print("Temporary extraction files saved under:")
    print(OUTPUT_ROOT)


if __name__ == "__main__":
    main()