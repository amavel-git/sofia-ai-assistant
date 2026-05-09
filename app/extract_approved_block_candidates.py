#!/usr/bin/env python3
import json
import re
from datetime import datetime, timezone
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]

SOURCE_SITES_DIR = SOFIA_ROOT / "data" / "source_sites"
OUTPUT_DIR = SOFIA_ROOT / "data" / "source_knowledge"
OUTPUT_FILE = OUTPUT_DIR / "content_block_candidates.json"

MIN_SECTION_WORDS = 80
MAX_BLOCK_TEXT_CHARS = 1800


CATEGORY_KEYWORDS = {
    "infidelity": ["infidelidad", "infidelidade", "infidélité", "infidelity", "aldatma", "измена"],
    "pre_employment": ["pre-employment", "pre empleo", "preempleo", "pré-emploi", "admissional", "işe alım", "при приеме"],
    "maintenance_testing": ["maintenance", "periódico", "periodic", "périodique", "recorrente", "rutinario", "rutinário"],
    "legal_tests": ["legal", "judicial", "tribunal", "court", "jurídico", "juridique", "mahkeme", "суд"],
    "theft": ["hurto", "robo", "furto", "theft", "vol", "hırsızlık", "краж"],
    "sexual_harassment": ["acoso sexual", "assédio sexual", "harcèlement sexuel", "sexual harassment", "cinsel taciz", "сексуаль"],
    "polygraph_process": ["como funciona", "how it works", "fonctionne", "procedimento", "procedure", "proceso", "processo", "süreç", "процедура"],
    "price_variables": ["precio", "preço", "price", "tarif", "tarifa", "custo", "cost", "fiyat", "стоимость"],
    "examiner_qualifications": ["examinador", "examiner", "examinateur", "qualified", "qualifications", "formación", "formação", "sertifika"],
    "ethics": ["ética", "ethics", "éthique", "code of ethics", "código de ética", "gizlilik", "этика"],
    "quality_standards": ["standards", "estándares", "normas", "qualidade", "quality", "qualité", "ASTM", "APA", "NCCA", "IAIPP"],
    "limitations": ["limitaciones", "limitações", "limitations", "limites", "no es infalible", "não é infalível", "not infallible", "infaillible"],
    "confidentiality": ["confidencialidad", "confidencialidade", "confidentiality", "confidentialité", "privacy", "privacidad", "gizlilik"],
    "faq": ["faq", "preguntas frecuentes", "perguntas frequentes", "questions fréquentes", "frequently asked questions"],
}


