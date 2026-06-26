import json
import sys
from pathlib import Path
from datetime import datetime, timezone

from page_blueprints import build_page_blueprint_package

try:
    from opportunity_intelligence import analyze_opportunity
except ModuleNotFoundError:
    from app.opportunity_intelligence import analyze_opportunity


SOFIA_ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = SOFIA_ROOT / "data" / "workspaces.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def find_workspace(workspaces_data: dict, workspace_id: str):
    for workspace in workspaces_data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace

    return None


def get_workspace_folder(workspace: dict) -> Path:
    folder_path = workspace.get("folder_path", "")

    if not folder_path:
        raise ValueError(f"Workspace has no folder_path: {workspace.get('workspace_id')}")

    return SOFIA_ROOT / folder_path


def load_language_profile(workspace_folder: Path) -> dict:
    profile_path = workspace_folder / "language_profile.json"

    if not profile_path.exists():
        return {}

    return load_json(profile_path)


def get_template_type(content_type: str) -> str:
    content_type = str(content_type or "").strip().lower()

    if content_type in ["landing_page", "service_page", "website_page"]:
        return "service"

    if content_type in ["blog_post", "article", "post"]:
        return "blog"

    return "service"


def build_blueprint_source(opp: dict) -> dict:
    seo = opp.get("seo_brief", {}) or {}

    return {
        "content_type": (
            opp.get("page_type")
            or opp.get("recommended_content_type")
            or opp.get("content_type")
            or ""
        ),
        "page_type": opp.get("page_type", ""),
        "blueprint_id": opp.get("blueprint_id", ""),
        "intent_type": opp.get("intent_type", ""),
        "page_type_classification": opp.get("page_type_classification", {}),
        "working_title": opp.get("title") or opp.get("topic", ""),
        "title": seo.get("page_title", "") or opp.get("title") or opp.get("topic", ""),
        "target_keyword": seo.get("focus_keyphrase", "") or opp.get("topic_label") or opp.get("topic", ""),
        "focus_keyphrase": seo.get("focus_keyphrase", "") or opp.get("topic_label") or opp.get("topic", ""),
        "search_intent": opp.get("intent_type", "") or opp.get("opportunity_type", ""),
    }


def extract_blueprint_sections(blueprint_package: dict) -> list:
    blueprint = blueprint_package.get("blueprint") or {}
    sections = blueprint.get("sections", [])

    section_records = []

    for section in sections:
        section_records.append({
            "id": section.get("id", ""),
            "type": section.get("type", ""),
            "required": section.get("required", False),
            "purpose": section.get("purpose", "")
        })

    return section_records


def build_faq_strategy(content_type: str, language_profile: dict) -> dict:
    faq_templates = language_profile.get("faq_templates", {}) or {}
    template_type = get_template_type(content_type)

    if template_type == "service":
        minimum_questions = faq_templates.get("minimum_questions", 6)
        maximum_questions = faq_templates.get("maximum_questions", 8)
    else:
        minimum_questions = faq_templates.get("minimum_questions", 4)
        maximum_questions = faq_templates.get("maximum_questions", 6)

    return {
        "required": faq_templates.get("required", True),
        "minimum_questions": minimum_questions,
        "maximum_questions": maximum_questions,
        "question_style": "real_search_queries",
        "priority": "high",
        "guidance": [
            "FAQ questions should match real client search intent.",
            "FAQ content should support the focus keyphrase and related long-tail queries.",
            "FAQ answers should be concise, useful, and professionally cautious.",
            "FAQ content should be topic-specific, not generic polygraph filler."
        ]
    }


