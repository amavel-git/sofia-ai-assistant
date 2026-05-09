import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


SOFIA_ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = SOFIA_ROOT / "data" / "workspaces.json"
GLOBAL_BLOCKS_PATH = SOFIA_ROOT / "data" / "approved_content_blocks.json"


DEFAULT_MAX_BLOCKS = 6
MAX_BLOCK_TEXT_CHARS = 1200



def load_json(path: Path, default: Any):
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON in {path}: {e}")

    except Exception:
        return default


def normalize_language(language: str) -> str:
    language = str(language or "").strip().lower()

    if language.startswith("pt-br"):
        return "pt-BR"
    if language.startswith("pt"):
        return "pt-PT"
    if language.startswith("es"):
        return "es"
    if language.startswith("fr"):
        return "fr"
    if language.startswith("tr"):
        return "tr"
    if language.startswith("ru"):
        return "ru"
    if language.startswith("en"):
        return "en"

    return "en"


def language_candidates(language: str) -> List[str]:
    normalized = normalize_language(language)

    if normalized == "pt-PT":
        return ["pt-PT", "pt", "pt-BR"]
    if normalized == "pt-BR":
        return ["pt-BR", "pt", "pt-PT"]

    return [normalized]


def get_workspace(workspace_id: str) -> Dict[str, Any]:
    data = load_json(WORKSPACES_PATH, {"workspaces": []})

    for workspace in data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace

    raise RuntimeError(f"Workspace not found: {workspace_id}")


def get_workspace_profile_path(workspace: Dict[str, Any]) -> Path:
    folder_path = workspace.get("folder_path", "")

    if not folder_path:
        raise RuntimeError(f"Workspace has no folder_path: {workspace.get('workspace_id')}")

    return SOFIA_ROOT / folder_path / "local_content_profile.json"


def load_workspace_profile(workspace: Dict[str, Any]) -> Dict[str, Any]:
    path = get_workspace_profile_path(workspace)
    return load_json(path, {})


def load_approved_blocks() -> List[Dict[str, Any]]:
    data = load_json(GLOBAL_BLOCKS_PATH, [])

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        return data.get("blocks", [])

    return []


def tokenize(text: str) -> List[str]:
    text = str(text or "").lower()
    text = re.sub(r"[^\wÀ-ÿа-яА-ЯёЁçÇğĞıİöÖşŞüÜ]+", " ", text)
    return [token for token in text.split() if len(token) >= 3]


def score_block(block: Dict[str, Any], topic: str, tags_hint: Optional[List[str]] = None) -> int:
    score = 0

    topic_tokens = set(tokenize(topic))
    tags_hint = [str(tag).lower() for tag in (tags_hint or [])]

    block_tags = set(str(tag).lower() for tag in block.get("tags", []))
    block_category = str(block.get("category", "")).lower()
    block_text = str(block.get("text", "") or block.get("content", "") or "").lower()
    block_title = str(block.get("title", "") or block.get("block_id", "") or "").lower()
    source_type = str(block.get("source_type", "")).lower()

    # ------------------------------------------------------------
    # Strong preference for semantic/service/topic blocks
    # ------------------------------------------------------------

    preferred_categories = {
        "infidelity",
        "theft",
        "legal_tests",
        "polygraph_process",
        "examiner_qualifications",
        "ethics",
        "quality_standards",
        "confidentiality",
        "limitations",
        "sexual_harassment",
        "pre_employment",
        "maintenance_testing",
        "applications",
        "procedure",
        "results",
    }

    if block_category in preferred_categories:
        score += 20

    # ------------------------------------------------------------
    # FAQ blocks should help, but not dominate
    # ------------------------------------------------------------

    faq_penalty_categories = {
        "pricing",
        "booking",
        "questions",
        "duration",
        "location",
        "medication",
        "nervousness",
        "minors",
    }

    if block_category in faq_penalty_categories:
        score -= 4

    # ------------------------------------------------------------
    # Prefer approved semantic scraped blocks
    # ------------------------------------------------------------

    if source_type == "approved_scraped_website_candidate":
        score += 12

    # ------------------------------------------------------------
    # Tag hint matching
    # ------------------------------------------------------------

    for tag in tags_hint:
        if tag in block_tags:
            score += 12

        if tag == block_category:
            score += 15

    # ------------------------------------------------------------
    # Topic semantic/token matching
    # ------------------------------------------------------------

    for token in topic_tokens:
        if token in block_tags:
            score += 8

        if token in block_category:
            score += 7

        if token in block_title:
            score += 5

        if token in block_text:
            score += 2

    # ------------------------------------------------------------
    # Polygraph foundation knowledge
    # ------------------------------------------------------------

    useful_tags = {
        "procedure",
        "accuracy",
        "reliability",
        "confidentiality",
        "privacy",
        "ethics",
        "results",
        "limitations",
        "quality_standards",
        "examiner_qualifications",
    }

    if block_tags.intersection(useful_tags):
        score += 5

    # ------------------------------------------------------------
    # Penalize very short/weak blocks
    # ------------------------------------------------------------

    if len(block_text) < 120:
        score -= 6

    return score


