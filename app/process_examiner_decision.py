import json
import re
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timezone

from workspace_paths import (
    get_workspace_draft_registry_path,
    empty_draft_registry,
)

from job_queue import create_job

SOFIA_ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = SOFIA_ROOT / "data" / "workspaces.json"
GLOBAL_DRAFT_REGISTRY = SOFIA_ROOT / "sites" / "draft_registry.json"


OPPORTUNITY_DECISIONS = ["APPROVE", "MODIFY", "REJECT"]
DRAFT_DECISIONS = ["APPROVE", "REVISE", "REJECT", "COMPLETE"]


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

    combined_output = ""

    if result.stdout:
        combined_output += result.stdout
        print(result.stdout.strip())

    if result.stderr:
        combined_output += "\n" + result.stderr
        print(result.stderr.strip())

    logical_failure_markers = [
        "Traceback",
        "Exception",
        "WordPress pipeline failed",
        "WordPress update/upload failed",
        "Draft is not exportable",
        "Draft status is not uploadable",
        "Draft validation has not passed",
    ]

    if result.returncode != 0:
        print(f"Auto step failed: {label}")
        return False

    for marker in logical_failure_markers:
        if marker in combined_output:
            print(f"Auto step failed: {label}")
            print(f"Detected logical failure marker: {marker}")
            return False

    print(f"Auto step completed: {label}")
    return True

def run_pipeline_command_capture(args, label):
    print(f"\nAuto step: {label}")
    result = subprocess.run(
        args,
        cwd=str(SOFIA_ROOT),
        text=True,
        capture_output=True
    )

    combined_output = ""

    if result.stdout:
        combined_output += result.stdout
        print(result.stdout.strip())

    if result.stderr:
        combined_output += "\n" + result.stderr
        print(result.stderr.strip())

    if result.returncode != 0:
        print(f"Auto step failed: {label}")
        return False, combined_output

    print(f"Auto step completed: {label}")
    return True, combined_output


def extract_created_draft_id(process_output):
    if not process_output:
        return ""

    match = re.search(r"Draft created:\s*(DRAFT-\d+)", process_output)
    if match:
        return match.group(1)

    return ""


def add_internal_links_before_review(draft_id):
    print("\nAuto step: Add internal links before examiner review")
    print(f"Draft: {draft_id}")

    inject_ok = run_pipeline_command(
        [
            "python3",
            "app/inject_internal_links.py",
            draft_id
        ],
        "Inject base internal links"
    )

    if not inject_ok:
        print("Base internal links were not injected.")
        return False

    optimize_ok = run_pipeline_command(
        [
            "python3",
            "app/optimize_internal_link_anchors.py",
            draft_id
        ],
        "Optimize internal link anchors"
    )

    if not optimize_ok:
        print("AI internal link anchor optimization did not complete.")
        return True

    apply_ok = run_pipeline_command(
        [
            "python3",
            "app/apply_ai_internal_links.py",
            draft_id
        ],
        "Apply AI internal links"
    )

    if not apply_ok:
        print("AI internal links were not applied.")
        return True

    return True


