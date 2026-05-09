#!/usr/bin/env python3
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]

CANDIDATES_FILE = SOFIA_ROOT / "data" / "source_knowledge" / "review_content_block_candidates.json"
APPROVED_FILE = SOFIA_ROOT / "data" / "approved_content_blocks.json"
BACKUP_DIR = SOFIA_ROOT / "data" / "backups"

MAX_APPROVE_TOTAL = 60

PREFERRED_CATEGORIES = [
    "polygraph_process",
    "examiner_qualifications",
    "ethics",
    "quality_standards",
    "confidentiality",
    "limitations",
    "price_variables",
    "infidelity",
    "theft",
    "legal_tests",
    "sexual_harassment",
    "pre_employment",
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def safe_now_for_filename():
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def load_json(path, default):
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def backup_approved_file():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    if not APPROVED_FILE.exists():
        return None

    backup_file = BACKUP_DIR / f"approved_content_blocks_{safe_now_for_filename()}.json"
    shutil.copy2(APPROVED_FILE, backup_file)

    return backup_file


def make_block_id(candidate):
    candidate_id = candidate.get("candidate_id", "")
    language = candidate.get("language", "xx")
    category = candidate.get("category", "general")

    if candidate_id:
        return candidate_id.replace("cand_", "site_approved_", 1)

    return f"site_approved_{language}_{category}_{safe_now_for_filename()}"


def normalize_candidate_as_approved_block(candidate):
    block_id = make_block_id(candidate)

    return {
        "block_id": block_id,
        "source_type": "approved_scraped_website_candidate",
        "source_id": candidate.get("candidate_id"),
        "source_domain": candidate.get("source_domain"),
        "source_url": candidate.get("source_url"),
        "source_title": candidate.get("source_title"),
        "source_extracted_at": candidate.get("source_extracted_at"),

        "language": candidate.get("language"),
        "category": candidate.get("category"),
        "detected_categories": candidate.get("detected_categories", []),
        "tags": candidate.get("tags", []),

        "summary": candidate.get("summary"),
        "key_points": candidate.get("key_points", []),

        "service_type": candidate.get("service_type", "general_polygraph"),
        "risk_level": candidate.get("risk_level", "standard"),

        "allowed_use": candidate.get("allowed_use", [
            "landing_page",
            "blog_post",
            "faq",
            "repair_expansion",
            "drafting_reference"
        ]),

        "reuse_policy": {
            "may_adapt": True,
            "copy_verbatim_only_if_needed": False,
            "avoid_duplicate_exact_text_across_pages": True,
            "must_paraphrase": True
        },

        "recommended_when": candidate.get("recommended_when", []),

        "text": candidate.get("text", ""),

        "approval": {
            "approved": True,
            "approved_at": now_iso(),
            "approval_method": "batch_candidate_approval_script",
            "notes": [
                "Approved as controlled semantic reference material.",
                "Do not copy verbatim in generated drafts.",
                "Use to paraphrase, synthesize, localize, and strengthen professional content."
            ]
        }
    }


def is_safe_to_auto_approve(candidate):
    category = candidate.get("category")
    risk = candidate.get("risk_level", "")
    text = str(candidate.get("text", "")).lower()

    if category not in PREFERRED_CATEGORIES:
        return False

    if risk == "requires_manual_review":
        return False

    risky_phrases = [
        "100%",
        "guaranteed",
        "garantizado",
        "garantido",
        "garanti",
        "infalível",
        "infalible",
        "infallible",
        "infaillible",
        "prova definitiva",
        "prueba definitiva",
    ]

    if any(phrase in text for phrase in risky_phrases):
        return False

    if len(text.split()) < 100:
        return False

    return True


def category_priority(category):
    try:
        return PREFERRED_CATEGORIES.index(category)
    except ValueError:
        return 999


def main():
    print("=== Sofia: Approve Content Block Candidates ===\n")

    candidates_data = load_json(CANDIDATES_FILE, {})
    approved_data = load_json(APPROVED_FILE, {
        "version": "0.1",
        "created_for": "Sofia SEO Assistant",
        "source_files": [],
        "notes": [],
        "blocks": []
    })

    candidates = candidates_data.get("candidates", [])
    blocks = approved_data.get("blocks", [])

    existing_ids = {
        block.get("block_id")
        for block in blocks
        if block.get("block_id")
    }

    safe_candidates = [
        c for c in candidates
        if is_safe_to_auto_approve(c)
    ]

    safe_candidates.sort(
        key=lambda c: (
            category_priority(c.get("category")),
            str(c.get("language")),
            -int(c.get("selection_score", 0))
        )
    )

    selected = safe_candidates[:MAX_APPROVE_TOTAL]

    if not selected:
        print("No safe candidates selected for approval.")
        return

    backup_file = backup_approved_file()

    added = 0
    skipped_duplicates = 0

    for candidate in selected:
        approved_block = normalize_candidate_as_approved_block(candidate)
        block_id = approved_block.get("block_id")

        if block_id in existing_ids:
            skipped_duplicates += 1
            continue

        blocks.append(approved_block)
        existing_ids.add(block_id)
        added += 1

    approved_data["blocks"] = blocks

    source_files = approved_data.get("source_files", [])
    if "review_content_block_candidates.json" not in source_files:
        source_files.append("review_content_block_candidates.json")
    approved_data["source_files"] = source_files

    notes = approved_data.get("notes", [])
    new_note = f"Added {added} approved semantic website-derived blocks on {now_iso()}."
    notes.append(new_note)
    approved_data["notes"] = notes

    save_json(APPROVED_FILE, approved_data)

    print(f"Backup created: {backup_file}")
    print(f"Candidates available: {len(candidates)}")
    print(f"Safe candidates selected: {len(selected)}")
    print(f"Blocks added: {added}")
    print(f"Duplicate blocks skipped: {skipped_duplicates}")
    print(f"Saved: {APPROVED_FILE}")


if __name__ == "__main__":
    main()