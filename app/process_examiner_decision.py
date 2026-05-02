import json
import re
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timezone


SOFIA_ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = SOFIA_ROOT / "data" / "workspaces.json"
GLOBAL_DRAFT_REGISTRY = SOFIA_ROOT / "sites" / "draft_registry.json"


OPPORTUNITY_DECISIONS = ["APPROVE", "MODIFY", "REJECT"]
DRAFT_DECISIONS = ["APPROVE", "REVISE", "REJECT"]


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def today():
    return datetime.now().strftime("%Y-%m-%d")

def run_pipeline_command(args, label):
    print(f"\nAuto step: {label}")
    result = subprocess.run(
        args,
        cwd=str(SOFIA_ROOT),
        text=True,
        capture_output=True
    )

    if result.stdout:
        print(result.stdout.strip())

    if result.stderr:
        print(result.stderr.strip())

    if result.returncode != 0:
        print(f"Auto step failed: {label}")
        return False

    print(f"Auto step completed: {label}")
    return True


def find_workspace(workspaces, workspace_id):
    for workspace in workspaces.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def parse_reply(reply_text):
    reply_text = reply_text.strip()

    match = re.match(
        r"^(APPROVE|MODIFY|REVISE|REJECT)\s+([A-Z]+-[A-Z0-9-]+|DRAFT-\d+)(?::\s*(.*))?$",
        reply_text,
        re.IGNORECASE
    )

    if not match:
        return None

    decision = match.group(1).upper()
    item_id = match.group(2).upper()
    comment = match.group(3).strip() if match.group(3) else ""

    return {
        "decision": decision,
        "item_id": item_id,
        "comment": comment
    }


def find_opportunity(opportunities, opportunity_id):
    for opportunity in opportunities:
        opp_id = opportunity.get("id") or opportunity.get("opportunity_id")
        if opp_id == opportunity_id:
            return opportunity
    return None


def process_opportunity_decision(workspace, item_id, decision, comment):
    if decision not in OPPORTUNITY_DECISIONS:
        print(f"Invalid opportunity decision: {decision}")
        print(f"Valid opportunity decisions: {', '.join(OPPORTUNITY_DECISIONS)}")
        return False

    opportunities_path = SOFIA_ROOT / workspace["folder_path"] / "external_opportunities.json"

    if not opportunities_path.exists():
        print(f"external_opportunities.json not found: {opportunities_path}")
        return False

    data = load_json(opportunities_path)
    opportunities = data.get("opportunities", [])

    opportunity = find_opportunity(opportunities, item_id)

    if not opportunity:
        print(f"Opportunity not found: {item_id}")
        return False

    opportunity["telegram_notified"] = True

    timestamp = now_iso()

    if decision == "APPROVE":
        opportunity["status"] = "approved"
        opportunity["review_status"] = "approved_by_examiner"
        opportunity["approved_at"] = timestamp
        opportunity["ready_for_intake"] = True

    elif decision == "MODIFY":
        opportunity["status"] = "needs_modification"
        opportunity["review_status"] = "modification_requested"
        opportunity["modified_at"] = timestamp

    elif decision == "REJECT":
        opportunity["status"] = "rejected"
        opportunity["review_status"] = "rejected_by_examiner"
        opportunity["rejected_at"] = timestamp

    opportunity["examiner_decision"] = decision
    opportunity["examiner_comment"] = comment
    opportunity["examiner_decision_at"] = timestamp

    save_json(opportunities_path, data)

    if decision == "MODIFY":
        if comment:
            run_pipeline_command(
                [
                    "python3",
                    "app/apply_opportunity_modification.py",
                    workspace.get("workspace_id"),
                    item_id,
                    comment
                ],
                "Apply opportunity modification"
            )
        else:
            print("\nModification requested, but no comment was provided.")
            print("No automatic opportunity modification loop was triggered.")

    if decision == "APPROVE":
        workspace_id = workspace.get("workspace_id")

        run_pipeline_command(
            ["python3", "app/convert_opportunity_to_intake.py", workspace_id],
            "Convert approved opportunity to intake"
        )

        run_pipeline_command(
            ["python3", "app/process_next_intake.py"],
            "Process next intake"
        )

    print("Opportunity decision processed successfully.")
    print(f"Workspace: {workspace.get('workspace_id')}")
    print(f"Opportunity: {item_id}")
    print(f"Decision: {decision}")

    if decision == "APPROVE":
        print("\nOpportunity approved and automatic intake pipeline was triggered.")

    elif decision == "MODIFY":
        print("\nOpportunity marked for modification. Review comments and update opportunity.")

    elif decision == "REJECT":
        print("\nOpportunity rejected. No further action required.")
        if comment:
            print(f"Comment: {comment}")

    return True