def generate_and_validate_draft_before_review(workspace_id, draft_id):
    print(f"\nAuto step: Generate and validate draft before examiner review")
    print(f"Workspace: {workspace_id}")
    print(f"Draft: {draft_id}")

    generation_ok = run_pipeline_command(
        [
            "python3",
            "app/generate_website_draft.py",
            workspace_id,
            draft_id
        ],
        "Generate website draft content"
    )

    if not generation_ok:
        print("Draft generation failed. Draft will remain in review queue, but content is not ready.")
        return False

    clean_ok = run_pipeline_command(
        [
            "python3",
            "app/clean_generated_html.py",
            draft_id
        ],
        "Clean generated HTML"
    )

    if not clean_ok:
        print("Cleaning generated HTML failed.")
        return False

    validation_ok = run_pipeline_command(
        [
            "python3",
            "app/validate_generated_content.py",
            draft_id
        ],
        "Validate generated content"
    )

    if validation_ok:
        link_ok = add_internal_links_before_review(draft_id)

        if link_ok:
            final_clean_ok = run_pipeline_command(
                [
                    "python3",
                    "app/clean_generated_html.py",
                    draft_id
                ],
                "Final clean after internal links"
            )

            if not final_clean_ok:
                print("Final cleaning after internal links failed.")
                return False

            final_validation_ok = run_pipeline_command(
                [
                    "python3",
                    "app/validate_generated_content.py",
                    draft_id
                ],
                "Final validation after internal links"
            )

            if final_validation_ok:
                print("Draft generated, internally linked, and validated successfully before examiner review.")
                return True

            print("Draft failed final validation after internal links.")
            return False

        print("Internal links were not applied, but draft validation passed.")
        print("Draft will continue to examiner review without internal links.")
        return True

    print("\nValidation failed. Sofia will attempt automatic repair before examiner review.")

    repair_ok = run_pipeline_command(
        [
            "python3",
            "app/repair_generated_content.py",
            workspace.get("workspace_id"),
            item_id
        ],
        "Repair generated content"
    )

    if not repair_ok:
        print("Repair failed.")
        return False

    clean_after_repair_ok = run_pipeline_command(
        [
            "python3",
            "app/clean_generated_html.py",
            draft_id
        ],
        "Clean repaired generated HTML"
    )

    if not clean_after_repair_ok:
        print("Cleaning repaired HTML failed.")
        return False

    final_validation_ok = run_pipeline_command(
        [
            "python3",
            "app/validate_generated_content.py",
            draft_id
        ],
        "Validate repaired generated content"
    )

    if final_validation_ok:
        link_ok = add_internal_links_before_review(draft_id)

        if link_ok:
            final_clean_ok = run_pipeline_command(
                [
                    "python3",
                    "app/clean_generated_html.py",
                    draft_id
                ],
                "Final clean after internal links"
            )

            if not final_clean_ok:
                print("Final cleaning after internal links failed.")
                return False

            final_validation_after_links_ok = run_pipeline_command(
                [
                    "python3",
                    "app/validate_generated_content.py",
                    draft_id
                ],
                "Final validation after internal links"
            )

            if final_validation_after_links_ok:
                print("Draft repaired, internally linked, and validated successfully before examiner review.")
                return True

            print("Draft failed final validation after internal links.")
            return False

        print("Internal links were not applied, but repaired draft validation passed.")
        print("Draft will continue to examiner review without internal links.")
        return True

    print("Draft still has validation issues after repair.")
    return False


