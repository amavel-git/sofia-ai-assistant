import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone


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


def get_workspace_folder(workspace):
    return ROOT / workspace["folder_path"]


def slug_from_url(url):
    path = urlparse(url).path.strip("/")
    if not path:
        return ""
    return path.split("/")[-1]


def section_from_url(url):
    path = urlparse(url).path.strip("/")
    if not path:
        return "home"
    parts = path.split("/")
    if len(parts) > 1:
        return parts[0]
    return "top_level"


def normalize_text(text):
    text = str(text or "").lower()
    replacements = {
        "á": "a", "à": "a", "ä": "a",
        "é": "e", "è": "e", "ë": "e",
        "í": "i", "ì": "i", "ï": "i",
        "ó": "o", "ò": "o", "ö": "o",
        "ú": "u", "ù": "u", "ü": "u",
        "ñ": "n",
        "ç": "c"
    }

    for a, b in replacements.items():
        text = text.replace(a, b)

    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def infer_topic(url, title="", h1=""):
    text = normalize_text(f"{url} {title} {h1}")

    topic_rules = {
        "infidelity": ["infidelidad", "fidelidad", "parejas", "terapia pareja"],
        "internal_theft": ["robo", "hurto", "fraude interna", "desvio", "empresas"],
        "sexual_offense": ["agresion sexual", "abuso sexual"],
        "legal_defense": ["legal", "abogados", "justicia", "denuncias falsas", "inocencia"],
        "human_resources": ["recursos humanos", "laboral", "pre empleo", "pre laboral", "empleo"],
        "pricing": ["precio", "precios", "coste", "tarifa"],
        "science_reliability": ["ciencia", "cientifica", "fiabilidad", "base cientifica"],
        "history": ["historia"],
        "faq": ["faq", "preguntas", "respuestas", "dudas"],
        "media": ["medios", "television", "telecinco", "salvame", "deluxe"],
        "city_madrid": ["madrid"],
        "city_barcelona": ["barcelona"],
        "city_valencia": ["valencia"],
        "city_sevilla": ["sevilla"],
        "city_malaga": ["malaga"],
        "city_bilbao": ["bilbao"]
    }

    matches = []
    for topic, terms in topic_rules.items():
        if any(term in text for term in terms):
            matches.append(topic)

    return matches[0] if matches else "general_polygraph"


def normalize_page_type(raw_type, url, title="", h1=""):
    text = normalize_text(f"{url} {title} {h1}")

    if raw_type in ["pricing_page", "faq_page", "city_page"]:
        return raw_type

    if any(term in text for term in ["category/", "/tag/"]):
        if "/tag/" in url:
            return "tag_archive"
        return "category_archive"

    if any(term in text for term in ["madrid", "barcelona", "valencia", "sevilla", "malaga", "bilbao"]):
        return "city_page"

    if any(term in text for term in [
        "infidelidad",
        "agresion sexual",
        "abogados",
        "denuncias falsas",
        "empresas",
        "laboral",
        "robo",
        "hurto",
        "justicia",
        "recursos humanos"
    ]):
        return "service_page"

    if any(term in text for term in [
        "ciencia",
        "fiabilidad",
        "historia",
        "funcionamiento",
        "preguntas",
        "respuestas",
        "precio"
    ]):
        return "info_page"

    if any(term in url for term in [
        "/casos-legales/",
        "/casos-personales/",
        "/recursos-humanos/",
        "/ciencia-poligrafica/",
        "/consejos-faq/",
        "/opinion-medios/"
    ]):
        return "blog_post"

    if url.rstrip("/") == urlparse(url).scheme + "://" + urlparse(url).netloc:
        return "home"

    return raw_type or "content_page"


def build_site_structure(inventory, workspace_id):
    pages = []

    for item in inventory.get("pages", []):
        if item.get("status") != "ok":
            continue

        url = item.get("url", "")
        title = item.get("title", "")
        h1 = item.get("h1", "")
        raw_type = item.get("page_type", "")

        page_type = normalize_page_type(raw_type, url, title, h1)

        pages.append({
            "url": url,
            "slug": slug_from_url(url),
            "section": section_from_url(url),
            "page_type": page_type,
            "topic": infer_topic(url, title, h1),
            "language": "es-ES",
            "title": title,
            "h1": h1,
            "lastmod": item.get("lastmod")
        })

    return {
        "workspace_id": workspace_id,
        "domain": inventory.get("domain", ""),
        "source": "live_site_inventory",
        "last_updated": now_iso(),
        "pages": pages
    }


def build_site_content_memory(inventory, workspace_id, domain):
    content_topics = []
    keyword_index = []
    published_content = []

    for item in inventory.get("pages", []):
        if item.get("status") != "ok":
            continue

        url = item.get("url", "")
        title = item.get("title", "")
        h1 = item.get("h1", "")
        page_type = normalize_page_type(item.get("page_type", ""), url, title, h1)
        topic = infer_topic(url, title, h1)

        published_content.append({
            "url": url,
            "title": title,
            "h1": h1,
            "page_type": page_type,
            "topic": topic,
            "status": "live",
            "source": "live_site_inventory"
        })

        if topic not in content_topics:
            content_topics.append(topic)

        for value in [title, h1, slug_from_url(url)]:
            norm = normalize_text(value)
            if norm and norm not in keyword_index:
                keyword_index.append(norm)

    return {
        "workspace_info": {
            "workspace_id": workspace_id,
            "brand": "local_sites",
            "workspace_type": "local_market",
            "language": "es",
            "market_code": workspace_id.split(".")[-1],
            "domain": domain,
            "base_path": "/"
        },
        "published_content": published_content,
        "draft_content": [],
        "content_topics": content_topics,
        "keyword_index": keyword_index,
        "protected_topics": [],
        "cannibalization_notes": [],
        "content_opportunities": []
    }



