import argparse

from market_intelligence import (
    load_market_intelligence,
    save_market_intelligence,
    normalize_domain,
)


def remove_market_competitor(workspace_id, domain):
    data = load_market_intelligence(workspace_id)

    before = len(data.get("competitors", []))
    normalized_remove = normalize_domain(domain)

    data["competitors"] = [
        competitor for competitor in data.get("competitors", [])
        if normalize_domain(competitor.get("domain", "")) != normalized_remove
    ]

    after = len(data["competitors"])

    if before == after:
        print("Competitor not found.")
        print(f"Workspace: {workspace_id}")
        print(f"Domain: {domain}")
        return False

    path = save_market_intelligence(workspace_id, data)

    print("Competitor removed successfully.")
    print(f"Workspace: {workspace_id}")
    print(f"Domain: {domain}")
    print(f"Saved to: {path}")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Remove a competitor from a workspace market_intelligence.json file."
    )

    parser.add_argument("workspace_id", help="Workspace ID, e.g. local.ao")
    parser.add_argument("domain", help="Competitor domain or URL, e.g. https://example.com")

    args = parser.parse_args()

    remove_market_competitor(
        workspace_id=args.workspace_id,
        domain=args.domain
    )


if __name__ == "__main__":
    main()