import json
import re
import unicodedata
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]


STOPWORDS = {
    "pt": {
        "de", "da", "do", "das", "dos", "e", "em", "para", "por", "com",
        "a", "o", "as", "os", "um", "uma", "sobre", "no", "na", "nos", "nas",
        "ao", "aos", "à", "às", "que", "como", "teste", "poligrafo", "polígrafo"
    },
    "es": {
        "de", "del", "la", "el", "las", "los", "y", "en", "para", "por",
        "con", "un", "una", "sobre", "que", "como", "prueba", "poligrafo", "polígrafo"
    },
    "fr": {
        "de", "du", "des", "la", "le", "les", "et", "en", "pour", "par",
        "avec", "un", "une", "sur", "que", "comment", "polygraphe"
    },
    "en": {
        "the", "a", "an", "and", "in", "for", "of", "to", "with", "on",
        "about", "how", "what", "polygraph", "test", "testing"
    }
}


def load_json(path, default=None):
    if not path.exists():
        return default if default is not None else {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def strip_accents(text):
    text = str(text or "")
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_text(text):
    text = strip_accents(str(text or "").lower())
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_language(language):
    language = str(language or "en").lower()

    if language.startswith("pt"):
        return "pt"
    if language.startswith("es"):
        return "es"
    if language.startswith("fr"):
        return "fr"

    return "en"


def slug_to_phrase(slug):
    slug = str(slug or "").strip("/")
    if "/" in slug:
        slug = slug.split("/")[-1]
    return slug.replace("-", " ").strip()


def significant_tokens(text, language="en"):
    language = normalize_language(language)
    normalized = normalize_text(text)
    stopwords = STOPWORDS.get(language, STOPWORDS["en"])

    tokens = [
        token for token in normalized.split()
        if token and token not in stopwords and len(token) >= 3
    ]

    return tokens


def unique_ordered(values):
    result = []
    seen = set()

    for value in values:
        if value is None:
            continue

        value = str(value).strip()
        if not value:
            continue

        key = normalize_text(value)
        if not key or key in seen:
            continue

        result.append(value)
        seen.add(key)

    return result


def token_similarity(query, candidate, language="en"):
    query_norm = normalize_text(query)
    candidate_norm = normalize_text(candidate)

    if not query_norm or not candidate_norm:
        return 0.0, "empty"

    if query_norm == candidate_norm:
        return 1.0, "exact_normalized_match"

    if len(query_norm) >= 8 and len(candidate_norm) >= 8:
        if query_norm in candidate_norm or candidate_norm in query_norm:
            return 0.90, "phrase_containment"

    q_tokens = set(significant_tokens(query, language))
    c_tokens = set(significant_tokens(candidate, language))

    if not q_tokens or not c_tokens:
        return 0.0, "no_significant_tokens"

    intersection = q_tokens.intersection(c_tokens)
    union = q_tokens.union(c_tokens)

    jaccard = len(intersection) / len(union)

    # Boost if most of the query's meaningful tokens are already covered.
    query_coverage = len(intersection) / len(q_tokens)

    score = max(jaccard, query_coverage * 0.85)

    if len(intersection) >= 3 and query_coverage >= 0.75:
        score = max(score, 0.78)

    if len(intersection) >= 2 and query_coverage >= 0.60:
        score = max(score, 0.55)

    return round(score, 3), f"shared_tokens: {', '.join(sorted(intersection))}"


def make_candidate(source_file, source_type, label, terms, url="", metadata=None):
    return {
        "source_file": source_file,
        "source_type": source_type,
        "label": str(label or ""),
        "terms": unique_ordered(terms),
        "url": str(url or ""),
        "metadata": metadata or {}
    }


def collect_from_site_structure(workspace_path):
    path = SOFIA_ROOT / workspace_path / "site_structure.json"
    data = load_json(path, {"pages": []})

    candidates = []

    for page in data.get("pages", []):
        slug = page.get("slug", "")
        url = page.get("url", "")
        page_type = page.get("page_type", "")
        section = page.get("section", "")

        terms = [
            slug_to_phrase(slug),
            slug,
            page_type,
            section
        ]

        candidates.append(
            make_candidate(
                source_file="site_structure.json",
                source_type="existing_site_page",
                label=url or slug,
                terms=terms,
                url=url,
                metadata={
                    "page_type": page_type,
                    "section": section,
                    "language": page.get("language", "")
                }
            )
        )

    return candidates


def collect_from_site_content_memory(workspace_path):
    path = SOFIA_ROOT / workspace_path / "site_content_memory.json"
    data = load_json(path, {})

    candidates = []

    for item in data.get("published_content", []):
        terms = [
            item.get("title"),
            item.get("target_keyword"),
            item.get("focus_keyphrase"),
            item.get("slug"),
            slug_to_phrase(item.get("slug")),
        ]

        candidates.append(
            make_candidate(
                source_file="site_content_memory.json",
                source_type="published_or_completed_memory",
                label=item.get("title") or item.get("target_keyword"),
                terms=terms,
                url=item.get("url", ""),
                metadata=item
            )
        )

    for item in data.get("draft_content", []):
        terms = [
            item.get("title"),
            item.get("target_keyword"),
        ]

        candidates.append(
            make_candidate(
                source_file="site_content_memory.json",
                source_type="draft_memory",
                label=item.get("title") or item.get("target_keyword"),
                terms=terms,
                url="",
                metadata=item
            )
        )

    for keyword in data.get("keyword_index", []):
        candidates.append(
            make_candidate(
                source_file="site_content_memory.json",
                source_type="keyword_index",
                label=keyword,
                terms=[keyword],
                url="",
                metadata={}
            )
        )

    for topic in data.get("content_topics", []):
        candidates.append(
            make_candidate(
                source_file="site_content_memory.json",
                source_type="content_topic",
                label=topic,
                terms=[topic],
                url="",
                metadata={}
            )
        )

    for topic in data.get("protected_topics", []):
        if isinstance(topic, dict):
            label = topic.get("topic") or topic.get("keyword") or ""
            terms = [label, topic.get("notes")]
            metadata = topic
        else:
            label = str(topic)
            terms = [label]
            metadata = {}

        candidates.append(
            make_candidate(
                source_file="site_content_memory.json",
                source_type="protected_topic",
                label=label,
                terms=terms,
                url="",
                metadata=metadata
            )
        )

    return candidates


def collect_from_content_inventory(workspace_path):
    path = SOFIA_ROOT / workspace_path / "content_inventory.json"
    data = load_json(path, {"content_items": []})

    candidates = []

    for item in data.get("content_items", []):
        terms = [
            item.get("title"),
            item.get("seo_title"),
            item.get("focus_keyphrase"),
            item.get("slug"),
            slug_to_phrase(item.get("slug")),
            item.get("primary_topic"),
        ]

        terms.extend(item.get("related_topics", []))
        terms.extend(item.get("cannibalization_terms", []))

        candidates.append(
            make_candidate(
                source_file="content_inventory.json",
                source_type="content_inventory_item",
                label=item.get("title") or item.get("primary_topic"),
                terms=terms,
                url=item.get("canonical_url") or item.get("wordpress_link") or "",
                metadata=item
            )
        )

    return candidates


def collect_from_market_intelligence(workspace_path):
    path = SOFIA_ROOT / workspace_path / "market_intelligence.json"
    data = load_json(path, {"market_topics": []})

    candidates = []

    for item in data.get("market_topics", []):
        our_coverage = str(item.get("our_coverage", "")).lower()
        recommended_action = str(item.get("recommended_action", "")).lower()

        # Market intelligence should usually inform, not block.
        # It becomes cannibalization-relevant only if it says we already cover the topic.
        coverage_indicates_existing = any(
            marker in our_coverage
            for marker in [
                "covered",
                "completed",
                "published",
                "draft",
                "prepared"
            ]
        )

        if not coverage_indicates_existing:
            continue

        terms = [
            item.get("topic"),
            item.get("intent"),
            item.get("recommended_action"),
        ]
        terms.extend(item.get("related_keywords", []))

        candidates.append(
            make_candidate(
                source_file="market_intelligence.json",
                source_type="market_topic_with_our_coverage",
                label=item.get("topic"),
                terms=terms,
                url="",
                metadata={
                    "our_coverage": our_coverage,
                    "recommended_action": recommended_action,
                    "priority": item.get("priority", "")
                }
            )
        )

    return candidates


def collect_candidates(workspace):
    workspace_path = workspace.get("folder_path", "")
    checked_sources = {}

    collectors = [
        ("site_structure.json", collect_from_site_structure),
        ("site_content_memory.json", collect_from_site_content_memory),
        ("content_inventory.json", collect_from_content_inventory),
        ("market_intelligence.json", collect_from_market_intelligence),
    ]

    all_candidates = []

    for source_name, collector in collectors:
        path = SOFIA_ROOT / workspace_path / source_name
        checked_sources[source_name] = {
            "exists": path.exists(),
            "path": str(path)
        }

        if not path.exists():
            checked_sources[source_name]["items_loaded"] = 0
            continue

        try:
            candidates = collector(workspace_path)
            all_candidates.extend(candidates)
            checked_sources[source_name]["items_loaded"] = len(candidates)
        except Exception as e:
            checked_sources[source_name]["error"] = f"{type(e).__name__}: {e}"
            checked_sources[source_name]["items_loaded"] = 0

    return all_candidates, checked_sources


def score_candidates(topic, workspace, extra_terms=None):
    language = workspace.get("language", "en")
    query_terms = unique_ordered([topic] + (extra_terms or []))

    candidates, checked_sources = collect_candidates(workspace)

    matches = []

    for candidate in candidates:
        best_score = 0.0
        best_reason = ""
        best_term = ""

        for query in query_terms:
            for candidate_term in candidate.get("terms", []):
                score, reason = token_similarity(query, candidate_term, language=language)

                if score > best_score:
                    best_score = score
                    best_reason = reason
                    best_term = candidate_term

        if best_score >= 0.35:
            matches.append({
                "score": best_score,
                "risk": classify_score(best_score, candidate.get("source_type")),
                "reason": best_reason,
                "matched_term": best_term,
                "source_file": candidate.get("source_file"),
                "source_type": candidate.get("source_type"),
                "label": candidate.get("label"),
                "url": candidate.get("url"),
                "metadata": compact_metadata(candidate.get("metadata", {})),
            })

    matches.sort(key=lambda x: x["score"], reverse=True)

    return matches, checked_sources


def compact_metadata(metadata):
    if not isinstance(metadata, dict):
        return {}

    allowed = [
        "draft_id",
        "content_id",
        "status",
        "published_live",
        "page_type",
        "section",
        "target_keyword",
        "focus_keyphrase",
        "slug",
        "wordpress_id",
        "wordpress_link",
        "canonical_url",
        "our_coverage",
        "recommended_action",
    ]

    return {
        key: metadata.get(key)
        for key in allowed
        if metadata.get(key) not in [None, ""]
    }


def classify_score(score, source_type=""):
    if source_type == "protected_topic" and score >= 0.55:
        return "protected_topic_review"

    if score >= 0.72:
        return "strong_overlap"

    if score >= 0.45:
        return "possible_overlap"

    return "weak_signal"


def summarize_result(matches, checked_sources):
    strong = [m for m in matches if m["risk"] == "strong_overlap"]
    possible = [m for m in matches if m["risk"] in ["possible_overlap", "protected_topic_review"]]

    if strong:
        top = strong[0]
        return {
            "result": "strong_overlap",
            "status": "strong_overlap",
            "notes": (
                "Strong cannibalization risk. Closest match found in "
                f"{top['source_file']} ({top['source_type']}): {top['label']}"
            )
        }

    if possible:
        top = possible[0]
        return {
            "result": "possible_overlap",
            "status": "possible_overlap",
            "notes": (
                "Possible cannibalization risk. Closest match found in "
                f"{top['source_file']} ({top['source_type']}): {top['label']}"
            )
        }

    existing_sources = [
        name for name, info in checked_sources.items()
        if info.get("exists") is True
    ]

    return {
        "result": "clear",
        "status": "clear",
        "notes": (
            "No significant overlap found across: "
            + ", ".join(existing_sources)
        )
    }


def check_workspace_cannibalization(workspace, topic, extra_terms=None, max_matches=8):
    matches, checked_sources = score_candidates(
        topic=topic,
        workspace=workspace,
        extra_terms=extra_terms or []
    )

    summary = summarize_result(matches, checked_sources)

    return {
        "checked": True,
        "result": summary["result"],
        "status": summary["status"],
        "notes": summary["notes"],
        "risk_score": matches[0]["score"] if matches else 0.0,
        "matches": matches[:max_matches],
        "checked_sources": checked_sources,
    }


def print_report(result):
    print("Cannibalization Check Result:")
    print(f"  Result: {result.get('result')}")
    print(f"  Risk score: {result.get('risk_score')}")
    print(f"  Notes: {result.get('notes')}")

    print("\nChecked sources:")
    for source, info in result.get("checked_sources", {}).items():
        exists = "yes" if info.get("exists") else "no"
        count = info.get("items_loaded", 0)
        print(f"  - {source}: exists={exists}, items={count}")

    matches = result.get("matches", [])
    if matches:
        print("\nTop matches:")
        for match in matches[:5]:
            print(
                f"  - {match.get('risk')} | score={match.get('score')} | "
                f"{match.get('source_file')} | {match.get('label')}"
            )
            if match.get("url"):
                print(f"    URL: {match.get('url')}")
            print(f"    Reason: {match.get('reason')}")


def main():
    import sys

    if len(sys.argv) < 3:
        print("Usage:")
        print('python app/cannibalization_checker.py WORKSPACE_ID "topic to check"')
        return

    workspace_id = sys.argv[1]
    topic = " ".join(sys.argv[2:]).strip()

    workspaces_path = SOFIA_ROOT / "data" / "workspaces.json"
    workspaces = load_json(workspaces_path, {"workspaces": []})

    workspace = None
    for item in workspaces.get("workspaces", []):
        if item.get("workspace_id") == workspace_id:
            workspace = item
            break

    if not workspace:
        print(f"ERROR: Workspace not found: {workspace_id}")
        return

    result = check_workspace_cannibalization(workspace, topic)
    print_report(result)


if __name__ == "__main__":
    main()