def find_workspace(workspaces, workspace_id):
    for workspace in workspaces.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def parse_reply(reply_text):
    reply_text = reply_text.strip()

    match = re.match(
        r"^(APPROVE|MODIFY|REVISE|REJECT|COMPLETE)\s+([A-Z]+-[A-Z0-9-]+|DRAFT-\d+)(?::\s*(.*))?$",
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

        job = create_job(
            workspace_id=workspace_id,
            job_type="approved_opportunity_to_review_draft",
            item_id=item_id,
            payload={
                "opportunity_id": item_id,
                "examiner_comment": comment,
                "approved_at": timestamp
            },
            created_by="process_examiner_decision",
            source="examiner_decision"
        )

        print("\nBackground job created for approved opportunity.")
        print(f"Job ID: {job.get('job_id')}")
        print(f"Job status: {job.get('status')}")
        print("The long intake/draft generation pipeline will be handled by sofia_worker.py.")

    print("Opportunity decision processed successfully.")
    print(f"Workspace: {workspace.get('workspace_id')}")
    print(f"Opportunity: {item_id}")
    print(f"Decision: {decision}")

    if decision == "APPROVE":
        print("\nOpportunity approved and queued for background processing.")

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

def load_workspace_draft_data(workspace):
    workspace_id = workspace.get("workspace_id")
    draft_registry_path = get_workspace_draft_registry_path(workspace_id)

    if draft_registry_path.exists():
        return draft_registry_path, load_json(draft_registry_path)

    return draft_registry_path, empty_draft_registry(workspace_id)


def reload_draft_from_registry(workspace, draft_id):
    draft_registry_path, draft_data = load_workspace_draft_data(workspace)
    drafts = draft_data.get("drafts", [])

    return find_draft(drafts, draft_id)


def draft_has_wordpress_upload(draft):
    upload = draft.get("wordpress_upload", {})
    return upload.get("uploaded") is True and bool(upload.get("wordpress_id"))


def update_existing_wordpress_draft_if_present(workspace, draft_id):
    fresh_draft = reload_draft_from_registry(workspace, draft_id)

    if not fresh_draft:
        print("Could not reload draft before WordPress revision update.")
        return False

    if not draft_has_wordpress_upload(fresh_draft):
        print("No existing WordPress draft found for this draft. Skipping WordPress update after revision.")
        return True

    validation_status, validation_issues = get_validation_status(fresh_draft)

    if validation_status != "passed":
        print("Revised draft has not passed validation. Skipping WordPress update after revision.")
        print(f"Validation status: {validation_status or 'missing'}")
        print("Validation issues:")
        print(format_validation_issues(validation_issues))
        return False

    return run_pipeline_command(
        [
            "python3",
            "app/run_publishing_pipeline.py",
            draft_id,
            "--after-approval"
        ],
        "Update existing WordPress draft after revision"
    )


def process_draft_decision(workspace, item_id, decision, comment):
    if decision not in DRAFT_DECISIONS:
        print(f"Invalid draft decision: {decision}")
        print(f"Valid draft decisions: {', '.join(DRAFT_DECISIONS)}")
        return False

    review_queue_path = SOFIA_ROOT / workspace["review_queue_path"]

    if not review_queue_path.exists():
        print(f"Review queue not found: {review_queue_path}")
        return False

    draft_registry_path, draft_data = load_workspace_draft_data(workspace)
    drafts = draft_data.get("drafts", [])

    draft = find_draft(drafts, item_id)

    if not draft:
        print(f"Draft not found in workspace draft registry: {item_id}")
        print(f"Registry: {draft_registry_path}")
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
            review_item["updated_at"] = timestamp

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
            review_item["updated_at"] = timestamp

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
            review_item["updated_at"] = timestamp

    elif decision == "COMPLETE":
        draft["draft_status"] = "completed"
        draft["completed_at"] = timestamp
        draft["completion"] = {
            "completed": True,
            "completed_at": timestamp,
            "completed_by": "examiner",
            "notes": comment,
            "publication_note": "WordPress draft completed for manual final review/publication. Live publication was not automatic."
        }

        draft["ready_for_publishing"] = True
        draft["wordpress_status"] = "completed_for_manual_publication"

        if review_item:
            review_item["status"] = "completed"
            review_item["examiner_decision"] = "COMPLETE"
            review_item["examiner_comment"] = comment
            review_item["decided_at"] = timestamp
            review_item["telegram_notified"] = True
            review_item["ready_for_publishing"] = True
            review_item["updated_at"] = timestamp

    draft_data["scope"] = "workspace"
    draft_data["workspace_id"] = workspace.get("workspace_id")

    save_json(draft_registry_path, draft_data)
    save_json(review_queue_path, review_queue)

    if decision == "COMPLETE":
        run_pipeline_command(
            [
                "python3",
                "app/update_content_inventory.py",
                workspace.get("workspace_id"),
                item_id
            ],
            "Update completed content inventory"
        )

    if decision == "APPROVE":
        validation_status, validation_issues = get_validation_status(draft)

        if validation_status != "passed":
            print("\nApproval received, but validation has not passed.")
            print(f"Validation status: {validation_status or 'missing'}")
            print("Validation issues:")
            print(format_validation_issues(validation_issues))
            print("\nNo WordPress/platform draft job was created.")
            print("Sofia must repair and validate the draft before publication preparation.")
        else:
            workspace_id = workspace.get("workspace_id")

            job = create_job(
                workspace_id=workspace_id,
                job_type="approved_draft_to_wordpress_review",
                item_id=item_id,
                payload={
                    "draft_id": item_id,
                    "approval_comment": comment,
                    "approved_at": timestamp,
                },
                created_by="process_examiner_decision",
                source="examiner_decision",
            )

            print("\nBackground job created for WordPress draft preparation.")
            print(f"Job ID: {job.get('job_id')}")
            print(f"Job status: {job.get('status')}")
            print("The WordPress preparation pipeline will be handled by sofia_worker.py.")

    if decision == "REVISE":
        if comment:
            workspace_id = workspace.get("workspace_id")

            job = create_job(
                workspace_id=workspace_id,
                job_type="revise_draft",
                item_id=item_id,
                payload={
                    "draft_id": item_id,
                    "revision_comment": comment,
                    "requested_at": timestamp,
                },
                created_by="process_examiner_decision",
                source="examiner_decision",
            )

            print("\nBackground job created for draft revision.")
            print(f"Job ID: {job.get('job_id')}")
            print(f"Job status: {job.get('status')}")
            print("The AI revision pipeline will be handled by sofia_worker.py.")
        else:
            print("\nRevision requested, but no comment was provided.")
            print("No background revision job was created.")

    fresh_final_draft = reload_draft_from_registry(workspace, item_id)
    final_status = (
        fresh_final_draft.get("draft_status")
        if fresh_final_draft
        else draft.get("draft_status")
    )

    print("Draft decision processed successfully.")
    print(f"Workspace: {workspace.get('workspace_id')}")
    print(f"Draft: {item_id}")
    print(f"Decision: {decision}")
    print(f"New draft status: {final_status}")
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