def find_draft(drafts, draft_id):
    for draft in drafts:
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def find_review_item(review_items, draft_id):
    for item in review_items:
        if item.get("draft_id") == draft_id:
            return item
    return None

def get_validation_status(draft):
    validation = draft.get("validation", {})
    status = validation.get("status", "")
    issues = validation.get("issues", [])

    return status, issues


def format_validation_issues(issues):
    if not issues:
        return "No validation issues listed."

    return "\n".join([f"- {issue}" for issue in issues])

def reload_draft_from_registry(draft_id):
    if not GLOBAL_DRAFT_REGISTRY.exists():
        return None

    draft_data = load_json(GLOBAL_DRAFT_REGISTRY)
    drafts = draft_data.get("drafts", [])

    return find_draft(drafts, draft_id)


def process_draft_decision(workspace, item_id, decision, comment):
    if decision not in DRAFT_DECISIONS:
        print(f"Invalid draft decision: {decision}")
        print(f"Valid draft decisions: {', '.join(DRAFT_DECISIONS)}")
        return False

    if not GLOBAL_DRAFT_REGISTRY.exists():
        print(f"Draft registry not found: {GLOBAL_DRAFT_REGISTRY}")
        return False

    review_queue_path = SOFIA_ROOT / workspace["review_queue_path"]

    if not review_queue_path.exists():
        print(f"Review queue not found: {review_queue_path}")
        return False

    draft_data = load_json(GLOBAL_DRAFT_REGISTRY)
    drafts = draft_data.get("drafts", [])

    draft = find_draft(drafts, item_id)

    if not draft:
        print(f"Draft not found in global draft registry: {item_id}")
        return False

    review_queue = load_json(review_queue_path)
    review_items = review_queue.get("review_items", [])
    review_item = find_review_item(review_items, item_id)

    timestamp = now_iso()
    date_today = today()

    if decision == "APPROVE":
        draft["draft_status"] = "approved"
        draft["approved_at"] = date_today
        draft["approval"] = {
            "approved": True,
            "approved_at": date_today,
            "approved_by": "examiner",
            "notes": comment
        }
        draft["wordpress_status"] = "ready_for_preparation"

        if review_item:
            review_item["status"] = "approved"
            review_item["examiner_decision"] = "APPROVE"
            review_item["examiner_comment"] = comment
            review_item["decided_at"] = timestamp
            review_item["telegram_notified"] = True

    elif decision == "REVISE":
        draft["draft_status"] = "revision_requested"
        draft["revision_request"] = {
            "requested": True,
            "requested_at": timestamp,
            "requested_by": "examiner",
            "comment": comment
        }

        if review_item:
            review_item["status"] = "revision_requested"
            review_item["examiner_decision"] = "REVISE"
            review_item["examiner_comment"] = comment
            review_item["decided_at"] = timestamp
            review_item["telegram_notified"] = True

    elif decision == "REJECT":
        draft["draft_status"] = "rejected"
        draft["rejection"] = {
            "rejected": True,
            "rejected_at": timestamp,
            "rejected_by": "examiner",
            "reason": comment
        }

        if review_item:
            review_item["status"] = "rejected"
            review_item["examiner_decision"] = "REJECT"
            review_item["examiner_comment"] = comment
            review_item["decided_at"] = timestamp
            review_item["telegram_notified"] = True

    save_json(GLOBAL_DRAFT_REGISTRY, draft_data)
    save_json(review_queue_path, review_queue)

    if decision == "APPROVE":
        validation_status, validation_issues = get_validation_status(draft)

        if validation_status != "passed":
            print("\nApproval received, but validation has not passed.")
            print("Sofia will attempt automatic refinement before publication preparation.")
            print(f"Current validation status: {validation_status or 'missing'}")
            print("Validation issues:")
            print(format_validation_issues(validation_issues))

            repair_ok = run_pipeline_command(
                [
                    "python3",
                    "app/repair_generated_content.py",
                    item_id
                ],
                "Auto-refine approved draft content"
            )

            if repair_ok:
                run_pipeline_command(
                    [
                        "python3",
                        "app/clean_generated_html.py",
                        item_id
                    ],
                    "Clean auto-refined approved draft"
                )

                run_pipeline_command(
                    [
                        "python3",
                        "app/validate_generated_content.py",
                        item_id
                    ],
                    "Validate auto-refined approved draft"
                )

            fresh_draft = reload_draft_from_registry(item_id)

            if fresh_draft:
                validation_status, validation_issues = get_validation_status(fresh_draft)

        if validation_status == "passed":
            run_pipeline_command(
                [
                    "python3",
                    "app/run_publishing_pipeline.py",
                    item_id,
                    "--after-approval"
                ],
                "Prepare publication drafts after approval"
            )
        else:
            print("\nApproval received, but publication preparation was blocked.")
            print(f"Validation status: {validation_status or 'missing'}")
            print("Validation issues:")
            print(format_validation_issues(validation_issues))
            print("\nNo WordPress/platform draft was prepared.")
            print("Sofia must continue internal SEO/quality refinement before publication preparation.")

    if decision == "REVISE":
        if comment:
            revision_ok = run_pipeline_command(
                [
                    "python3",
                    "app/apply_draft_revision.py",
                    workspace.get("workspace_id"),
                    item_id,
                    comment
                ],
                "Apply AI draft revision"
            )

            if revision_ok:
                clean_ok = run_pipeline_command(
                    [
                        "python3",
                        "app/clean_generated_html.py",
                        item_id
                    ],
                    "Clean revised generated HTML"
                )

                validation_ok = run_pipeline_command(
                    [
                        "python3",
                        "app/validate_generated_content.py",
                        item_id
                    ],
                    "Validate revised generated content"
                )

                if not validation_ok:
                    repair_ok = run_pipeline_command(
                        [
                            "python3",
                            "app/repair_generated_content.py",
                            item_id
                        ],
                        "Repair revised generated content"
                    )

                    if repair_ok:
                        run_pipeline_command(
                            [
                                "python3",
                                "app/clean_generated_html.py",
                                item_id
                            ],
                            "Clean repaired generated HTML"
                        )

                        run_pipeline_command(
                            [
                                "python3",
                                "app/validate_generated_content.py",
                                item_id
                            ],
                            "Validate repaired generated content"
                        )
        else:
            print("\nRevision requested, but no comment was provided.")
            print("No automatic revision loop was triggered.")

    print("Draft decision processed successfully.")
    print(f"Workspace: {workspace.get('workspace_id')}")
    print(f"Draft: {item_id}")
    print(f"Decision: {decision}")
    print(f"New draft status: {draft.get('draft_status')}")
    if comment:
        print(f"Comment: {comment}")

    return True