def build_conversion_strategy(content_type: str) -> dict:
    template_type = get_template_type(content_type)

    if template_type == "service":
        return {
            "primary_goal": "lead_generation",
            "cta_style": "soft_consultation",
            "trust_block_required": True,
            "local_relevance_required": True,
            "internal_links_required": True,
            "guidance": [
                "Use visitor-facing contact headings only.",
                "Do not use internal marketing terms such as CTA or call-to-action in visible page text.",
                "Invite the visitor to request confidential guidance or discuss whether the service is appropriate.",
                "Avoid pressure, guarantees, or exaggerated claims."
            ]
        }

    return {
        "primary_goal": "informational_support",
        "cta_style": "soft_next_step",
        "trust_block_required": True,
        "local_relevance_required": True,
        "internal_links_required": True,
        "guidance": [
            "Provide a natural next step for readers.",
            "Avoid aggressive sales wording.",
            "Keep the content useful and trust-oriented."
        ]
    }


def infer_topic_intelligence(topic: str, concept: str = "") -> dict:
    text = f"{topic} {concept}".lower()

    topic_tags = []
    client_pain_points = []
    investigation_scenarios = []
    topic_specific_examples = []
    questions_the_page_should_answer = []

    def add(items, values):
        items.extend(values)

    # Warehouse / inventory / stock loss
    if any(word in text for word in [
        "warehouse", "armaz", "stock", "inventory", "invent", "mercador", "goods"
    ]):
        add(topic_tags, [
            "warehouse",
            "inventory",
            "stock_loss",
            "goods_disappearance",
            "access_control",
            "internal_investigation",
            "employee_theft",
        ])
        add(client_pain_points, [
            "repeated stock losses",
            "missing goods or merchandise",
            "differences between physical inventory and internal records",
            "suspected inventory manipulation",
            "unclear responsibility among staff with warehouse access",
            "difficulty distinguishing administrative error, poor controls, and possible internal theft",
        ])
        add(investigation_scenarios, [
            "warehouse theft investigation",
            "inventory manipulation investigation",
            "irregularities in goods entry and exit records",
            "internal audit revealing unexplained stock discrepancies",
            "suspected unauthorized access to warehouse areas",
            "suspected involvement of employees, supervisors, drivers, or logistics staff",
        ])
        add(topic_specific_examples, [
            "a company finds repeated differences between recorded inventory and physical stock",
            "valuable goods disappear without a clear operational explanation",
            "an internal audit identifies discrepancies in high-value products",
            "warehouse access records do not clearly explain who handled missing goods",
            "management needs to avoid accusing innocent employees while investigating a specific incident",
        ])
        add(questions_the_page_should_answer, [
            "When can a polygraph support a warehouse theft investigation?",
            "Can a polygraph help clarify responsibility for missing stock?",
            "Should the polygraph replace inventory audits or documentary evidence?",
        ])

    # Fuel diversion / transport / fleet
    if any(word in text for word in [
        "fuel", "combust", "diesel", "fleet", "transport", "truck", "motorista", "vehicle"
    ]):
        add(topic_tags, [
            "fuel_diversion",
            "fleet_fraud",
            "transport_company",
            "driver_misconduct",
            "fuel_theft",
            "internal_investigation",
            "loss_prevention",
        ])
        add(client_pain_points, [
            "unexplained fuel consumption differences",
            "suspected siphoning or resale of fuel",
            "fuel expenses that do not match routes or operational records",
            "drivers or logistics staff suspected of unauthorized fuel use",
            "difficulty distinguishing mechanical consumption, poor records, and possible theft",
        ])
        add(investigation_scenarios, [
            "transport company investigating fuel losses",
            "fleet records showing fuel use inconsistent with routes",
            "suspected collusion between drivers and fuel station staff",
            "internal audit identifying irregular fuel expenses",
            "company needing to clarify responsibility before taking disciplinary action",
        ])
        add(topic_specific_examples, [
            "fuel card records show repeated abnormal consumption on specific routes",
            "a company detects fuel purchases that do not match vehicle mileage",
            "drivers deny involvement despite unexplained diesel losses",
            "management needs to determine whether losses are caused by theft, misuse, or weak controls",
        ])
        add(questions_the_page_should_answer, [
            "When can a polygraph support an investigation into fuel diversion?",
            "Can a polygraph help clarify whether a driver participated in unauthorized fuel use?",
            "How should polygraph results be combined with fuel records, GPS data, and audits?",
        ])

    # Procurement / purchasing / supplier fraud
    if any(word in text for word in [
        "procurement", "compras", "purchasing", "supplier", "fornecedor",
        "contract", "contrato", "invoice", "fatura", "factura", "aquisição", "aquisicao"
    ]):
        add(topic_tags, [
            "procurement_fraud",
            "supplier_fraud",
            "contract_manipulation",
            "invoice_fraud",
            "overpricing",
            "kickbacks",
            "conflict_of_interest",
            "internal_investigation",
            "corporate_fraud",
        ])
        add(client_pain_points, [
            "suspected overpricing or inflated supplier costs",
            "unexplained preference for one supplier",
            "possible kickbacks or improper benefits",
            "contracts awarded without transparent justification",
            "irregular approval of invoices or purchase orders",
            "difficulty proving whether misconduct was intentional or caused by weak controls",
        ])
        add(investigation_scenarios, [
            "procurement department suspected of favoring a supplier",
            "internal audit identifying repeated overpricing",
            "payments approved despite incomplete or irregular documentation",
            "employee suspected of receiving benefits from external suppliers",
            "supplier selection process showing signs of manipulation",
            "company investigating whether purchasing decisions were influenced by personal gain",
        ])
        add(topic_specific_examples, [
            "a supplier repeatedly wins contracts despite higher prices",
            "purchase orders are approved without clear business justification",
            "an internal audit identifies invoices that appear inflated or duplicated",
            "management suspects that an employee received benefits to favor a vendor",
            "procurement records do not clearly explain why a specific supplier was chosen",
        ])
        add(questions_the_page_should_answer, [
            "When can a polygraph support a procurement fraud investigation?",
            "Can a polygraph help clarify whether an employee received improper benefits from a supplier?",
            "Should a polygraph replace audits, supplier records, invoice analysis, or legal procedures?",
        ])

    # General theft / internal loss
    if any(word in text for word in [
        "theft", "furto", "roubo", "desvio", "steal", "stolen", "loss", "perda"
    ]):
        add(topic_tags, [
            "theft",
            "internal_theft",
            "employee_theft",
            "corporate_investigation",
            "loss_prevention",
        ])
        add(client_pain_points, [
            "internal suspicion without direct evidence",
            "risk of accusing innocent employees",
            "need to support an internal investigation with an additional professional tool",
            "pressure to act quickly without making unsupported accusations",
        ])
        add(investigation_scenarios, [
            "employee theft investigation",
            "internal loss investigation",
            "corporate fraud or misconduct investigation",
            "investigation involving several possible suspects",
        ])
        add(questions_the_page_should_answer, [
            "When is a polygraph appropriate in an internal theft investigation?",
            "How can a company use the test responsibly without replacing other evidence?",
            "What are the professional limits of the examination?",
        ])

    return {
        "topic_tags": sorted(set(topic_tags)),
        "client_pain_points": list(dict.fromkeys(client_pain_points)),
        "investigation_scenarios": list(dict.fromkeys(investigation_scenarios)),
        "topic_specific_examples": list(dict.fromkeys(topic_specific_examples)),
        "questions_the_page_should_answer": list(dict.fromkeys(questions_the_page_should_answer)),
    }