def is_clean_enough_block(block: Dict[str, Any]) -> bool:
    source_type = str(block.get("source_type", "")).lower()
    text = str(block.get("text", "") or block.get("content", "") or "").strip()
    text_lower = text.lower()

    # Old FAQ blocks are generally curated already.
    if source_type != "approved_scraped_website_candidate":
        return True

    if not text:
        return False

    # Reject truncated scraped fragments.
    if text.endswith("..."):
        return False

    # Reject fragments that start mid-sentence.
    if text[0].islower():
        return False

    # Reject obvious navigation/contact/location noise.
    noisy_terms = [
        "features calling messaging groups status channels",
        "meta ai",
        "whatsapp",
        "telegram",
        "tlm:",
        "email:",
        "rua ",
        "avenida ",
        "porto",
        "lisboa",
        "faro",
        "contacto polígrafo portugal",
        "escritórios polígrafo portugal",
        "betclic",
        "youtube",
        "tvi",
        "sic",
    ]

    if any(term in text_lower for term in noisy_terms):
        return False

    # Reject entertainment/media-heavy fragments.
    entertainment_terms = [
        "maquina da verdade na televisão",
        "programas de televisão",
        "entretenimento",
        "influenciadores",
    ]

    if any(term in text_lower for term in entertainment_terms):
        return False

    return True


def select_relevant_blocks(
    workspace_id: str,
    topic: str = "",
    tags_hint: Optional[List[str]] = None,
    max_blocks: int = DEFAULT_MAX_BLOCKS,
) -> List[Dict[str, Any]]:
    workspace = get_workspace(workspace_id)
    language = normalize_language(workspace.get("language", "en"))
    accepted_languages = set(language_candidates(language))

    blocks = load_approved_blocks()

    # Safety filter:
    # - Old FAQ blocks without an approval field remain allowed.
    # - New scraped/site-derived blocks must have approval.approved == True.
    approved_blocks = []

    for block in blocks:
        approval = block.get("approval")

        if approval is None:
            approved_blocks.append(block)
            continue

        if isinstance(approval, dict) and approval.get("approved") is True:
            approved_blocks.append(block)

    matching_language_blocks = []

    for block in approved_blocks:
        if not is_clean_enough_block(block):
            continue

        block_language = normalize_language(block.get("language", ""))

        if block_language in accepted_languages:
            matching_language_blocks.append(block)

    scored = []

    for block in matching_language_blocks:
        score = score_block(block, topic, tags_hint=tags_hint)

        if score > 0:
            scored.append((score, block))

    scored.sort(key=lambda item: item[0], reverse=True)

    selected = []
    category_counts = {}

    for score, block in scored:
        category = str(block.get("category", "general")).lower()
        source_type = str(block.get("source_type", "")).lower()
        text = str(block.get("text", "") or block.get("content", "") or "").strip()

        # Avoid letting one category dominate the whole package.
        max_per_category = 2
        if category_counts.get(category, 0) >= max_per_category:
            continue

        # Avoid rough scraped fragments when possible.
        if source_type == "approved_scraped_website_candidate":
            if text and text[0].islower():
                continue
            if text.endswith("..."):
                continue

        selected.append(block)
        category_counts[category] = category_counts.get(category, 0) + 1

        if len(selected) >= max_blocks:
            break

    if not selected:
        selected = matching_language_blocks[:max_blocks]

    return selected


