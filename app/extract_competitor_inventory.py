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


def clean_text(text):
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_domain_key(url):
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path
    host = host.lower().replace("www.", "")
    host = re.sub(r"[^a-z0-9]+", "_", host).strip("_")
    return host or "competitor"


def find_workspace(workspaces, workspace_id):
    for workspace in workspaces.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def get_workspace_folder(workspace):
    folder_path = workspace.get("folder_path")
    if not folder_path:
        raise ValueError("Workspace has no folder_path")
    return ROOT / folder_path


def fetch_text(url, timeout=30):
    headers = {
        "User-Agent": "SofiaCompetitorInventoryBot/1.0 (+market intelligence; respectful crawl)"
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def competitor_base_url(domain):
    parsed = urlparse(domain)

    if not parsed.scheme:
        domain = "https://" + domain
        parsed = urlparse(domain)

    return f"{parsed.scheme}://{parsed.netloc}"


def discover_sitemap_urls(domain):
    base = competitor_base_url(domain)

    candidates = [
        urljoin(base.rstrip("/") + "/", "sitemap_index.xml"),
        urljoin(base.rstrip("/") + "/", "sitemap.xml"),
        urljoin(base.rstrip("/") + "/", "page-sitemap.xml"),
        urljoin(base.rstrip("/") + "/", "post-sitemap.xml"),
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


def collect_urls_from_sitemaps(domain, max_urls=100):
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

    return list(unique.values())[:max_urls], sitemap_urls


def fallback_seed_urls(domain):
    base = competitor_base_url(domain)
    return [
        {
            "loc": domain.rstrip("/"),
            "lastmod": None,
            "source": "manual_domain"
        },
        {
            "loc": base.rstrip("/"),
            "lastmod": None,
            "source": "base_domain"
        }
    ]


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



def infer_competitor_page_type(url, title="", h1=""):
    text = normalize_text(f"{url} {title} {h1}")
    url_text = normalize_text(url)

    spanish_locations = [
        "madrid", "barcelona", "valencia", "sevilla", "malaga", "bilbao",
        "alicante", "castellon", "zaragoza", "granada", "cordoba", "cadiz",
        "huelva", "jaen", "almeria", "huesca", "teruel", "valladolid",
        "salamanca", "segovia", "soria", "zamora", "avila", "burgos",
        "leon", "palencia", "toledo", "cuenca", "guadalajara", "albacete",
        "ciudad real", "badajoz", "caceres", "girona", "lleida", "tarragona",
        "cantabria", "ceuta", "melilla", "las palmas", "santa cruz de tenerife",
        "murcia", "oviedo", "gijon", "pamplona", "logrono", "vitoria",
        "santander", "a coruna", "pontevedra", "ourense", "lugo"
    ]

    if any(x in text for x in ["precio", "precios", "tarifa", "coste", "cuanto cuesta"]):
        return "pricing_page"

    if any(x in text for x in ["faq", "preguntas", "respuestas", "dudas"]):
        return "faq_page"

    if any(x in text for x in ["formacion", "curso", "certificacion", "capacitacion"]):
        return "training_page"

    if any(x in text for x in ["reserva", "cita", "contacto", "ubicaciones", "localizacion"]):
        return "conversion_page"

    if any(location in text for location in spanish_locations):
        return "city_page"

    if any(x in text for x in [
        "infidelidad",
        "fidelidad",
        "robo",
        "hurto",
        "empresa",
        "laboral",
        "recursos humanos",
        "pre empleo",
        "pre laboral",
        "abogados",
        "legal",
        "denuncias falsas",
        "agresion sexual",
        "familia",
        "pareja",
        "testimonio",
        "verificacion personal"
    ]):
        return "service_page"

    if any(x in url_text for x in ["/category/", "/tag/"]):
        return "archive_page"

    if any(x in text for x in [
        "blog", "noticias", "articulo", "consejos", "guia", "guias",
        "mitos", "realidades", "historia", "ciencia", "precision",
        "falsos positivos", "contramedidas", "inconclusos", "ansiedad",
        "medicacion", "metodologias", "neurobiologia"
    ]):
        return "blog_or_article"

    return "content_page"


def infer_competitor_topics(url, title="", h1=""):
    text = normalize_text(f"{url} {title} {h1}")

    topic_rules = {
        "infidelity": ["infidelidad", "fidelidad", "pareja", "parejas"],
        "internal_theft": ["robo", "hurto", "apropiacion indebida", "fraude interna", "empresa", "empresas"],
        "human_resources": ["laboral", "recursos humanos", "pre empleo", "pre laboral", "seleccion"],
        "legal_defense": ["legal", "abogados", "justicia", "denuncias falsas", "defensa", "testimonio"],
        "sexual_offense": ["agresion sexual", "abuso sexual"],
        "pricing": ["precio", "precios", "tarifa", "coste"],
        "training": ["formacion", "curso", "certificacion", "capacitacion", "poligrafia"],
        "appointment_booking": ["reserva", "cita", "reserva online", "contacto"],
        "pre_test_evaluation": ["evaluacion previa", "previa al examen", "pre test", "pretest"],
        "procedure": ["procedimiento", "como prepararse", "prepararse", "guia completa", "tipos de preguntas"],
        "question_formulation": ["preguntas poligrafo", "tipos de preguntas", "preguntas de poligrafo"],
        "inconclusive_results": ["inconcluso", "inconclusos", "resultados inconclusos"],
        "false_positives": ["falso positivo", "falsos positivos"],
        "countermeasures": ["contramedidas", "enganar poligrafo"],
        "anxiety_medication": ["ansiedad", "nerviosismo", "medicacion", "condiciones medicas", "farmacologia"],
        "methodology": ["cqt", "cit", "metodologia", "metodologias", "evaluacion numerica", "evaluacion global"],
        "technology": ["analogico", "digital", "inteligencia artificial", "machine learning"],
        "science_reliability": ["fiabilidad", "precision", "ciencia", "cientifico", "validez", "neurobiologia", "sistema nervioso autonomo"],
        "history": ["historia", "evolucion"],
        "media": ["cine", "television", "hollywood"],
        "security_services": ["servicios inteligencia", "seguridad nacional", "cni"],
        "faq": ["faq", "preguntas frecuentes", "preguntas", "respuestas"],
        "city_madrid": ["madrid"],
        "city_barcelona": ["barcelona"],
        "city_valencia": ["valencia"],
        "city_sevilla": ["sevilla"],
        "city_malaga": ["malaga"],
        "city_bilbao": ["bilbao"],
        "city_zaragoza": ["zaragoza"],
        "city_alicante": ["alicante"],
        "city_granada": ["granada"],
        "city_cordoba": ["cordoba"],
        "city_cadiz": ["cadiz"],
        "city_valladolid": ["valladolid"],
        "city_toledo": ["toledo"],
        "city_las_palmas": ["las palmas"],
        "city_tenerife": ["santa cruz de tenerife", "tenerife"]
    }

    topics = []
    for topic, terms in topic_rules.items():
        if any(term in text for term in terms):
            topics.append(topic)

    return topics or ["general_polygraph"]

def inspect_url(url):
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

    return {
        "url": url,
        "status": "ok",
        "title": title,
        "h1": h1,
        "meta_description": meta_description,
        "page_type": infer_competitor_page_type(url, title, h1),
        "topics": infer_competitor_topics(url, title, h1),
        "word_count_estimate": len(clean_text(html).split())
    }


def build_statistics(pages):
    ok_pages = [p for p in pages if p.get("status") == "ok"]

    page_type_counts = {}
    topic_counts = {}

    for page in ok_pages:
        page_type = page.get("page_type", "unknown")
        page_type_counts[page_type] = page_type_counts.get(page_type, 0) + 1

        for topic in page.get("topics", []):
            topic_counts[topic] = topic_counts.get(topic, 0) + 1

    return {
        "total_pages": len(ok_pages),
        "failed_pages": len([p for p in pages if p.get("status") != "ok"]),
        "page_type_counts": page_type_counts,
        "topic_counts": topic_counts
    }


def load_market_intelligence(workspace_folder):
    path = workspace_folder / "market_intelligence.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing market_intelligence.json: {path}")
    return load_json(path)


def save_scrape_log(workspace_folder, log_entry):
    path = workspace_folder / "competitor_scrape_log.json"

    if path.exists():
        try:
            data = load_json(path)
        except Exception:
            data = {}
    else:
        data = {}

    data.setdefault("workspace_id", log_entry.get("workspace_id"))
    data.setdefault("scrapes", [])
    data["scrapes"].append(log_entry)

    save_json(path, data)


def extract_competitor(workspace_id, workspace_folder, competitor, max_urls=100):
    domain = competitor.get("domain", "")
    name = competitor.get("name") or domain

    print(f"\n=== Competitor: {name} ===")
    print(f"Domain: {domain}")

    sitemap_entries, sitemap_urls = collect_urls_from_sitemaps(domain, max_urls=max_urls)

    source = "sitemap"
    if not sitemap_entries:
        print("No sitemap URLs found. Using fallback seed URLs.")
        sitemap_entries = fallback_seed_urls(domain)
        source = "fallback"

    pages = []

    for index, entry in enumerate(sitemap_entries, start=1):
        url = entry.get("loc")
        print(f"[{index}/{len(sitemap_entries)}] {url}")
        page = inspect_url(url)
        page["lastmod"] = entry.get("lastmod")
        pages.append(page)

    inventory = {
        "version": "1.0",
        "workspace_id": workspace_id,
        "competitor": {
            "name": name,
            "domain": domain,
            "competitor_type": competitor.get("competitor_type", ""),
            "priority": competitor.get("priority", ""),
            "language": competitor.get("language", ""),
            "country": competitor.get("country", ""),
            "status": competitor.get("status", "")
        },
        "scan": {
            "scanned_at": now_iso(),
            "source": source,
            "sitemaps_checked": sitemap_urls,
            "max_urls": max_urls
        },
        "pages": pages,
        "statistics": build_statistics(pages)
    }

    output_dir = workspace_folder / "competitor_inventories"
    output_file = output_dir / f"{normalize_domain_key(domain)}.json"
    save_json(output_file, inventory)

    log_entry = {
        "workspace_id": workspace_id,
        "competitor": name,
        "domain": domain,
        "scanned_at": inventory["scan"]["scanned_at"],
        "source": source,
        "pages_ok": inventory["statistics"]["total_pages"],
        "pages_failed": inventory["statistics"]["failed_pages"],
        "output_file": str(output_file.relative_to(ROOT))
    }
    save_scrape_log(workspace_folder, log_entry)

    print("Saved:", output_file)
    print(json.dumps(inventory["statistics"], indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="Extract competitor inventories for a Sofia workspace.")
    parser.add_argument("workspace_id", help="Workspace ID, e.g. local.es")
    parser.add_argument("--max-urls", type=int, default=80)
    parser.add_argument("--competitor", help="Optional domain/name filter")
    args = parser.parse_args()

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, args.workspace_id)

    if not workspace:
        print(f"Workspace not found: {args.workspace_id}")
        sys.exit(1)

    workspace_folder = get_workspace_folder(workspace)
    market_intelligence = load_market_intelligence(workspace_folder)

    competitors = market_intelligence.get("competitors", [])

    if args.competitor:
        needle = args.competitor.lower()
        competitors = [
            c for c in competitors
            if needle in (c.get("domain", "") + " " + c.get("name", "")).lower()
        ]

    competitors = [
        c for c in competitors
        if c.get("status", "active") == "active"
    ]

    if not competitors:
        print("No active competitors found.")
        sys.exit(0)

    print(f"Workspace: {args.workspace_id}")
    print(f"Competitors to scan: {len(competitors)}")

    for competitor in competitors:
        try:
            extract_competitor(
                workspace_id=args.workspace_id,
                workspace_folder=workspace_folder,
                competitor=competitor,
                max_urls=args.max_urls
            )
        except Exception as e:
            print(f"ERROR scanning {competitor.get('domain')}: {e}")


if __name__ == "__main__":
    main()