def build_professional_situation(topic_intelligence: dict) -> dict:
    pain_points = topic_intelligence.get("client_pain_points") or []
    scenarios = topic_intelligence.get("investigation_scenarios") or []
    examples = topic_intelligence.get("topic_specific_examples") or []
    questions = topic_intelligence.get("questions_the_page_should_answer") or []

    return {
        "typical_client_problem": pain_points[0] if pain_points else "",
        "typical_investigation_trigger": scenarios[0] if scenarios else "",
        "operational_context": examples[0] if examples else "",
        "why_evidence_may_be_insufficient": (
            "Available records, interviews, audits or internal controls may show irregularities "
            "without fully clarifying knowledge, authorization, participation or intent."
        ),
        "decision_pressure": (
            "The client may need to decide whether additional professional evaluation is appropriate "
            "before taking disciplinary, operational or legal steps."
        ),
        "professional_objective": (
            "Explain how a polygraph examination may contribute complementary information within "
            "a broader, responsible investigation."
        ),
        "page_should_answer": questions[:5],
        "editorial_perspective": (
            "Write from the perspective of a cautious investigative professional helping the visitor "
            "understand the situation, limits, evidence context and next steps."
        ),
    }



def build_content_focus_strategy(opp: dict, blueprint_package: dict, workspace: dict | None = None) -> dict:
    seo = opp.get("seo_brief", {}) or {}
    topic = opp.get("topic", "")
    focus_keyphrase = seo.get("focus_keyphrase", "") or topic
    topic_intelligence = infer_topic_intelligence(topic, opp.get("cluster_concept", ""))
    professional_situation = build_professional_situation(topic_intelligence)

    if workspace:
        opportunity_intelligence = analyze_opportunity(opp, workspace)
        professional_model = (
            opportunity_intelligence.get("professional_opportunity_model") or {}
        )

        if professional_model:
            professional_situation = {
                **professional_situation,
                "typical_client_problem": professional_model.get(
                    "client_problem",
                    professional_situation.get("typical_client_problem", ""),
                ),
                "typical_investigation_trigger": professional_model.get(
                    "investigation_trigger",
                    professional_situation.get("typical_investigation_trigger", ""),
                ),
                "why_evidence_may_be_insufficient": professional_model.get(
                    "missing_information",
                    professional_situation.get("why_evidence_may_be_insufficient", ""),
                ),
                "professional_objective": professional_model.get(
                    "professional_objective",
                    professional_situation.get("professional_objective", ""),
                ),
                "decision_pressure": professional_model.get(
                    "decision_pressure",
                    professional_situation.get("decision_pressure", ""),
                ),
                "editorial_perspective": professional_model.get(
                    "editorial_angle",
                    professional_situation.get("editorial_perspective", ""),
                ),
                "page_should_answer": professional_model.get(
                    "visitor_questions",
                    professional_situation.get("page_should_answer", []),
                ),
                "authority_position": professional_model.get("authority_position", ""),
                "content_angle_terms": professional_model.get("content_angle_terms", []),
                "opportunity_model_source": professional_model.get("source", ""),
            }

    return {
        "focus_keyphrase": focus_keyphrase,
        "topic": topic,
        "topic_intelligence": topic_intelligence,
        "professional_situation": professional_situation,
        "blueprint_id": blueprint_package.get("blueprint_id", "")
    }


