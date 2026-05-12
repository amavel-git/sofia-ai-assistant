import argparse

from market_intelligence import (
    load_market_intelligence,
    save_market_intelligence,
    competitor_exists,
    utc_now_iso,
)


def build_competitor_record(domain, name=None, country="", language="", notes=""):
    return {
        "name": name or "Unknown competitor",
        "domain": domain.strip(),
        "country": country,
        "language": language,
        "notes": notes or "Manually added by examiner.",
        "observed_services": [],
        "observed_keywords": [],
        "strong_pages": [],
        "content_gaps": [],
        "risk_notes": [],
        "source": "manual_examiner",
        "confidence": "high",
        "status": "pending_review",
        "last_reviewed": None,
        "added_at": utc_now_iso()
    }


def add_market_competitor(workspace_id, domain, name=None, country="", language="", notes=""):
    data = load_market_intelligence(workspace_id)

    if competitor_exists(data, domain):
        print("Competitor already exists.")
        print(f"Workspace: {workspace_id}")
        print(f"Domain: {domain}")
        return False

    competitor = build_competitor_record(
        domain=domain,
        name=name,
        country=country,
        language=language,
        notes=notes
    )

    data.setdefault("competitors", []).append(competitor)
    path = save_market_intelligence(workspace_id, data)

    print("Competitor added successfully.")
    print(f"Workspace: {workspace_id}")
    print(f"Domain: {domain}")
    print(f"Saved to: {path}")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Add a manual competitor to a workspace market_intelligence.json file."
    )

    parser.add_argument("workspace_id", help="Workspace ID, e.g. local.ao")
    parser.add_argument("domain", help="Competitor domain or URL, e.g. https://example.com")
    parser.add_argument("--name", default=None, help="Competitor name")
    parser.add_argument("--country", default="", help="Competitor country")
    parser.add_argument("--language", default="", help="Primary competitor language")
    parser.add_argument("--notes", default="", help="Manual notes about this competitor")

    args = parser.parse_args()

    add_market_competitor(
        workspace_id=args.workspace_id,
        domain=args.domain,
        name=args.name,
        country=args.country,
        language=args.language,
        notes=args.notes
    )


if __name__ == "__main__":
    main()