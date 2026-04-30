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


def get_primary_concept(opportunity):
    concepts = opportunity.get("detected_concepts", [])
    if not concepts:
        return None
    return concepts[0]


def main():
    print("=== Sofia: Cluster Opportunities V2 (Concept-Based) ===\n")

    data = load_json(OPPORTUNITIES_FILE)
    opportunities = data.get("opportunities", [])

    clusters = {}
    clustered_ids = set()

    # Step 1: Build clusters
    for opp in opportunities:
        if opp.get("status") != "validated":
            continue

        concept = get_primary_concept(opp)

        if not concept:
            continue  # skip if no concept

        if concept not in clusters:
            clusters[concept] = []

        clusters[concept].append(opp)

    new_opportunities = []

    # Step 2: Process clusters
    for concept, group in clusters.items():
        if len(group) == 1:
            new_opportunities.append(group[0])
            continue

        print(f"Cluster detected (concept): {concept} ({len(group)} items)")

        primary = group[0]

        combined_keywords = []
        for g in group:
            combined_keywords.append(g.get("topic", ""))

        primary["related_keywords"] = list(set(combined_keywords))
        primary["clustered"] = True
        primary["cluster_size"] = len(group)
        primary["cluster_concept"] = concept

        new_opportunities.append(primary)

        for g in group[1:]:
            g["status"] = "clustered"
            clustered_ids.add(g["id"])

    # Step 3: Keep non-clustered opportunities
    remaining = [
        o for o in opportunities
        if o.get("id") not in clustered_ids and o.get("status") != "validated"
    ]

    data["opportunities"] = new_opportunities + remaining

    save_json(OPPORTUNITIES_FILE, data)

    print("\nClustering V2 completed.")


if __name__ == "__main__":
    main()