def build_strategy_brief(opp: dict, language_profile: dict, workspace_id: str = '') -> dict:
    content_type = opp.get("recommended_content_type", "landing_page")
    concept = opp.get("cluster_concept", "")
    geo_relevance = opp.get("geo_relevance", "neutral")
    language_mismatch = opp.get("language_mismatch", False)

    templates = language_profile.get("content_strategy_templates", {}) or {}
    template_type = get_template_type(content_type)
    base_template = templates.get(template_type, {}) or {}

    warnings = []

    if geo_relevance == "low":
        warnings.append("This topic may refer to a foreign location and should be reviewed before drafting.")

    if language_mismatch:
        warnings.append("The detected language may not match the workspace language.")

    concept_warnings = templates.get("warnings_by_concept", {}).get(concept, [])
    warnings.extend(concept_warnings)

    recommended_angle = templates.get("recommended_angles_by_concept", {}).get(
        concept,
        base_template.get("recommended_angle", "")
    )

    blueprint_source = build_blueprint_source(opp)
    blueprint_package = build_page_blueprint_package(blueprint_source)
    blueprint_sections = extract_blueprint_sections(blueprint_package)

    faq_strategy = build_faq_strategy(content_type, language_profile)
    conversion_strategy = build_conversion_strategy(content_type)
    workspace_context = {
        "workspace_id": workspace_id or opp.get("workspace_id", ""),
        "country": (
            (language_profile.get("region") or {}).get("country_name", "")
            or language_profile.get("country_localized", "")
        ),
    }

    content_focus = build_content_focus_strategy(
        opp,
        blueprint_package,
        workspace_context,
    )

    return {
        "generated_at": now_iso(),
        "strategy_version": "2.0",
        "source_topic": opp.get("topic", ""),
        "content_goal": base_template.get("content_goal", ""),
        "target_audience": base_template.get("target_audience", ""),
        "recommended_angle": recommended_angle,
        "conversion_goal": base_template.get("conversion_goal", ""),
        "warnings": warnings,
        "internal_linking_notes": templates.get("internal_linking_notes", []),

        "page_blueprint": {
            "blueprint_id": blueprint_package.get("blueprint_id", ""),
            "page_type": opp.get("page_type", ""),
            "intent_type": opp.get("intent_type", ""),
            "classification": opp.get("page_type_classification", {}),
            "sections": blueprint_sections,
            "prompt_text": blueprint_package.get("prompt_text", "")
        },

        "content_focus": content_focus,
        "faq_strategy": faq_strategy,
        "conversion_strategy": conversion_strategy,

        "quality_controls": {
            "requires_examiner_review_before_publication": True,
            "avoid_legal_guarantees": True,
            "avoid_absolute_accuracy_claims": True,
            "avoid_unverified_local_law_claims": True,
            "avoid_generic_polygraph_filler": True,
            "prefer_topic_specific_faqs": True
        },

        "required_sections": [
            section.get("id")
            for section in blueprint_sections
            if section.get("required") is True
        ]
    }


