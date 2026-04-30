import json
from pathlib import Path
from datetime import datetime


BASE_DIR = Path(__file__).resolve().parent.parent

WORKSPACES_FILE = BASE_DIR / "data" / "workspaces.json"
CORE_TOPIC_MAP_FILE = BASE_DIR / "config" / "core_topic_map.json"
TOPIC_LOCALIZATION_FILE = BASE_DIR / "config" / "topic_localization_rules.json"


def load_json(file_path: Path):
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path: Path, data):
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def normalize(text):
    return str(text or "").strip().lower()


def infer_locale(language: str, workspace_id: str, domain: str):
    language = normalize(language)
    workspace_id = normalize(workspace_id)
    domain = normalize(domain)

    if language == "pt":
        if "br" in workspace_id or "brasil" in domain:
            return "pt-BR"
        return "pt-PT"

    if language == "en":
        return "en"

    if language == "es":
        return "es"

    if language == "fr":
        return "fr"

    if language == "ru":
        return "ru"

    if language == "tr":
        return "tr"

    return language


def get_workspace(workspaces_data, workspace_id):
    for workspace in workspaces_data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def get_topic_group(core_topic_map, workspace_type):
    return core_topic_map.get("topic_groups", {}).get(workspace_type, [])


def load_local_overrides(workspace_folder: Path):
    override_file = workspace_folder / "local_topic_overrides.json"

    if not override_file.exists():
        return {}

    try:
        data = load_json(override_file)
        return data.get("topic_overrides", {})
    except Exception:
        return {}


def collect_existing_items(site_structure, memory_data, drafts, workspace_id):
    items = []

    for page in site_structure.get("pages", []):
        combined = " ".join([
            page.get("url", ""),
            page.get("slug", ""),
            page.get("section", ""),
            page.get("page_type", "")
        ])

        items.append({
            "source": "site_structure",
            "type": page.get("page_type", ""),
            "url": page.get("url", ""),
            "slug": page.get("slug", ""),
            "text": normalize(combined)
        })

    for item in memory_data.get("draft_content", []):
        if isinstance(item, dict):
            combined = " ".join([
                item.get("title", ""),
                item.get("target_keyword", "")
            ])

            items.append({
                "source": "memory_draft",
                "type": "draft",
                "url": "",
                "slug": "",
                "text": normalize(combined)
            })

    for item in memory_data.get("published_content", []):
        if isinstance(item, dict):
            combined = " ".join([
                item.get("title", ""),
                item.get("target_keyword", ""),
                item.get("slug", "")
            ])

            items.append({
                "source": "memory_published",
                "type": "published",
                "url": item.get("url", ""),
                "slug": item.get("slug", ""),
                "text": normalize(combined)
            })

    for keyword in memory_data.get("keyword_index", []):
        items.append({
            "source": "keyword_index",
            "type": "keyword",
            "url": "",
            "slug": "",
            "text": normalize(keyword)
        })

    for draft in drafts:
        if draft.get("workspace_id") == workspace_id:
            combined = " ".join([
                draft.get("working_title", ""),
                draft.get("target_keyword", ""),
                draft.get("suggested_slug", "")
            ])

            items.append({
                "source": "draft_registry",
                "type": "draft",
                "url": "",
                "slug": draft.get("suggested_slug", ""),
                "text": normalize(combined)
            })

    return items


def expand_topic_terms(topic, localization_rules, locale):
    terms = set()
    exact_phrases = set()
    localized_concept_terms = set()

    topic_name = normalize(topic.get("topic_name", ""))
    topic_keywords = topic.get("keywords", [])
    concept_signals = topic.get("concept_signals", [])

    if topic_name:
        exact_phrases.add(topic_name)

    for keyword in topic_keywords:
        keyword_norm = normalize(keyword)

        if keyword_norm:
            exact_phrases.add(keyword_norm)
            terms.add(keyword_norm)

        for word in keyword_norm.replace("-", " ").split():
            if len(word) > 3:
                terms.add(word)

    for word in topic_name.replace("-", " ").split():
        if len(word) > 3:
            terms.add(word)

    locale_rules = localization_rules.get(locale, {})

    for signal in concept_signals:
        signal_norm = normalize(signal)

        if signal_norm:
            terms.add(signal_norm)

        related_terms = locale_rules.get(signal_norm, [])

        for term in related_terms:
            term_norm = normalize(term)
            if term_norm:
                terms.add(term_norm)
                localized_concept_terms.add(term_norm)

    return {
        "terms": list(terms),
        "exact_phrases": list(exact_phrases),
        "localized_concept_terms": list(localized_concept_terms)
    }


