import json
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]

WORKSPACE_ID = "local.ao"
LOCAL_SITE_PATH = SOFIA_ROOT / "sites" / "local_sites" / "ao"

OPPORTUNITIES_FILE = LOCAL_SITE_PATH / "external_opportunities.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def normalize(text):
    return text.lower().replace("polígrafo", "poligrafo")


def get_cluster_key(topic):
    t = normalize(topic)

    if "funciona" in t:
        return "polygraph_works"

    if "preço" in t or "valor" in t:
        return "polygraph_price"

    if "empresa" in t:
        return "polygraph_business"

    if "infidelidade" in t or "casal" in t:
        return "polygraph_relationship"

    return "other"


def main():
    print("=== Sofia: Cluster Opportunities ===\n")

    data = load_json(OPPORTUNITIES_FILE)
    opportunities = data.get("opportunities", [])

    clusters = {}
    clustered_ids = set()

    for opp in opportunities:
        if opp.get("status") != "validated":
            continue

        topic = opp.get("topic", "")
        key = get_cluster_key(topic)

        if key == "other":
            continue

        if key not in clusters:
            clusters[key] = []

        clusters[key].append(opp)

    new_opportunities = []

    for key, group in clusters.items():
        if len(group) == 1:
            new_opportunities.append(group[0])
            continue

        print(f"Cluster detected: {key} ({len(group)} items)")

        primary = group[0]

        combined_keywords = []
        for g in group:
            combined_keywords.append(g.get("topic", ""))

        primary["related_keywords"] = list(set(combined_keywords))
        primary["clustered"] = True
        primary["cluster_size"] = len(group)

        new_opportunities.append(primary)

        for g in group[1:]:
            g["status"] = "clustered"
            clustered_ids.add(g["id"])

    data["opportunities"] = new_opportunities + [
        o for o in opportunities if o.get("id") in clustered_ids
    ]

    save_json(OPPORTUNITIES_FILE, data)

    print("\nClustering completed.")


if __name__ == "__main__":
    main()