def main():
    print("=== Sofia: Generate Content Strategy Brief ===\n")

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python app/generate_content_strategy_brief.py WORKSPACE_ID")
        print("  python app/generate_content_strategy_brief.py WORKSPACE_ID --force")
        print("Example:")
        print("  python app/generate_content_strategy_brief.py local.ao")
        return

    workspace_id = sys.argv[1]
    force = "--force" in sys.argv

    workspaces_data = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces_data, workspace_id)

    if not workspace:
        print(f"Workspace not found: {workspace_id}")
        sys.exit(1)

    workspace_folder = get_workspace_folder(workspace)
    opportunities_file = workspace_folder / "external_opportunities.json"

    if not opportunities_file.exists():
        print(f"Missing external opportunities file: {opportunities_file}")
        return

    opportunities_data = load_json(opportunities_file)
    language_profile = load_language_profile(workspace_folder)

    opportunities = opportunities_data.get("opportunities", [])
    updated = 0

    for opp in opportunities:
        if opp.get("status") not in [
            "validated",
            "approved",
            "converted_to_intake"
        ]:
            continue

        if opp.get("content_strategy_brief") and not force:
            continue

        opp["content_strategy_brief"] = build_strategy_brief(opp, language_profile, workspace_id)
        opp["updated_at"] = now_iso()
        updated += 1

        strategy = opp["content_strategy_brief"]
        blueprint_id = strategy.get("page_blueprint", {}).get("blueprint_id", "")

        print(f"{opp.get('id')}: {opp.get('topic')}")
        print(f"  Content type: {opp.get('recommended_content_type')}")
        print(f"  Blueprint: {blueprint_id}")
        print("  Strategy brief created\n")

    opportunities_data["opportunities"] = opportunities
    save_json(opportunities_file, opportunities_data)

    print(f"Content strategy briefs created/updated: {updated}")


if __name__ == "__main__":
    main()