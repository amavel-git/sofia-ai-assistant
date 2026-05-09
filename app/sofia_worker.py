#!/usr/bin/env python3
"""
Sofia Background Worker

Purpose:
- Process long-running Sofia jobs outside telegram_listener.py.
- Keep Telegram responsive by allowing the listener to create jobs quickly.
- Execute queued jobs from each workspace-level job_registry.json.

Current status:
- Skeleton worker.
- Supports reading queued jobs.
- Supports simulated processing for testing.
- Real pipeline execution will be added in the next patch.

Initial supported job type:
    approved_opportunity_to_review_draft

Target real workflow for that job:
1. Convert approved opportunity to intake
2. Process next intake
3. Generate website draft
4. Clean HTML
5. Validate
6. Repair if needed
7. Clean again
8. Validate again
9. If passed, notify examiner review
10. If failed, store error internally and do not send confusing examiner message
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional


# Allow this file to be run directly:
#   python app/sofia_worker.py local.ao --list
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.job_queue import (
    get_next_queued_job,
    list_jobs,
    mark_job_completed,
    mark_job_failed,
    mark_job_running,
    mark_step_completed,
    update_job,
    print_job_summary,
)


SUPPORTED_JOB_TYPES = {
    "approved_opportunity_to_review_draft",
    "revise_draft",
    "approved_draft_to_wordpress_review",
}

def run_pipeline_command(
    command: list[str],
    step_name: str,
    timeout_seconds: int = 900,
    required_stdout_text: str | None = None,
    fail_on_error: bool = True,
) -> Dict[str, Any]:
    """
    Run one Sofia pipeline command and capture output safely.

    This lets the worker execute long-running commands outside Telegram.
    Output is stored in job_registry.json if something fails.

    If required_stdout_text is provided, the command is only considered
    successful when that text appears in stdout.

    If fail_on_error=False, the command result is returned even when the
    command exits with a non-zero return code. This is useful for validation,
    because a validation failure should trigger repair instead of immediately
    killing the whole job.
    """

    print(f"\nRunning step: {step_name}")
    print("Command:", " ".join(command))

    completed = subprocess.run(
        command,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )

    result = {
        "step_name": step_name,
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "success": completed.returncode == 0,
    }

    if completed.stdout:
        print(completed.stdout)

    if completed.stderr:
        print(completed.stderr)

    if completed.returncode != 0:
        result["success"] = False

        if fail_on_error:
            raise RuntimeError(
                f"Pipeline step failed: {step_name}\n"
                f"Return code: {completed.returncode}\n"
                f"STDOUT:\n{completed.stdout}\n"
                f"STDERR:\n{completed.stderr}"
            )

        return result

    if required_stdout_text and required_stdout_text not in completed.stdout:
        result["success"] = False

        if fail_on_error:
            raise RuntimeError(
                f"Pipeline step did not produce expected confirmation: {step_name}\n"
                f"Expected text: {required_stdout_text}\n"
                f"STDOUT:\n{completed.stdout}\n"
                f"STDERR:\n{completed.stderr}"
            )

        return result

    return result

def extract_created_draft_id(process_output: str) -> str:
    """
    Extract newly created draft id from process_next_intake.py output.

    Expected output example:
        Draft created: DRAFT-0002
    """

    if not process_output:
        return ""

    match = re.search(r"Draft created:\s*(DRAFT-\d+)", process_output)

    if match:
        return match.group(1)

    return ""


def find_intake_for_opportunity(opportunity_id: str) -> Optional[Dict[str, Any]]:
    """
    Find an intake item created from a specific opportunity.

    This protects the worker from duplicate Telegram clicks or old jobs.
    """

    intake_path = ROOT_DIR / "sites" / "content_intake.json"

    if not intake_path.exists():
        return None

    try:
        data = json.loads(intake_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    for item in data.get("content_ideas", []):
        serialized = json.dumps(item, ensure_ascii=False)

        source_opp = (
            item.get("source_opportunity_id")
            or item.get("opportunity_id")
            or item.get("created_from_opportunity_id")
            or item.get("source_id")
        )

        if source_opp == opportunity_id or opportunity_id in serialized:
            return item

    return None


def set_current_step(workspace_id: str, job_id: str, step_name: str) -> Dict[str, Any]:
    """Set the current step for a running job."""
    return update_job(
        workspace_id,
        job_id,
        {
            "current_step": step_name,
        },
    )


def complete_step(workspace_id: str, job_id: str, step_name: str) -> Dict[str, Any]:
    """Mark one step as completed."""
    return mark_step_completed(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )


def handle_approved_opportunity_to_review_draft(
    job: Dict[str, Any],
    simulate_success: bool = False,
) -> Dict[str, Any]:
    """
    Handle approved_opportunity_to_review_draft.

    Current implementation:
    - Runs the first real step:
        convert_opportunity_to_intake.py workspace_id

    - Runs the second real step:
        process_next_intake.py

    - Simulates the remaining steps only when --simulate-success is used.

    Later we will connect the remaining real steps one by one.
    """

    workspace_id = job["workspace_id"]
    job_id = job["job_id"]
    opportunity_id = job.get("item_id")

    if not opportunity_id:
        raise ValueError("Job is missing item_id / opportunity_id.")

    completed_outputs = []

    # ------------------------------------------------------------
    # Step 1: real execution
    # Convert approved opportunity to intake
    # ------------------------------------------------------------
    step_name = "convert_approved_opportunity_to_intake"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "app/convert_opportunity_to_intake.py",
            workspace_id,
        ],
        step_name=step_name,
        fail_on_error=False,
    )

    completed_outputs.append(output)

    stdout = output.get("stdout", "")

    if "New intake entries created: 1" in stdout:
        print("Opportunity converted to a new intake item.")

    elif "already exists in content_intake.json" in stdout or "New intake entries created: 0" in stdout:
        existing_intake = find_intake_for_opportunity(opportunity_id)

        if not existing_intake:
            raise RuntimeError(
                "Opportunity conversion created no new intake, but no matching "
                f"intake item could be found for {opportunity_id}."
            )

        existing_status = existing_intake.get("status", "")
        existing_intake_id = existing_intake.get("intake_id", "")
        existing_draft_id = (
            existing_intake.get("draft_conversion", {}).get("draft_id")
            or ""
        )

        if existing_status == "new":
            print(
                "Opportunity already exists in content_intake.json, but intake "
                "status is still 'new'. Worker will continue to process it."
            )

            update_job(
                workspace_id=workspace_id,
                job_id=job_id,
                updates={
                    "payload": {
                        **job.get("payload", {}),
                        "intake_id": existing_intake_id,
                        "existing_intake_reused": True,
                    }
                },
            )

        elif existing_status == "converted_to_draft":
            raise RuntimeError(
                f"Opportunity {opportunity_id} was already converted to "
                f"{existing_draft_id or 'a draft'} from intake {existing_intake_id}. "
                "This job appears to be a duplicate or old Telegram action."
            )

        else:
            raise RuntimeError(
                f"Opportunity {opportunity_id} already exists in intake as "
                f"{existing_intake_id}, but its status is '{existing_status}'. "
                "Worker cannot safely continue."
            )

    else:
        raise RuntimeError(
            "Opportunity conversion did not confirm that a new intake was created.\n"
            f"STDOUT:\n{stdout}\n"
            f"STDERR:\n{output.get('stderr', '')}"
        )

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 2: real execution
    # Process next intake and create workspace-level draft
    # ------------------------------------------------------------
    step_name = "process_next_intake"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "app/process_next_intake.py",
        ],
        step_name=step_name,
        required_stdout_text="Draft created:",
    )

    completed_outputs.append(output)

    created_draft_id = extract_created_draft_id(output.get("stdout", ""))

    if not created_draft_id:
        raise RuntimeError(
            "process_next_intake.py reported success, but no DRAFT-xxxx id "
            "could be extracted from its output."
        )

    update_job(
        workspace_id=workspace_id,
        job_id=job_id,
        updates={
            "payload": {
                **job.get("payload", {}),
                "draft_id": created_draft_id,
            }
        },
    )

    print(f"Created draft captured by worker: {created_draft_id}")

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 3: real execution
    # Generate website draft content
    # ------------------------------------------------------------
    step_name = "generate_website_draft"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "app/generate_website_draft.py",
            workspace_id,
            created_draft_id,
        ],
        step_name=step_name,
        timeout_seconds=1800,
        required_stdout_text="Website draft generated successfully.",
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 4: real execution
    # Clean generated HTML first pass
    # ------------------------------------------------------------
    step_name = "clean_generated_html_first_pass"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "app/clean_generated_html.py",
            created_draft_id,
        ],
        step_name=step_name,
        required_stdout_text="Content cleaned successfully.",
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 5: real execution
    # Validate generated content first pass
    # ------------------------------------------------------------
    step_name = "validate_generated_content_first_pass"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    validation_output = run_pipeline_command(
        command=[
            sys.executable,
            "app/validate_generated_content.py",
            workspace_id,
            created_draft_id,
        ],
        step_name=step_name,
        required_stdout_text="Validation status: passed",
        fail_on_error=False,
    )

    completed_outputs.append(validation_output)

    first_validation_passed = validation_output.get("success") is True

    if first_validation_passed:
        print("First validation passed.")

        complete_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

    else:
        print("First validation failed. Sofia will attempt automatic repair.")

        complete_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        # ------------------------------------------------------------
        # Step 6: real execution
        # Repair generated content
        # ------------------------------------------------------------
        step_name = "repair_generated_content_if_needed"

        set_current_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        output = run_pipeline_command(
            command=[
                sys.executable,
                "app/repair_generated_content.py",
                workspace_id,
                created_draft_id,
            ],
            step_name=step_name,
            timeout_seconds=1800,
        )

        completed_outputs.append(output)

        complete_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        # ------------------------------------------------------------
        # Step 7: real execution
        # Clean repaired HTML
        # ------------------------------------------------------------
        step_name = "clean_generated_html_second_pass"

        set_current_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        output = run_pipeline_command(
            command=[
                sys.executable,
                "app/clean_generated_html.py",
                created_draft_id,
            ],
            step_name=step_name,
            required_stdout_text="Content cleaned successfully.",
        )

        completed_outputs.append(output)

        complete_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        # ------------------------------------------------------------
        # Step 8: real execution
        # Validate repaired content
        # ------------------------------------------------------------
        step_name = "validate_generated_content_second_pass"

        set_current_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        output = run_pipeline_command(
            command=[
                sys.executable,
                "app/validate_generated_content.py",
                workspace_id,
                created_draft_id,
            ],
            step_name=step_name,
            required_stdout_text="Validation status: passed",
            fail_on_error=True,
        )

        completed_outputs.append(output)

        complete_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

    # ------------------------------------------------------------
    # Step 9: real execution
    # Notify examiner review only after validation has passed
    # ------------------------------------------------------------
    step_name = "notify_examiner_review_if_valid"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "app/notify_examiner_review.py",
            workspace_id,
            "--send",
        ],
        step_name=step_name,
        required_stdout_text="Telegram message sent with buttons.",
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    for step_name in remaining_steps:
        print(f"Simulating step: {step_name}")

        set_current_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        complete_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

    result = {
        "message": "Approved opportunity converted to validated draft and sent for examiner review.",
        "opportunity_id": opportunity_id,
        "simulated_remaining_steps": False,
        "completed_outputs": completed_outputs,
        "draft_id": created_draft_id,
        "review_notification_sent": True,
    }

    return mark_job_completed(
        workspace_id=workspace_id,
        job_id=job_id,
        result=result,
    )


def handle_revise_draft(
    job: Dict[str, Any],
    simulate_success: bool = False,
) -> Dict[str, Any]:
    """
    Handle revise_draft.

    Workflow:
    1. Apply draft revision with examiner instructions
    2. Clean revised HTML
    3. Validate revised content
    4. Repair if needed
    5. Clean again
    6. Validate again
    7. WordPress update and examiner notification are connected later
    """

    workspace_id = job["workspace_id"]
    job_id = job["job_id"]
    draft_id = job.get("item_id")
    payload = job.get("payload", {}) or {}
    revision_comment = payload.get("revision_comment", "")

    if not draft_id:
        raise ValueError("Job is missing item_id / draft_id.")

    if not revision_comment:
        raise ValueError("revise_draft job is missing revision_comment in payload.")

    completed_outputs = []

    # ------------------------------------------------------------
    # Step 1: real execution
    # Apply AI draft revision
    # ------------------------------------------------------------
    step_name = "apply_draft_revision"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "app/apply_draft_revision.py",
            workspace_id,
            draft_id,
            revision_comment,
        ],
        step_name=step_name,
        timeout_seconds=1800,
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 2: real execution
    # Clean revised HTML first pass
    # ------------------------------------------------------------
    step_name = "clean_revised_html_first_pass"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "app/clean_generated_html.py",
            draft_id,
        ],
        step_name=step_name,
        required_stdout_text="Content cleaned successfully.",
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 3: real execution
    # Validate revised content first pass
    # ------------------------------------------------------------
    step_name = "validate_revised_content_first_pass"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    validation_output = run_pipeline_command(
        command=[
            sys.executable,
            "app/validate_generated_content.py",
            workspace_id,
            draft_id,
        ],
        step_name=step_name,
        required_stdout_text="Validation status: passed",
        fail_on_error=False,
    )

    completed_outputs.append(validation_output)

    first_validation_passed = validation_output.get("success") is True

    if first_validation_passed:
        print("Revised draft passed first validation.")

        complete_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

    else:
        print("Revised draft failed first validation. Sofia will attempt automatic repair.")

        complete_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        # ------------------------------------------------------------
        # Step 4: real execution
        # Repair revised content
        # ------------------------------------------------------------
        step_name = "repair_revised_content_if_needed"

        set_current_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        output = run_pipeline_command(
            command=[
                sys.executable,
                "app/repair_generated_content.py",
                workspace_id,
                draft_id,
            ],
            step_name=step_name,
            timeout_seconds=1800,
        )

        completed_outputs.append(output)

        complete_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        # ------------------------------------------------------------
        # Step 5: real execution
        # Clean repaired revised HTML
        # ------------------------------------------------------------
        step_name = "clean_revised_html_second_pass"

        set_current_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        output = run_pipeline_command(
            command=[
                sys.executable,
                "app/clean_generated_html.py",
                draft_id,
            ],
            step_name=step_name,
            required_stdout_text="Content cleaned successfully.",
        )

        completed_outputs.append(output)

        complete_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        # ------------------------------------------------------------
        # Step 6: real execution
        # Validate repaired revised content
        # ------------------------------------------------------------
        step_name = "validate_revised_content_second_pass"

        set_current_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        output = run_pipeline_command(
            command=[
                sys.executable,
                "app/validate_generated_content.py",
                workspace_id,
                draft_id,
            ],
            step_name=step_name,
            required_stdout_text="Validation status: passed",
            fail_on_error=True,
        )

        completed_outputs.append(output)

        complete_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

    # ------------------------------------------------------------
    # Step 7: real execution
    # Notify examiner review after revision
    # ------------------------------------------------------------
    step_name = "notify_examiner_review_after_revision"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "app/notify_examiner_review.py",
            workspace_id,
            "--send",
        ],
        step_name=step_name,
        required_stdout_text="Telegram message sent with buttons.",
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    result = {
        "message": "Revised draft validated and sent back for examiner review.",
        "draft_id": draft_id,
        "revision_comment": revision_comment,
        "simulated_remaining_steps": False,
        "completed_outputs": completed_outputs,
        "review_notification_sent": True,
        "wordpress_updated": False,
    }

    return mark_job_completed(
        workspace_id=workspace_id,
        job_id=job_id,
        result=result,
    )


def handle_approved_draft_to_wordpress_review(
    job: Dict[str, Any],
    simulate_success: bool = False,
) -> Dict[str, Any]:
    """
    Handle approved_draft_to_wordpress_review.

    Correct workflow:
    1. Create/update WordPress draft after examiner approval
    2. Notify examiner with WordPress-stage review message/link
    3. Mark job completed
    """

    workspace_id = job["workspace_id"]
    job_id = job["job_id"]
    draft_id = job.get("item_id")
    payload = job.get("payload", {}) or {}
    approval_comment = payload.get("approval_comment", "")

    if not draft_id:
        raise ValueError("Job is missing item_id / draft_id.")

    completed_outputs = []

    # ------------------------------------------------------------
    # Step 1: real execution
    # Create/update WordPress draft after examiner approval
    # ------------------------------------------------------------
    step_name = "create_or_update_wordpress_draft_after_approval"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "app/update_wordpress_draft.py",
            workspace_id,
            draft_id,
        ],
        step_name=step_name,
        timeout_seconds=900,
        fail_on_error=True,
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 2: real execution
    # Notify examiner with WordPress-stage review message/link
    # ------------------------------------------------------------
    step_name = "notify_wordpress_review_if_ready"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "app/notify_examiner_review.py",
            workspace_id,
            "--send-draft",
            draft_id,
        ],
        step_name=step_name,
        timeout_seconds=120,
        required_stdout_text="Telegram message sent with buttons.",
        fail_on_error=True,
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    result = {
        "message": "Approved draft prepared in WordPress and sent for final examiner review.",
        "draft_id": draft_id,
        "approval_comment": approval_comment,
        "simulated": False,
        "wordpress_prepared": True,
        "review_notification_sent": True,
        "completed_outputs": completed_outputs,
    }

    return mark_job_completed(
        workspace_id=workspace_id,
        job_id=job_id,
        result=result,
    )


def process_job(
    job: Dict[str, Any],
    simulate_success: bool = False,
) -> Dict[str, Any]:
    """
    Process one queued job.

    This function:
    - marks the job running
    - dispatches by job_type
    - marks completed or failed
    """

    workspace_id = job["workspace_id"]
    job_id = job["job_id"]
    job_type = job["job_type"]

    print("Starting job:")
    print_job_summary(job)

    mark_job_running(
        workspace_id=workspace_id,
        job_id=job_id,
        current_step="starting",
    )

    try:
        if job_type == "approved_opportunity_to_review_draft":
            completed_job = handle_approved_opportunity_to_review_draft(
                job=job,
                simulate_success=simulate_success,
            )

        elif job_type == "revise_draft":
            completed_job = handle_revise_draft(
                job=job,
                simulate_success=simulate_success,
            )

        elif job_type == "approved_draft_to_wordpress_review":
            completed_job = handle_approved_draft_to_wordpress_review(
                job=job,
                simulate_success=simulate_success,
            )

        else:
            raise ValueError(f"Unsupported job type: {job_type}")

        print("\nJob completed:")
        print_job_summary(completed_job)
        return completed_job

    except Exception as exc:
        error_details = {
            "exception_type": type(exc).__name__,
            "traceback": traceback.format_exc(),
        }

        failed_job = mark_job_failed(
            workspace_id=workspace_id,
            job_id=job_id,
            error_message=str(exc),
            error_details=error_details,
        )

        print("\nJob failed safely.")
        print_job_summary(failed_job)
        print(f"\nInternal error: {exc}")

        return failed_job


def process_next_job(
    workspace_id: str,
    job_type: Optional[str] = None,
    simulate_success: bool = False,
) -> Optional[Dict[str, Any]]:
    """Process the next queued job for one workspace."""

    job = get_next_queued_job(
        workspace_id=workspace_id,
        job_type=job_type,
    )

    if not job:
        print(f"No queued jobs found for workspace: {workspace_id}")
        return None

    return process_job(
        job=job,
        simulate_success=simulate_success,
    )


def watch_workspace_jobs(
    workspace_id: str,
    job_type: Optional[str] = None,
    poll_seconds: int = 15,
    simulate_success: bool = False,
) -> None:
    """
    Continuously watch one workspace job registry and process queued jobs.

    This is the first simple worker loop.
    Later this can be moved to a Windows/WSL service.
    """

    print("=== Sofia Worker Watch Mode ===")
    print(f"Workspace: {workspace_id}")
    print(f"Job type filter: {job_type or 'all'}")
    print(f"Poll seconds: {poll_seconds}")
    print("Press Ctrl+C to stop.\n")

    while True:
        try:
            job = get_next_queued_job(
                workspace_id=workspace_id,
                job_type=job_type,
            )

            if job:
                print("\nQueued job found. Processing now.")
                process_job(
                    job=job,
                    simulate_success=simulate_success,
                )
            else:
                print(f"No queued jobs. Sleeping {poll_seconds}s...")

            time.sleep(poll_seconds)

        except KeyboardInterrupt:
            print("\nSofia worker watch stopped by user.")
            break

        except Exception as exc:
            print(f"\nWorker watch error: {type(exc).__name__}: {exc}")
            time.sleep(poll_seconds)


def show_jobs(workspace_id: str, status: Optional[str] = None) -> None:
    """Print a simple list of jobs for a workspace."""
    jobs = list_jobs(
        workspace_id=workspace_id,
        status=status,
    )

    if not jobs:
        print(f"No jobs found for workspace: {workspace_id}")
        return

    for job in jobs:
        print("-" * 60)
        print_job_summary(job)


def build_arg_parser() -> argparse.ArgumentParser:
    """Build CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Sofia background worker"
    )

    parser.add_argument(
        "workspace_id",
        help="Workspace id, e.g. local.ao",
    )

    parser.add_argument(
        "--job-type",
        default=None,
        help="Optional job type filter.",
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List jobs instead of processing one.",
    )

    parser.add_argument(
        "--status",
        default=None,
        help="Optional status filter for --list, e.g. queued, running, completed, failed.",
    )

    parser.add_argument(
        "--simulate-success",
        action="store_true",
        help="Simulate successful execution without running real pipeline scripts.",
    )

    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously watch the workspace job registry and process queued jobs.",
    )

    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=15,
        help="Polling interval for --watch mode. Default: 15 seconds.",
    )

    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.list:
        show_jobs(
            workspace_id=args.workspace_id,
            status=args.status,
        )
        return

    if args.watch:
        watch_workspace_jobs(
            workspace_id=args.workspace_id,
            job_type=args.job_type,
            poll_seconds=args.poll_seconds,
            simulate_success=args.simulate_success,
        )
        return

    process_next_job(
        workspace_id=args.workspace_id,
        job_type=args.job_type,
        simulate_success=args.simulate_success,
    )


if __name__ == "__main__":
    main()