def is_archive_or_system_page(url, page_type):
    url = str(url or "").lower()
    page_type = str(page_type or "").lower()

    if page_type in ["tag_archive", "category_archive"]:
        return True

    if "/tag/" in url or "/category/" in url:
        return True

    if "/spice_post_slider/" in url:
        return True

    return False


def evaluate_page_health(item, page_type=None):
    reasons = []

    url = item.get("url", "")
    page_type = page_type or item.get("page_type", "")
    archive_or_system = is_archive_or_system_page(url, page_type)

    title = (item.get("title") or "").strip()
    h1 = (item.get("h1") or "").strip()
    meta_description = (item.get("meta_description") or "").strip()
    word_count = item.get("word_count_estimate") or 0

    if archive_or_system:
        return {
            "needs_review": False,
            "review_reasons": [],
            "is_archive_or_system": True
        }

    if not title:
        reasons.append("missing_title")

    if not h1:
        reasons.append("missing_h1")

    if not meta_description:
        reasons.append("missing_meta_description")

    if word_count and word_count < 600:
        reasons.append("thin_content")

    lastmod = item.get("lastmod")

    if lastmod:
        try:
            dt = datetime.fromisoformat(lastmod.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - dt).days

            if age_days > 365 * 3:
                reasons.append("old_content")
        except Exception:
            pass

    return {
        "needs_review": bool(reasons),
        "review_reasons": reasons,
        "is_archive_or_system": False
    }


def build_content_inventory(inventory, workspace_id):
    items = []

    review_summary = {
        "needs_review": 0,
        "archive_or_system_pages": 0,
        "old_content": 0,
        "thin_content": 0,
        "missing_title": 0,
        "missing_h1": 0,
        "missing_meta_description": 0
    }

    for item in inventory.get("pages", []):
        if item.get("status") != "ok":
            continue

        url = item.get("url", "")
        title = item.get("title", "")
        h1 = item.get("h1", "")

        page_type = normalize_page_type(item.get("page_type", ""), url, title, h1)
        health = evaluate_page_health(item, page_type=page_type)

        if health.get("is_archive_or_system"):
            review_summary["archive_or_system_pages"] += 1

        if health["needs_review"]:
            review_summary["needs_review"] += 1

        for reason in health["review_reasons"]:
            if reason not in review_summary:
                review_summary[reason] = 0
            review_summary[reason] += 1

        items.append({
            "content_id": f"LIVE-{len(items) + 1:04d}",
            "source": "live_site_inventory",
            "url": url,
            "title": title,
            "h1": h1,
            "page_type": page_type,
            "topic": infer_topic(url, title, h1),
            "is_archive_or_system": health.get("is_archive_or_system", False),
            "status": "live",
            "lastmod": item.get("lastmod"),
            "word_count_estimate": item.get("word_count_estimate"),
            "internal_links_count": item.get("internal_links_count"),
            "needs_review": health["needs_review"],
            "review_reasons": health["review_reasons"]
        })

    return {
        "version": "1.0",
        "workspace_id": workspace_id,
        "last_updated": now_iso(),
        "review_summary": review_summary,
        "items": items
    }


def summarize_structure(site_structure):
    counts = {}

    for page in site_structure.get("pages", []):
        key = page.get("page_type", "unknown")
        counts[key] = counts.get(key, 0) + 1

    return counts


def main():
    parser = argparse.ArgumentParser(description="Build Sofia site intelligence files from live_site_inventory.json.")
    parser.add_argument("workspace_id", help="Workspace ID, e.g. local.es")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, args.workspace_id)

    if not workspace:
        print(f"Workspace not found: {args.workspace_id}")
        raise SystemExit(1)

    folder = get_workspace_folder(workspace)
    inventory_path = folder / "live_site_inventory.json"

    if not inventory_path.exists():
        print(f"Missing live_site_inventory.json: {inventory_path}")
        raise SystemExit(1)

    inventory = load_json(inventory_path)
    domain = inventory.get("domain") or workspace.get("domain", "")

    site_structure = build_site_structure(inventory, args.workspace_id)
    site_memory = build_site_content_memory(inventory, args.workspace_id, domain)
    content_inventory = build_content_inventory(inventory, args.workspace_id)

    outputs = {
        "site_structure.json": site_structure,
        "site_content_memory.json": site_memory,
        "content_inventory.json": content_inventory
    }

    if args.dry_run:
        print("Dry run only. No files written.")
    else:
        for filename, data in outputs.items():
            save_json(folder / filename, data)

    print("\n=== Site Intelligence Build Summary ===")
    print(f"Workspace: {args.workspace_id}")
    print(f"Pages processed: {len(site_structure.get('pages', []))}")
    print("Page type counts:")
    for key, value in sorted(summarize_structure(site_structure).items()):
        print(f"- {key}: {value}")

    print("\nOutputs:")
    for filename in outputs:
        print(f"- {folder / filename}")


if __name__ == "__main__":
    main()