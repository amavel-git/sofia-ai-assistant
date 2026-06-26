import json
from pathlib import Path
from datetime import datetime, timezone


SOFIA_ROOT = Path(__file__).resolve().parents[1]

WORKSPACE_ID = "local.ao"
LOCAL_SITE_PATH = SOFIA_ROOT / "sites" / "local_sites" / "ao"

SIGNALS_FILE = LOCAL_SITE_PATH / "external_signals.json"
OPPORTUNITIES_FILE = LOCAL_SITE_PATH / "external_opportunities.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_next_opportunity_id(opportunities: list, country_code: str) -> str:
    max_num = 0
    prefix = f"OPP-{country_code}-"

    for opp in opportunities:
        opp_id = opp.get("id", "")
        if opp_id.startswith(prefix):
            try:
                num = int(opp_id.replace(prefix, ""))
                max_num = max(max_num, num)
            except ValueError:
                continue

    return f"{prefix}{max_num + 1:03d}"


def opportunity_exists(opportunities: list, topic: str) -> bool:
    topic_norm = topic.strip().lower()

    for opp in opportunities:
        if opp.get("topic", "").strip().lower() == topic_norm:
            return True

    return False


def map_priority(priority_hint: str) -> str:
    if priority_hint == "high":
        return "high"
    if priority_hint == "medium":
        return "medium"
    return "low"


def infer_signal_topic_profile(signal: dict) -> dict:
    raw_signal = str(signal.get("raw_signal", "")).strip()
    text = raw_signal.lower()

    topic_tags = []

    if any(term in text for term in [
        "warehouse", "logistic", "logistics", "goods", "merchandise",
        "stock", "inventory", "supply chain",
        "armaz", "logíst", "logistic", "mercador", "invent",
        "almacén", "mercanc", "inventario",
        "entrepôt", "marchandise", "inventaire"
    ]):
        topic_tags.extend([
            "warehouse",
            "logistics",
            "missing_goods",
            "inventory_loss",
            "internal_investigation"
        ])

    if any(term in text for term in [
        "fuel", "diesel", "fleet", "driver", "transport",
        "combust", "gasóleo", "gasoleo", "motorista",
        "combustible", "conductor",
        "carburant", "chauffeur"
    ]):
        topic_tags.extend([
            "fuel_diversion",
            "fleet_fraud",
            "transport_company",
            "driver_misconduct"
        ])

    if any(term in text for term in [
        "procurement", "purchasing", "supplier", "contract", "invoice",
        "compras", "fornecedor", "contrato", "fatura", "factura",
        "proveedor", "factura",
        "fournisseur", "contrat", "facture"
    ]):
        topic_tags.extend([
            "procurement_fraud",
            "supplier_fraud",
            "contract_manipulation",
            "invoice_fraud"
        ])

    if any(term in text for term in [
        "payment", "financial fraud", "funds", "expense",
        "pagamento", "fraude financeira", "desvio de fundos", "despesa",
        "pago", "fraude financiera", "fondos",
        "paiement", "fraude financière", "fonds"
    ]):
        topic_tags.extend([
            "financial_fraud",
            "improper_payments",
            "expense_fraud",
            "internal_controls"
        ])

    if any(term in text for term in [
        "theft", "stolen", "missing", "loss", "diversion",
        "furto", "roubo", "desaparecimento", "perda", "desvio",
        "robo", "hurto", "desaparición", "pérdida",
        "vol", "disparition", "perte", "détournement"
    ]):
        topic_tags.extend([
            "internal_theft",
            "loss_investigation",
            "employee_misconduct"
        ])

    return {
        "raw_signal": raw_signal,
        "topic_tags": sorted(set(topic_tags)),
    }


def build_normalized_topic_key(profile: dict) -> str:
    tags = set(profile.get("topic_tags", []))

    if {"warehouse", "logistics", "missing_goods"}.issubset(tags):
        return "polygraph testing for missing goods in logistics centers"

    if "fuel_diversion" in tags:
        return "polygraph testing for fuel diversion investigations"

    if "procurement_fraud" in tags:
        return "polygraph testing for procurement fraud investigations"

    if "financial_fraud" in tags or "improper_payments" in tags:
        return "polygraph testing for improper payments and financial fraud investigations"

    if "internal_theft" in tags:
        return "polygraph testing for internal theft investigations"

    return profile.get("raw_signal", "")


def build_opportunity(signal: dict, opp_id: str) -> dict:
    profile = infer_signal_topic_profile(signal)
    topic_seed = build_normalized_topic_key(profile)
    raw_signal = signal.get("raw_signal", "")

    topic = raw_signal or topic_seed
    priority_hint = signal.get("priority_hint", "low")

    return {
        "id": opp_id,
        "created_at": now(),
        "updated_at": now(),
        "country": signal.get("country"),
        "language": signal.get("language"),
        "source": signal.get("source"),
        "source_signal_id": signal.get("id"),
        "topic": topic,
        "topic_profile": profile,
        "topic_seed": topic_seed,
        "opportunity_type": "blog_topic",
        "recommended_content_type": "blog_post",
        "intent_type": "informational",
        "priority": map_priority(priority_hint),
        "confidence": 0.7,
        "status": "new",
        "related_keywords": list(dict.fromkeys([topic, raw_signal, topic_seed])),
        "detected_concepts": signal.get("detected_concepts", []),
        "business_reason": f"Detected from external signal: {raw_signal}",
        "risk_notes": [],
        "recommended_action": "send_to_examiner_for_validation",
        "cannibalization_status": "unchecked",
        "local_topic_status": "unchecked",
        "raw_signal": raw_signal,
        "normalized_topic": topic_seed,
        "review_status": "pending_examiner"
    }


def main():
    print("=== Sofia: Convert Signals to Opportunities ===\n")

    signals_data = load_json(SIGNALS_FILE)
    opportunities_data = load_json(OPPORTUNITIES_FILE)

    signals = signals_data.get("signals", [])
    opportunities = opportunities_data.get("opportunities", [])

    created = 0
    country_code = WORKSPACE_ID.split(".")[-1].upper()

    for signal in signals:
        if signal.get("status") != "processed":
            continue

        if signal.get("classification") != "relevant":
            continue

        profile = infer_signal_topic_profile(signal)
        topic_seed = build_normalized_topic_key(profile)
        raw_signal = signal.get("raw_signal", "")
        topic = raw_signal or topic_seed

        if opportunity_exists(opportunities, topic):
            continue

        opp_id = get_next_opportunity_id(opportunities, country_code)

        new_opp = build_opportunity(signal, opp_id)
        opportunities.append(new_opp)

        signal["converted_to_opportunity"] = True
        signal["opportunity_id"] = opp_id

        created += 1

        print(f"Created {opp_id} from signal: {topic}")

    opportunities_data["opportunities"] = opportunities
    signals_data["signals"] = signals

    save_json(OPPORTUNITIES_FILE, opportunities_data)
    save_json(SIGNALS_FILE, signals_data)

    print(f"\nTotal opportunities created: {created}")


if __name__ == "__main__":
    main()