def main():
    print("=== Sofia: Process Examiner Decision ===\n")

    if len(sys.argv) < 3:
        print("Usage:")
        print('python app/process_examiner_decision.py WORKSPACE_ID "APPROVE OPP-AO-001"')
        print('python app/process_examiner_decision.py WORKSPACE_ID "MODIFY OPP-AO-001: comment"')
        print('python app/process_examiner_decision.py WORKSPACE_ID "APPROVE DRAFT-0005"')
        print('python app/process_examiner_decision.py WORKSPACE_ID "REVISE DRAFT-0005: comment"')
        return

    workspace_id = sys.argv[1]
    reply_text = " ".join(sys.argv[2:]).strip()

    parsed = parse_reply(reply_text)

    if not parsed:
        print("Could not parse examiner reply.")
        print("Expected examples:")
        print("APPROVE OPP-AO-001")
        print("MODIFY OPP-AO-001: change angle")
        print("APPROVE DRAFT-0005")
        print("REVISE DRAFT-0005: change terminology")
        return

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, workspace_id)

    if not workspace:
        print(f"Workspace not found: {workspace_id}")
        return

    decision = parsed["decision"]
    item_id = parsed["item_id"]
    comment = parsed["comment"]

    if item_id.startswith("OPP-"):
        process_opportunity_decision(workspace, item_id, decision, comment)
        return

    if item_id.startswith("DRAFT-"):
        process_draft_decision(workspace, item_id, decision, comment)
        return

    print(f"Unknown item type: {item_id}")


if __name__ == "__main__":
    main()