CATEGORY_TAGS = {
    "infidelity": ["infidelity", "private_case", "specific_issue"],
    "pre_employment": ["pre_employment", "screening", "human_resources"],
    "maintenance_testing": ["maintenance_testing", "periodic_testing", "screening"],
    "legal_tests": ["legal", "case_specific", "limitations"],
    "theft": ["theft", "corporate_investigation", "specific_issue"],
    "sexual_harassment": ["sexual_harassment", "workplace", "sensitive_case"],
    "polygraph_process": ["procedure", "steps", "methodology"],
    "price_variables": ["pricing", "quote", "manual_confirmation"],
    "examiner_qualifications": ["examiner", "qualifications", "professional_standards"],
    "ethics": ["ethics", "consent", "questions"],
    "quality_standards": ["quality", "standards", "professional_review"],
    "limitations": ["limitations", "accuracy", "safety"],
    "confidentiality": ["confidentiality", "privacy", "results"],
    "faq": ["faq", "questions"],
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default):
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def normalize_space(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def word_count(text):
    return len([w for w in normalize_space(text).split(" ") if w.strip()])


def clean_text(text):
    text = normalize_space(text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return text


def detect_categories(text):
    text_lower = str(text or "").lower()
    found = []

    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword.lower() in text_lower for keyword in keywords):
            found.append(category)

    return found


def choose_primary_category(categories):
    priority = [
        "theft",
        "infidelity",
        "pre_employment",
        "maintenance_testing",
        "legal_tests",
        "sexual_harassment",
        "polygraph_process",
        "examiner_qualifications",
        "ethics",
        "quality_standards",
        "limitations",
        "confidentiality",
        "price_variables",
        "faq",
    ]

    for item in priority:
        if item in categories:
            return item

    return categories[0] if categories else "general_polygraph"


def build_tags(categories):
    tags = []

    for category in categories:
        tags.extend(CATEGORY_TAGS.get(category, []))

    unique = []
    for tag in tags:
        if tag not in unique:
            unique.append(tag)

    return unique or ["general"]


def safe_excerpt(text, max_chars=MAX_BLOCK_TEXT_CHARS):
    text = clean_text(text)

    if len(text) <= max_chars:
        return text

    shortened = text[:max_chars].rsplit(" ", 1)[0].strip()
    return shortened + "..."


def split_body_into_chunks(body_text, max_words=220):
    words = normalize_space(body_text).split()
    chunks = []

    current = []

    for word in words:
        current.append(word)

        if len(current) >= max_words:
            chunks.append(" ".join(current))
            current = []

    if current:
        chunks.append(" ".join(current))

    return chunks


def make_candidate_id(language, source_id, category, index):
    safe_language = str(language or "xx").replace("-", "_").lower()
    safe_source = re.sub(r"[^a-z0-9_]+", "_", source_id.lower())
    safe_category = re.sub(r"[^a-z0-9_]+", "_", category.lower())
    return f"cand_{safe_language}_{safe_source}_{safe_category}_{index:04d}"


def summarize_from_headings(page):
    headings = page.get("headings", [])
    useful = []

    for h in headings:
        text = h.get("text")
        if text:
            useful.append(text)

    if useful:
        return " / ".join(useful[:4])

    return page.get("title", "")


def candidate_from_page_chunk(page, chunk, index):
    categories = detect_categories(
        " ".join([
            page.get("title", ""),
            page.get("meta_description", ""),
            summarize_from_headings(page),
            chunk,
        ])
    )

    primary_category = choose_primary_category(categories)
    language = page.get("language", "")
    source_id = page.get("source_id", "")

    candidate = {
        "candidate_id": make_candidate_id(language, source_id, primary_category, index),
        "status": "candidate",
        "approved": False,
        "temporary_candidate": True,

        "source_type": "scraped_website_text",
        "source_id": source_id,
        "source_domain": page.get("source_domain"),
        "source_url": page.get("url"),
        "source_title": page.get("title"),
        "source_extracted_at": page.get("extracted_at"),

        "language": language,
        "category": primary_category,
        "detected_categories": categories,
        "tags": build_tags(categories),

        "service_type": primary_category if primary_category != "general_polygraph" else "general_polygraph",
        "risk_level": infer_risk_level(primary_category, chunk),

        "allowed_use": [
            "landing_page",
            "blog_post",
            "faq",
            "repair_expansion",
            "drafting_reference"
        ],

        "reuse_policy": {
            "may_adapt": True,
            "copy_verbatim_only_if_needed": False,
            "avoid_duplicate_exact_text_across_pages": True,
            "must_paraphrase": True
        },

        "recommended_when": build_recommended_when(primary_category, categories),

        "summary": summarize_from_headings(page),
        "key_points": extract_key_points(chunk),

        "text": safe_excerpt(chunk),

        "approval_notes": [
            "Review before moving into approved_content_blocks.json.",
            "Do not approve if the text contains risky legal, accuracy, guarantee, or copied promotional claims.",
            "Approved version should be treated as semantic guidance, not as copy-paste text."
        ],

        "created_at": now_iso()
    }

    return candidate


def infer_risk_level(category, text):
    text_lower = str(text or "").lower()

    risky_terms = [
        "100%",
        "guaranteed",
        "garantizado",
        "garantido",
        "garanti",
        "infalível",
        "infalible",
        "infallible",
        "infaillible",
        "legal proof",
        "prueba legal",
        "prova legal",
    ]

    if any(term in text_lower for term in risky_terms):
        return "requires_manual_review"

    if category in {"legal_tests", "sexual_harassment", "pre_employment", "maintenance_testing"}:
        return "sensitive_context"

    if category in {"limitations", "ethics", "confidentiality", "price_variables"}:
        return "guarded_safe"

    return "standard"


def build_recommended_when(primary_category, categories):
    recommended = [primary_category]
    recommended.extend(categories)

    unique = []
    for item in recommended:
        if item and item not in unique:
            unique.append(item)

    return unique


def extract_key_points(text, max_points=5):
    text = clean_text(text)

    sentences = re.split(r"(?<=[.!?])\s+", text)
    points = []

    for sentence in sentences:
        sentence = clean_text(sentence)

        if len(sentence) < 60:
            continue

        if sentence not in points:
            points.append(sentence)

        if len(points) >= max_points:
            break

    return points


def load_all_extracted_pages():
    pages = []

    for path in SOURCE_SITES_DIR.glob("*/live_content_extracts.json"):
        data = load_json(path, {})
        for page in data.get("pages", []):
            if page.get("word_count", 0) >= MIN_SECTION_WORDS:
                pages.append(page)

    return pages


def main():
    print("=== Sofia: Extract Approved Block Candidates ===\n")

    pages = load_all_extracted_pages()

    if not pages:
        print("No extracted pages found.")
        print(f"Expected files under: {SOURCE_SITES_DIR}")
        return

    candidates = []
    counter = 1

    for page in pages:
        body_text = page.get("body_text", "")

        if word_count(body_text) < MIN_SECTION_WORDS:
            continue

        chunks = split_body_into_chunks(body_text, max_words=220)

        for chunk in chunks:
            if word_count(chunk) < MIN_SECTION_WORDS:
                continue

            candidate = candidate_from_page_chunk(page, chunk, counter)
            candidates.append(candidate)
            counter += 1

    output = {
        "version": "0.1",
        "created_for": "Sofia SEO Assistant",
        "created_at": now_iso(),
        "source": "Temporary scraped live_content_extracts.json files",
        "approved_for_drafting": False,
        "notes": [
            "These are candidate blocks only.",
            "Do not use directly in Sofia drafting.",
            "Review, clean, and approve before appending to data/approved_content_blocks.json.",
            "Approved blocks must be used as semantic guidance, not copy-paste text."
        ],
        "candidate_count": len(candidates),
        "candidates": candidates,
    }

    save_json(OUTPUT_FILE, output)

    print(f"Candidates created: {len(candidates)}")
    print(f"Saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()