def score_topic_against_item(topic, topic_terms, item, local_override):
    text = item.get("text", "")
    slug = normalize(item.get("slug", ""))
    page_type = normalize(item.get("type", ""))

    exact_score = 0
    partial_score = 0
    matched_terms = []

    # 1. Exact local slug signals = strongest evidence
    exact_slug_signals = local_override.get("exact_slug_signals", [])
    if slug:
        for signal in exact_slug_signals:
            signal_norm = normalize(signal)
            if signal_norm and signal_norm in slug:
                exact_score += 10
                matched_terms.append(signal_norm)

    # 2. Partial local slug signals = related but not dedicated
    partial_slug_signals = local_override.get("partial_slug_signals", [])
    if slug:
        for signal in partial_slug_signals:
            signal_norm = normalize(signal)
            if signal_norm and signal_norm in slug:
                partial_score += 5
                matched_terms.append(signal_norm)

    # 3. Exact English phrase match
    for phrase in topic_terms.get("exact_phrases", []):
        if phrase and phrase in text:
            exact_score += 4
            matched_terms.append(phrase)

    # 4. Localized concept terms in slug = useful but not always exact
    if slug:
        for term in topic_terms.get("localized_concept_terms", []):
            term_norm = normalize(term)
            if term_norm and term_norm.replace(" ", "-") in slug:
                partial_score += 3
                matched_terms.append(term_norm)

    # 5. General meaningful terms = weak related signal
    meaningful_terms = []
    for term in topic_terms.get("terms", []):
        for part in term.replace("-", " ").split():
            if len(part) > 3:
                meaningful_terms.append(part)

    meaningful_terms = list(set(meaningful_terms))

    for part in meaningful_terms:
        if part in text:
            partial_score += 1
            matched_terms.append(part)

    # 6. Page type weighting
    if page_type in ["service_page", "pillar", "info_page", "faq", "blog_post"]:
        partial_score += 1

    if page_type in ["category", "home", "blog_index"]:
        partial_score -= 1

    return exact_score, partial_score, list(set(matched_terms))


def classify_topic_coverage(topic, existing_items, localization_rules, locale, local_overrides):
    topic_id = topic.get("topic_id", "")
    topic_terms = expand_topic_terms(topic, localization_rules, locale)
    local_override = local_overrides.get(topic_id, {})

    best_item = None
    best_exact = 0
    best_partial = 0
    best_matches = []

    for item in existing_items:
        exact_score, partial_score, matched_terms = score_topic_against_item(
            topic=topic,
            topic_terms=topic_terms,
            item=item,
            local_override=local_override
        )

        if (exact_score + partial_score) > (best_exact + best_partial):
            best_item = item
            best_exact = exact_score
            best_partial = partial_score
            best_matches = matched_terms

    dedicated_required = topic.get("dedicated_page_required", True)

    if best_exact >= 8:
        return {
            "coverage_status": "covered_exact",
            "matched_item": best_item,
            "matched_terms": best_matches,
            "reason": "Dedicated local slug signal or strong exact match was found."
        }

    if best_partial >= 4:
        if dedicated_required:
            return {
                "coverage_status": "covered_partial",
                "matched_item": best_item,
                "matched_terms": best_matches,
                "reason": "Related content exists, but no dedicated page was detected."
            }

        return {
            "coverage_status": "covered_exact",
            "matched_item": best_item,
            "matched_terms": best_matches,
            "reason": "Related informational content is sufficient for this non-dedicated topic."
        }

    return {
        "coverage_status": "missing",
        "matched_item": None,
        "matched_terms": [],
        "reason": "No sufficient localized or local override match found."
    }