def build_knowledge_package(
    workspace_id: str,
    topic: str = "",
    tags_hint: Optional[List[str]] = None,
    max_blocks: int = DEFAULT_MAX_BLOCKS,
) -> Dict[str, Any]:
    workspace = get_workspace(workspace_id)

    profile = load_workspace_profile(workspace)

    blocks = select_relevant_blocks(
        workspace_id=workspace_id,
        topic=topic,
        tags_hint=tags_hint,
        max_blocks=max_blocks,
    )

    return {
        "workspace_id": workspace_id,

        # Added metadata for downstream logging/debugging
        "topic": topic,
        "tags_hint": tags_hint or [],

        "workspace": {
            "brand": workspace.get("brand"),
            "workspace_type": workspace.get("workspace_type"),
            "country": workspace.get("country"),
            "language": normalize_language(workspace.get("language", "en")),
            "domain": workspace.get("domain"),
            "folder_path": workspace.get("folder_path"),
        },

        "local_profile": profile,

        "selected_blocks": blocks,

        "knowledge_instructions": [
            "Use approved content blocks as controlled professional reference material, not as copy-paste text.",
            "Paraphrase, synthesize, and adapt the ideas in original wording suited to the page topic, country, language, and workspace profile.",
            "Before writing, extract the ideas from the blocks, then write a new original version. Do not mirror sentence structure from the source blocks.",
            "Do not reproduce full blocks verbatim.",
            "Only reuse exact wording when a block is explicitly marked reusable_exact_text: true.",
            "Respect preferred terms, avoided terms, service availability, manual-confirmation rules, and local CTA.",
            "Avoid absolute guarantees, legal-validity claims, or 100% accuracy claims.",
            "Preserve the professional meaning and safety limitations of the approved source material while writing naturally.",
        ]
    }


def format_package_for_prompt(package: Dict[str, Any]) -> str:
    profile = package.get("local_profile", {}) or {}
    blocks = package.get("selected_blocks", []) or []
    workspace = package.get("workspace", {}) or {}

    lines = []

    lines.append("APPROVED SOFIA KNOWLEDGE PACKAGE")
    lines.append("")
    lines.append(f"Workspace: {package.get('workspace_id')}")
    lines.append(f"Country: {workspace.get('country')}")
    lines.append(f"Language: {workspace.get('language')}")
    lines.append(f"Workspace type: {workspace.get('workspace_type')}")
    lines.append(f"Domain: {workspace.get('domain')}")
    lines.append("")

    preferred_terms = profile.get("preferred_terms", [])
    avoid_terms = profile.get("avoid", []) or profile.get("terms_to_avoid", [])
    available_services = profile.get("available_services", [])
    manual_confirmation = profile.get("manual_confirmation", [])
    coverage = profile.get("coverage", [])
    cta = profile.get("cta", "")

    if preferred_terms:
        lines.append("Preferred terminology:")
        for item in preferred_terms:
            lines.append(f"- {item}")
        lines.append("")

    if avoid_terms:
        lines.append("Avoid or handle carefully:")
        for item in avoid_terms:
            lines.append(f"- {item}")
        lines.append("")

    if coverage:
        lines.append("Coverage notes:")
        for item in coverage:
            lines.append(f"- {item}")
        lines.append("")

    if available_services:
        lines.append("Available services:")
        for item in available_services:
            lines.append(f"- {item}")
        lines.append("")

    if manual_confirmation:
        lines.append("Services / cases requiring manual confirmation:")
        for item in manual_confirmation:
            lines.append(f"- {item}")
        lines.append("")

    if cta:
        lines.append("Preferred CTA:")
        lines.append(str(cta))
        lines.append("")

    lines.append("Approved content blocks:")
    for block in blocks:
        block_id = block.get("block_id") or block.get("id") or "unknown_block"
        category = block.get("category") or ", ".join(block.get("tags", []))
        text = block.get("text") or block.get("content") or ""
        text = str(text).strip()

        # Prevent oversized prompt injection
        if len(text) > MAX_BLOCK_TEXT_CHARS:
            text = text[:MAX_BLOCK_TEXT_CHARS].rstrip() + "..."

        lines.append(f"\n[{block_id}]")
        lines.append(f"Category: {category}")
        lines.append(text)

    lines.append("")
    lines.append("Knowledge use rules:")
    for rule in package.get("knowledge_instructions", []):
        lines.append(f"- {rule}")

    return "\n".join(lines).strip()


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("python app/content_knowledge.py WORKSPACE_ID [topic]")
        print("")
        print("Example:")
        print('python app/content_knowledge.py local.ao "teste de polígrafo para furto interno"')
        return

    workspace_id = sys.argv[1]
    topic = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""

    package = build_knowledge_package(
        workspace_id=workspace_id,
        topic=topic,
        max_blocks=6,
    )

    print(format_package_for_prompt(package))


if __name__ == "__main__":
    main()