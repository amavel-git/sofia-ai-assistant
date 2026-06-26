import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests


ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = ROOT / "data" / "workspaces.json"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_workspace(workspaces, workspace_id):
    for workspace in workspaces.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def clean_text(text):
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_workspace_folder(workspace):
    folder_path = workspace.get("folder_path")
    if not folder_path:
        raise ValueError("Workspace has no folder_path")
    return ROOT / folder_path


def fetch_text(url, timeout=30):
    headers = {
        "User-Agent": "SofiaSiteInventoryBot/1.0 (+site intelligence; respectful crawl)"
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def discover_sitemap_urls(domain):
    candidates = [
        urljoin(domain.rstrip("/") + "/", "sitemap_index.xml"),
        urljoin(domain.rstrip("/") + "/", "sitemap.xml"),
        urljoin(domain.rstrip("/") + "/", "page-sitemap.xml"),
        urljoin(domain.rstrip("/") + "/", "post-sitemap.xml"),
    ]

    found = []

    for url in candidates:
        try:
            text = fetch_text(url, timeout=15)
            if "<urlset" in text or "<sitemapindex" in text:
                found.append(url)
        except Exception:
            continue

    return list(dict.fromkeys(found))


def parse_sitemap_xml(xml_text):
    urls = []
    root = ET.fromstring(xml_text)

    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}", 1)[0] + "}"

    if root.tag.endswith("sitemapindex"):
        for sitemap in root.findall(f".//{ns}sitemap"):
            loc = sitemap.find(f"{ns}loc")
            if loc is not None and loc.text:
                urls.append({"type": "sitemap", "loc": loc.text.strip()})

    elif root.tag.endswith("urlset"):
        for url in root.findall(f".//{ns}url"):
            loc = url.find(f"{ns}loc")
            lastmod = url.find(f"{ns}lastmod")
            if loc is not None and loc.text:
                urls.append({
                    "type": "url",
                    "loc": loc.text.strip(),
                    "lastmod": lastmod.text.strip() if lastmod is not None and lastmod.text else None
                })

    return urls


def collect_urls_from_sitemaps(domain, max_urls=300):
    sitemap_urls = discover_sitemap_urls(domain)
    collected = []
    visited_sitemaps = set()

    queue = list(sitemap_urls)

    while queue:
        sitemap_url = queue.pop(0)

        if sitemap_url in visited_sitemaps:
            continue

        visited_sitemaps.add(sitemap_url)

        try:
            xml_text = fetch_text(sitemap_url, timeout=20)
            entries = parse_sitemap_xml(xml_text)
        except Exception:
            continue

        for entry in entries:
            if entry["type"] == "sitemap":
                queue.append(entry["loc"])
            elif entry["type"] == "url":
                collected.append(entry)

        if len(collected) >= max_urls:
            break

    unique = {}
    for item in collected:
        loc = item.get("loc")
        if loc and loc not in unique:
            unique[loc] = item

    return list(unique.values())[:max_urls]


def extract_tag(html, tag):
    pattern = rf"<{tag}[^>]*>(.*?)</{tag}>"
    match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return clean_text(match.group(1))


def extract_title(html):
    return extract_tag(html, "title")


def extract_h1(html):
    return extract_tag(html, "h1")


def extract_meta_description(html):
    patterns = [
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']'
    ]

    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return clean_text(match.group(1))

    return ""


def extract_internal_links(html, domain):
    links = re.findall(r'<a[^>]+href=["\'](.*?)["\']', html, flags=re.IGNORECASE)
    base_host = urlparse(domain).netloc.lower()

    internal = []

    for href in links:
        href = href.strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue

        absolute = urljoin(domain.rstrip("/") + "/", href)
        parsed = urlparse(absolute)

        if parsed.netloc.lower() == base_host:
            clean_url = absolute.split("#", 1)[0]
            internal.append(clean_url.rstrip("/"))

    return sorted(set(internal))


def infer_page_type(url, title="", h1=""):
    text = f"{url} {title} {h1}".lower()

    if "/blog" in text:
        return "blog_post"

    if any(x in text for x in ["precio", "precios", "tarifa", "coste", "cuanto cuesta"]):
        return "pricing_page"

    if any(x in text for x in ["madrid", "barcelona", "valencia", "sevilla", "zaragoza", "malaga", "bilbao"]):
        return "city_page"

    if any(x in text for x in ["infidelidad", "robo", "hurto", "empresa", "recursos-humanos", "pre-empleo", "abogados", "legal"]):
        return "service_page"

    if any(x in text for x in ["preguntas", "faq", "dudas"]):
        return "faq_page"

    if url.rstrip("/").count("/") <= 2:
        return "home_or_top_level"

    return "content_page"


def inspect_url(url, domain):
    try:
        html = fetch_text(url, timeout=25)
    except Exception as e:
        return {
            "url": url,
            "status": "fetch_failed",
            "error": str(e)
        }

    title = extract_title(html)
    h1 = extract_h1(html)
    meta_description = extract_meta_description(html)
    internal_links = extract_internal_links(html, domain)

    return {
        "url": url,
        "status": "ok",
        "title": title,
        "h1": h1,
        "meta_description": meta_description,
        "page_type": infer_page_type(url, title, h1),
        "word_count_estimate": len(clean_text(html).split()),
        "internal_links_count": len(internal_links),
        "internal_links_sample": internal_links[:20]
    }


def build_statistics(pages):
    ok_pages = [p for p in pages if p.get("status") == "ok"]

    def count_type(page_type):
        return len([p for p in ok_pages if p.get("page_type") == page_type])

    return {
        "total_pages": len(ok_pages),
        "failed_pages": len([p for p in pages if p.get("status") != "ok"]),
        "service_pages": count_type("service_page"),
        "city_pages": count_type("city_page"),
        "blog_posts": count_type("blog_post"),
        "pricing_pages": count_type("pricing_page"),
        "faq_pages": count_type("faq_page")
    }


def main():
    parser = argparse.ArgumentParser(description="Extract live website inventory for a Sofia workspace.")
    parser.add_argument("workspace_id", help="Workspace ID, e.g. local.es")
    parser.add_argument("--max-urls", type=int, default=150)
    args = parser.parse_args()

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, args.workspace_id)

    if not workspace:
        print(f"Workspace not found: {args.workspace_id}")
        sys.exit(1)

    domain = workspace.get("domain")
    if not domain:
        print("Workspace has no domain")
        sys.exit(1)

    folder = get_workspace_folder(workspace)
    output_path = folder / "live_site_inventory.json"

    print(f"Extracting live site inventory for {args.workspace_id}")
    print(f"Domain: {domain}")

    sitemap_entries = collect_urls_from_sitemaps(domain, max_urls=args.max_urls)

    pages = []
    for index, entry in enumerate(sitemap_entries, start=1):
        url = entry.get("loc")
        print(f"[{index}/{len(sitemap_entries)}] {url}")
        page = inspect_url(url, domain)
        page["lastmod"] = entry.get("lastmod")
        pages.append(page)

    inventory = {
        "version": "1.0",
        "workspace_id": args.workspace_id,
        "domain": domain,
        "last_scan": now_iso(),
        "source": "sitemap",
        "pages": pages,
        "statistics": build_statistics(pages)
    }

    save_json(output_path, inventory)

    print("\nInventory saved:")
    print(output_path)
    print(json.dumps(inventory["statistics"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()