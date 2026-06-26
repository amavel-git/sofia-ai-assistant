import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = ROOT / "data" / "workspaces.json"

PRIORITY_ORDER = {
    "high": 1,
    "medium_high": 2,
    "medium": 3,
    "low": 4
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_workspace(workspaces, workspace_id):
    for workspace in workspaces.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def get_workspace_folder(workspace):
    return ROOT / workspace["folder_path"]


def load_candidates(path):
    if not path.exists():
        return []

    data = load_json(path)

    if isinstance(data, list):
        return data

    return data.get("candidates", [])


def load_queue(path, workspace_id):
    if path.exists():
        data = load_json(path)
    else:
        data = {}

    data.setdefault("version", "1.0")
    data.setdefault("workspace_id", workspace_id)
    data.setdefault("created_at", now_iso())
    data.setdefault("updated_at", None)
    data.setdefault("queue_status", "not_started")
    data.setdefault("summary", {})
    data.setdefault("items", [])

    return data


def candidate_sort_key(candidate):
    priority = candidate.get("priority", "medium")
    competitor_count = candidate.get("competitor_coverage_count", 0)
    competitor_pages = candidate.get("competitor_total_pages", 0)

    return (
        PRIORITY_ORDER.get(priority, 99),
        -competitor_count,
        -competitor_pages,
        candidate.get("candidate_id", "")
    )


def queue_item_from_candidate(candidate, position):
    return {
        "queue_id": f"QUEUE-{position:04d}",
        "candidate_id": candidate.get("candidate_id"),
        "workspace_id": candidate.get("workspace_id"),
        "topic": candidate.get("topic"),
        "topic_label": candidate.get("topic_label"),
        "title": candidate.get("title"),
        "content_type": candidate.get("content_type"),

        "page_type": candidate.get("page_type"),
        "blueprint_id": candidate.get("blueprint_id"),
        "intent_type": candidate.get("intent_type"),
        "page_type_classification": candidate.get(
            "page_type_classification",
            {}
        ),

        "priority": candidate.get("priority"),
        "recommended_action": candidate.get("recommended_action"),
        "status": "pending",
        "queue_position": position,
        "created_at": now_iso(),
        "queued_at": None,
        "completed_at": None,
        "source": "market_intelligence_candidates",
        "rationale": candidate.get("rationale"),
        "competitor_coverage_count": candidate.get("competitor_coverage_count", 0),
        "competitor_total_pages": candidate.get("competitor_total_pages", 0),
        "competitors_covering": candidate.get("competitors_covering", []),
        "human_review_required": True
    }


def rebuild_queue_from_candidates(queue, candidates):
    existing_by_candidate = {
        item.get("candidate_id"): item
        for item in queue.get("items", [])
        if item.get("candidate_id")
    }

    sortable = [
        c for c in candidates
        if c.get("status") == "candidate_for_review"
    ]

    sortable.sort(key=candidate_sort_key)

    items = []

    for idx, candidate in enumerate(sortable, start=1):
        candidate_id = candidate.get("candidate_id")
        existing = existing_by_candidate.get(candidate_id)

        if existing:
            item = existing
            item["queue_position"] = idx
            item["queue_id"] = f"QUEUE-{idx:04d}"
            item["title"] = candidate.get("title")
            item["topic_label"] = candidate.get("topic_label")

            item["page_type"] = candidate.get("page_type")
            item["blueprint_id"] = candidate.get("blueprint_id")
            item["intent_type"] = candidate.get("intent_type")
            item["page_type_classification"] = candidate.get(
                "page_type_classification",
                {}
            )

            item["priority"] = candidate.get("priority")
            item["recommended_action"] = candidate.get("recommended_action")
            item["competitor_coverage_count"] = candidate.get("competitor_coverage_count", 0)
            item["competitor_total_pages"] = candidate.get("competitor_total_pages", 0)
            item["competitors_covering"] = candidate.get("competitors_covering", [])
        else:
            item = queue_item_from_candidate(candidate, idx)

        items.append(item)

    queue["items"] = items
    queue["updated_at"] = now_iso()

    if queue.get("queue_status") == "not_started" and items:
        queue["queue_status"] = "ready"

    update_summary(queue)

    return queue


def update_summary(queue):
    items = queue.get("items", [])

    summary = {
        "total_candidates": len(items),
        "pending": 0,
        "queued": 0,
        "approved": 0,
        "rejected": 0,
        "completed": 0
    }

    for item in items:
        status = item.get("status", "pending")
        if status not in summary:
            summary[status] = 0
        summary[status] += 1

    queue["summary"] = summary


def load_content_opportunities(path):
    if not path.exists():
        return []

    data = load_json(path)

    if isinstance(data, list):
        return data

    return data.get("opportunities", [])


def save_content_opportunities(path, opportunities):
    save_json(path, opportunities)


def load_external_opportunities(path):
    if path.exists():
        data = load_json(path)
    else:
        data = {}

    if isinstance(data, list):
        return {
            "version": "1.0",
            "opportunities": data
        }

    data.setdefault("version", "1.0")
    data.setdefault("opportunities", [])

    return data


def sync_external_opportunity(external_data, opportunity):
    opportunities = external_data.setdefault("opportunities", [])

    opportunity_id = opportunity.get("opportunity_id") or opportunity.get("id")
    if not opportunity_id:
        return False

    for item in opportunities:
        existing_id = item.get("opportunity_id") or item.get("id")
        if existing_id == opportunity_id:
            item.update(opportunity)
            item["id"] = opportunity_id
            item["opportunity_id"] = opportunity_id
            return False

    new_item = dict(opportunity)
    new_item["id"] = opportunity_id
    new_item["opportunity_id"] = opportunity_id
    opportunities.append(new_item)
    return True


def opportunity_exists(opportunities, candidate_id):
    for item in opportunities:
        if item.get("source_candidate_id") == candidate_id:
            return True
    return False


def make_opportunity_id(opportunities, workspace_id):
    prefix = f"OPP-{workspace_id.split('.')[-1].upper()}"
    numbers = []

    for item in opportunities:
        oid = item.get("opportunity_id") or item.get("id") or ""
        if oid.startswith(prefix):
            try:
                numbers.append(int(oid.split("-")[-1]))
            except Exception:
                pass

    next_number = max(numbers) + 1 if numbers else 1
    return f"{prefix}-{next_number:04d}"


def promote_next(queue, opportunities, workspace_id):
    active = [
        item for item in queue.get("items", [])
        if item.get("status") == "queued_for_review"
    ]

    if active:
        return None, "active_item_already_queued", None

    pending_items = [
        item for item in queue.get("items", [])
        if item.get("status") == "pending"
    ]

    pending_items.sort(key=lambda x: x.get("queue_position", 999999))

    if not pending_items:
        return None, "no_pending_items", None

    item = pending_items[0]
    candidate_id = item.get("candidate_id")

    if opportunity_exists(opportunities, candidate_id):
        item["status"] = "queued_for_review"
        item["queued_at"] = item.get("queued_at") or now_iso()

        existing_opportunity = None

        for opp in opportunities:
            if opp.get("source_candidate_id") == candidate_id:
                existing_opportunity = opp

                # restore notifier-ready state
                opp["status"] = "validated"
                opp["review_status"] = "pending_examiner"
                opp["telegram_notified"] = False
                opp["telegram_notified_at"] = None
                break

        update_summary(queue)

        return (
            item,
            "already_exists_in_opportunities",
            existing_opportunity
        )

    opportunity_id = make_opportunity_id(opportunities, workspace_id)

    opportunity = {
        "opportunity_id": opportunity_id,
        "workspace_id": workspace_id,
        "source": "market_intelligence",
        "source_candidate_id": candidate_id,
        "status": "pending_review",
        "created_at": now_iso(),
        "title": item.get("title"),
        "topic": item.get("topic"),
        "topic_label": item.get("topic_label"),
        "content_type": item.get("content_type"),

        "page_type": item.get("page_type"),
        "blueprint_id": item.get("blueprint_id"),
        "intent_type": item.get("intent_type"),
        "page_type_classification": item.get(
            "page_type_classification",
            {}
        ),

        "priority": item.get("priority"),
        "recommended_action": item.get("recommended_action"),
        "rationale": item.get("rationale"),
        "competitor_coverage_count": item.get("competitor_coverage_count", 0),
        "competitor_total_pages": item.get("competitor_total_pages", 0),
        "competitors_covering": item.get("competitors_covering", []),
        "human_review_required": True,
        "review_actions": [
            "approve",
            "modify",
            "reject"
        ]
    }

    opportunities.append(opportunity)

    item["status"] = "queued_for_review"
    item["queued_at"] = now_iso()
    item["opportunity_id"] = opportunity_id

    update_summary(queue)

    return item, "promoted", opportunity


def print_summary(queue):
    print("\n=== Market Opportunity Queue ===")
    print(f"Workspace: {queue.get('workspace_id')}")
    print(f"Status: {queue.get('queue_status')}")
    print(json.dumps(queue.get("summary", {}), indent=2, ensure_ascii=False))

    print("\nTop queue items:")
    for item in queue.get("items", [])[:10]:
        print(
            f"- {item.get('queue_id')} | "
            f"{item.get('candidate_id')} | "
            f"{item.get('priority')} | "
            f"{item.get('status')} | "
            f"{item.get('title')}"
        )



def notify_promoted_opportunity(workspace_id, opportunity_id):
    if not opportunity_id:
        return False

    result = subprocess.run(
        [
            sys.executable,
            "app/notify_examiner_review.py",
            workspace_id,
            "--send-opportunity",
            opportunity_id
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True
    )

    if result.stdout:
        print(result.stdout.strip())

    if result.stderr:
        print(result.stderr.strip())

    if result.returncode != 0:
        print("Telegram opportunity notification failed.")
        return False

    return True

def main():
    parser = argparse.ArgumentParser(description="Queue Sofia market candidates and promote one opportunity at a time.")
    parser.add_argument("workspace_id", help="Workspace ID, e.g. local.es")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--promote-next", action="store_true")
    args = parser.parse_args()

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, args.workspace_id)

    if not workspace:
        print(f"Workspace not found: {args.workspace_id}")
        raise SystemExit(1)

    folder = get_workspace_folder(workspace)

    candidates_path = folder / "market_intelligence_candidates.json"
    queue_path = folder / "market_opportunity_queue.json"
    opportunities_path = folder / "content_opportunities.json"
    external_opportunities_path = folder / "external_opportunities.json"

    candidates = load_candidates(candidates_path)
    queue = load_queue(queue_path, args.workspace_id)
    queue = rebuild_queue_from_candidates(queue, candidates)

    opportunities = load_content_opportunities(opportunities_path)
    external_opportunities = load_external_opportunities(external_opportunities_path)

    promoted_item = None
    promote_status = None
    promoted_opportunity = None

    if args.promote_next:
        promoted_item, promote_status, promoted_opportunity = promote_next(
            queue,
            opportunities,
            args.workspace_id
        )

        print(f"\nPromote next status: {promote_status}")

        if promoted_item:
            print(
                f"Queued: {promoted_item.get('candidate_id')} "
                f"→ {promoted_item.get('opportunity_id')} | "
                f"{promoted_item.get('title')}"
            )

    print_summary(queue)

    if args.dry_run:
        print("\nDry run only. No files updated.")
        return

    if promoted_opportunity:
        sync_external_opportunity(
            external_opportunities,
            promoted_opportunity
        )

    save_json(queue_path, queue)
    save_content_opportunities(opportunities_path, opportunities)
    save_json(external_opportunities_path, external_opportunities)

    if promoted_opportunity:
        print("\nSending Telegram opportunity notification...")
        notify_promoted_opportunity(
            args.workspace_id,
            promoted_opportunity.get("opportunity_id")
        )

    print("\nFiles updated:")
    print(f"- {queue_path}")
    print(f"- {opportunities_path}")
    print(f"- {external_opportunities_path}")


if __name__ == "__main__":
    main()