def build_opportunity(topic, workspace, coverage):
    first_keyword = topic.get("keywords", [""])[0]
    topic_id = topic.get("topic_id", "")
    workspace_id = workspace.get("workspace_id", "")

    suggested_slug = first_keyword.lower().replace(" ", "-").replace("_", "-")

    return {
        "opportunity_id": f"OPP-{workspace_id}-{topic_id}",
        "created_at": datetime.now().strftime("%Y-%m-%d"),
        "workspace_id": workspace_id,
        "workspace_type": workspace.get("workspace_type", ""),
        "workspace_path": workspace.get("folder_path", ""),
        "domain": workspace.get("domain", ""),
        "market_code": workspace.get("market_code", ""),
        "language": workspace.get("language", ""),

        "topic_id": topic_id,
        "topic_name": topic.get("topic_name", ""),
        "priority": topic.get("priority", "medium"),
        "recommended_action": topic.get("recommended_action", "create_new_page"),
        "search_intent": topic.get("search_intent", ""),
        "target_keyword": first_keyword,
        "secondary_keywords": topic.get("keywords", [])[1:],
        "suggested_slug": suggested_slug,

        "coverage_status": coverage["coverage_status"],
        "matched_existing_url": coverage["matched_item"].get("url", "") if coverage["matched_item"] else "",
        "matched_existing_slug": coverage["matched_item"].get("slug", "") if coverage["matched_item"] else "",
        "matched_terms": coverage["matched_terms"],
        "reason": coverage["reason"],

        "status": "new",
        "notes": ""
    }


def main():
    print("=== Sofia: Find Content Gaps with Local Overrides ===\n")

    workspace_id = "local.ao"

    for required_file in [WORKSPACES_FILE, CORE_TOPIC_MAP_FILE, TOPIC_LOCALIZATION_FILE]:
        if not required_file.exists():
            print(f"ERROR: Required file not found: {required_file}")
            return

    try:
        workspaces_data = load_json(WORKSPACES_FILE)
        core_topic_map = load_json(CORE_TOPIC_MAP_FILE)
        localization_rules = load_json(TOPIC_LOCALIZATION_FILE)
    except Exception as e:
        print(f"ERROR: Could not read config files: {e}")
        return

    workspace = get_workspace(workspaces_data, workspace_id)

    if not workspace:
        print(f"ERROR: Workspace not found: {workspace_id}")
        return

    locale = infer_locale(
        language=workspace.get("language", ""),
        workspace_id=workspace.get("workspace_id", ""),
        domain=workspace.get("domain", "")
    )

    workspace_folder = BASE_DIR / workspace.get("folder_path", "")

    site_structure_file = workspace_folder / "site_structure.json"
    memory_file = workspace_folder / "site_content_memory.json"
    opportunities_file = workspace_folder / "content_opportunities.json"
    draft_registry_file = BASE_DIR / "sites" / "draft_registry.json"

    for required_file in [site_structure_file, memory_file, draft_registry_file]:
        if not required_file.exists():
            print(f"ERROR: Required file not found: {required_file}")
            return

    site_structure = load_json(site_structure_file)
    memory_data = load_json(memory_file)
    draft_registry = load_json(draft_registry_file)
    local_overrides = load_local_overrides(workspace_folder)

    topics = get_topic_group(core_topic_map, workspace.get("workspace_type", ""))

    existing_items = collect_existing_items(
        site_structure=site_structure,
        memory_data=memory_data,
        drafts=draft_registry.get("drafts", []),
        workspace_id=workspace_id
    )

    covered_topics = []
    partial_opportunities = []
    missing_opportunities = []

    print(f"Workspace: {workspace_id}")
    print(f"Domain: {workspace.get('domain', '')}")
    print(f"Locale used: {locale}")
    print(f"Local overrides loaded: {bool(local_overrides)}")
    print(f"Topics checked: {len(topics)}\n")

    for topic in topics:
        coverage = classify_topic_coverage(
            topic=topic,
            existing_items=existing_items,
            localization_rules=localization_rules,
            locale=locale,
            local_overrides=local_overrides
        )

        opportunity = build_opportunity(topic, workspace, coverage)

        if coverage["coverage_status"] == "covered_exact":
            print(f"Exact: {topic.get('topic_name')}")
            covered_topics.append(opportunity)
        elif coverage["coverage_status"] == "covered_partial":
            print(f"Partial: {topic.get('topic_name')}")
            partial_opportunities.append(opportunity)
        else:
            print(f"Missing: {topic.get('topic_name')}")
            missing_opportunities.append(opportunity)

    output_data = {
        "workspace_id": workspace_id,
        "domain": workspace.get("domain", ""),
        "locale": locale,
        "generated_at": datetime.now().strftime("%Y-%m-%d"),
        "covered_topics": covered_topics,
        "partial_opportunities": partial_opportunities,
        "missing_opportunities": missing_opportunities
    }

    save_json(opportunities_file, output_data)

    print("\nContent gap scan completed.")
    print(f"Covered exact: {len(covered_topics)}")
    print(f"Partial opportunities: {len(partial_opportunities)}")
    print(f"Missing opportunities: {len(missing_opportunities)}")
    print(f"Saved to: {opportunities_file}")


if __name__ == "__main__":
    main()