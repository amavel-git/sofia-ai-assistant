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
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv


# Allow this file to be run directly:
#   python app/sofia_worker.py local.ao --list
ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env", override=True)

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.job_queue import (
    get_workspace_config,
    get_next_queued_job,
    list_jobs,
    mark_job_completed,
    mark_job_failed,
    mark_job_running,
    mark_job_retry_pending,
    mark_step_completed,
    update_job,
    print_job_summary,
)


def get_bot_token() -> str:
    token = os.getenv("SOFIA_TELEGRAM_BOT_TOKEN", "")
    return token.strip().strip('"').strip("'")


def normalize_language(language: str) -> str:
    language = str(language or "").lower()

    if language.startswith("pt-br"):
        return "pt-BR"
    if language.startswith("pt"):
        return "pt-PT"
    if language.startswith("es"):
        return "es"
    if language.startswith("fr"):
        return "fr"
    if language.startswith("en"):
        return "en"

    return "en"


def send_telegram_message(chat_id: str, text: str) -> bool:
    bot_token = get_bot_token()

    if not bot_token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
        },
        timeout=20,
    )

    data = response.json()
    return data.get("ok") is True


def is_timeout_failure(exc: Exception, error_details: Dict[str, Any]) -> bool:
    text = (
        f"{type(exc).__name__} "
        f"{str(exc)} "
        f"{json.dumps(error_details, ensure_ascii=False)}"
    ).lower()
    return "timeout" in text or "timed out" in text


def build_job_failure_message(
    workspace_id: str,
    job: Dict[str, Any],
    exc: Exception,
    error_details: Dict[str, Any],
) -> str:
    workspace = get_workspace_config(workspace_id)
    lang = normalize_language(workspace.get("language", "en"))

    item_id = (
        job.get("item_id")
        or job.get("draft_id")
        or job.get("opportunity_id")
        or "unknown"
    )
    timeout_failure = is_timeout_failure(exc, error_details)
    job_status = job.get("status", "")
    is_retry_pending = job_status == "retry_pending"
    is_final_failure = job_status in ["failed", "failed_after_retries"]

    if str(item_id).startswith("DRAFT-"):
        item_label_pt = "Rascunho"
        item_label_es = "Borrador"
        item_label_fr = "Brouillon"
        item_label_en = "Draft"
    elif str(item_id).startswith("OPP-"):
        item_label_pt = "Oportunidade"
        item_label_es = "Oportunidad"
        item_label_fr = "Opportunité"
        item_label_en = "Opportunity"
    else:
        item_label_pt = "Item"
        item_label_es = "Item"
        item_label_fr = "Élément"
        item_label_en = "Item"

    if lang.startswith("pt"):
        reason = (
            "o processamento da IA demorou demasiado tempo."
            if timeout_failure
            else "ocorreu uma dificuldade técnica durante o processamento."
        )

        if is_retry_pending:
            return (
                "⚠️ A Sofia teve uma dificuldade técnica temporária ao processar esta tarefa.\n\n"
                f"{item_label_pt}: {item_id}\n"
                f"Motivo: {reason}\n\n"
                "Nenhuma ação é necessária neste momento. "
                "A Sofia manterá a tarefa na fila e voltará a tentar automaticamente."
            )

        return (
            "⚠️ A Sofia não conseguiu concluir esta tarefa.\n\n"
            f"{item_label_pt}: {item_id}\n"
            f"Motivo: {reason}\n\n"
            "A revisão/pedido ficou registado, mas será necessário tentar novamente mais tarde."
        )

    if lang == "es":
        reason = (
            "el procesamiento de la IA tardó demasiado tiempo."
            if timeout_failure
            else "se produjo una dificultad técnica durante el procesamiento."
        )
        return (
            "⚠️ Sofia tuvo una dificultad técnica al procesar esta tarea.\n\n"
            f"{item_label_es}: {item_id}\n"
            f"Motivo: {reason}\n\n"
            "La revisión/solicitud quedó registrada, pero será necesario intentarlo de nuevo más tarde."
        )

    if lang == "fr":
        reason = (
            "le traitement par l’IA a pris trop de temps."
            if timeout_failure
            else "une difficulté technique est survenue pendant le traitement."
        )
        return (
            "⚠️ Sofia a rencontré une difficulté technique pendant le traitement de cette tâche.\n\n"
            f"{item_label_fr} : {item_id}\n"
            f"Motif : {reason}\n\n"
            "La révision/demande a été enregistrée, mais il faudra réessayer plus tard."
        )

    reason = (
        "the AI processing took too long."
        if timeout_failure
        else "a technical issue occurred during processing."
    )
    return (
        "⚠️ Sofia encountered a technical issue while processing this task.\n\n"
        f"{item_label_en}: {item_id}\n"
        f"Reason: {reason}\n\n"
        "The revision/request was preserved, but it will need to be retried later."
    )


def notify_job_failure_to_telegram(
    workspace_id: str,
    job: Dict[str, Any],
    exc: Exception,
    error_details: Dict[str, Any],
) -> bool:
    try:
        workspace = get_workspace_config(workspace_id)
        chat_id = workspace.get("telegram_group_id")

        if not chat_id:
            return False

        message = build_job_failure_message(
            workspace_id=workspace_id,
            job=job,
            exc=exc,
            error_details=error_details,
        )

        return send_telegram_message(str(chat_id), message)

    except Exception as notify_exc:
        print(
            "WARNING: could not notify Telegram about job failure: "
            f"{type(notify_exc).__name__}: {notify_exc}"
        )
        return False


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
    created_draft_id = ""
    skip_process_next_intake = False

    payload = job.get("payload", {}) or {}
    existing_payload_draft_id = payload.get("draft_id", "")

    resume_from_existing_draft = False

    if existing_payload_draft_id and job.get("status") in {
        "queued",
        "retry_pending",
        "failed",
        "failed_after_retries",
    }:
        created_draft_id = existing_payload_draft_id
        skip_process_next_intake = True
        resume_from_existing_draft = True

        print(
            "Existing draft found in job payload. "
            f"Worker will resume from draft stage: {created_draft_id}"
        )

    if not resume_from_existing_draft:
            # ------------------------------------------------------------
            # Step 0A: real execution
        # Generate/update SEO brief BEFORE converting opportunity to intake
        # ------------------------------------------------------------
        step_name = "generate_opportunity_seo_brief"

        set_current_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        output = run_pipeline_command(
            command=[
                sys.executable,
                "app/generate_opportunity_seo_brief.py",
                workspace_id,
            ],
            step_name=step_name,
            timeout_seconds=300,
            fail_on_error=True,
        )

        completed_outputs.append(output)

        complete_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

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

        elif (
            "already exists in content_intake.json" in stdout
            or "New intake entries created: 0" in stdout
            or "No approved opportunities ready for intake conversion" in stdout
        ):
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
                if not existing_draft_id:
                    raise RuntimeError(
                        f"Opportunity {opportunity_id} was already converted to a draft "
                        f"from intake {existing_intake_id}, but no draft_id was found."
                    )

                created_draft_id = existing_draft_id
                skip_process_next_intake = True

                print(
                    f"Opportunity {opportunity_id} was already converted to "
                    f"{created_draft_id} from intake {existing_intake_id}. "
                    "Worker will resume from the existing draft."
                )

                update_job(
                    workspace_id=workspace_id,
                    job_id=job_id,
                    updates={
                        "payload": {
                            **job.get("payload", {}),
                            "intake_id": existing_intake_id,
                            "draft_id": created_draft_id,
                            "existing_intake_reused": True,
                            "existing_draft_reused": True,
                        }
                    },
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
        # Step 1B: real execution
        # Generate/update strategy brief after SEO brief
        # ------------------------------------------------------------
        step_name = "generate_content_strategy_brief"

        set_current_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        output = run_pipeline_command(
            command=[
                sys.executable,
                "app/generate_content_strategy_brief.py",
                workspace_id,
                "--force",
            ],
            step_name=step_name,
            timeout_seconds=300,
            fail_on_error=True,
        )

        completed_outputs.append(output)

        complete_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        # ------------------------------------------------------------
        # Step 1C: real execution
        # Generate/update draft input after strategy brief
        # ------------------------------------------------------------
        step_name = "generate_draft_input"

        set_current_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        output = run_pipeline_command(
            command=[
                sys.executable,
                "app/generate_draft_input.py",
                workspace_id,
                "--force",
            ],
            step_name=step_name,
            timeout_seconds=300,
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
        # Process next intake and create workspace-level draft
        # ------------------------------------------------------------
        step_name = "process_next_intake"

        set_current_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        if skip_process_next_intake and created_draft_id:
            output = {
                "step_name": step_name,
                "command": ["resume_existing_draft"],
                "returncode": 0,
                "stdout": f"Resumed existing draft: {created_draft_id}",
                "stderr": "",
                "success": True,
                "resumed": True,
            }
            completed_outputs.append(output)
            print(f"Skipping process_next_intake; resuming existing draft: {created_draft_id}")

        else:
            output = run_pipeline_command(
                command=[
                    sys.executable,
                    "app/process_next_intake.py",
                    workspace_id,
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
    # Step 4A: prepare AI image jobs from image_plan
    # ------------------------------------------------------------
    step_name = "generate_pending_images"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "-m",
            "app.image_assets.generate_pending_images",
            workspace_id,
            created_draft_id,
        ],
        step_name=step_name,
        timeout_seconds=300,
        fail_on_error=False,
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

        repair_stdout = output.get("stdout", "")
        if (
            "Repair cancelled" in repair_stdout
            or "STOP:" in repair_stdout
        ):
            raise RuntimeError(
                "Repair was cancelled because the repaired content still contained "
                "forbidden language, markdown, or meta commentary."
            )

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
            fail_on_error=False,
        )

        completed_outputs.append(output)

        if output.get("success") is True:
            print("Second validation passed.")
        else:
            validation_stdout = output.get("stdout", "").lower()
            faq_repair_needed = (
                "faq has fewer" in validation_stdout
                or "missing faq" in validation_stdout
                or "fewer than" in validation_stdout and "faq" in validation_stdout
            )

            if not faq_repair_needed:
                raise RuntimeError(
                    "Second validation failed. WordPress draft creation blocked. "
                    "Draft requires repair before examiner review."
                )

            print("Second validation failed because of FAQ count. Sofia will run FAQ-only repair.")

            complete_step(
                workspace_id=workspace_id,
                job_id=job_id,
                step_name=step_name,
            )

            # ------------------------------------------------------------
            # Step 8A: real execution
            # FAQ-only repair if validation only needs more FAQ items
            # ------------------------------------------------------------
            step_name = "repair_faq_if_needed"

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
                timeout_seconds=1200,
                required_stdout_text="Content repaired. Run validation again.",
                fail_on_error=True,
            )

            completed_outputs.append(output)

            complete_step(
                workspace_id=workspace_id,
                job_id=job_id,
                step_name=step_name,
            )

            # ------------------------------------------------------------
            # Step 8C: real execution
            # Validate after FAQ-only repair
            # ------------------------------------------------------------
            step_name = "validate_generated_content_after_faq_repair"

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
                fail_on_error=False,
            )

            completed_outputs.append(output)

            if output.get("success") is True:
                print("Validation passed after FAQ-only repair.")
            else:
                raise RuntimeError(
                    "Validation still failed after FAQ-only repair. "
                    "WordPress draft creation blocked."
                )

        complete_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

    # ------------------------------------------------------------
    # Step 8Z: real execution
    # Assemble WordPress-ready Gutenberg/Yoast content only after validation passes.
    # This prevents duplicate FAQ sections and duplicate Gutenberg blocks.
    # ------------------------------------------------------------
    step_name = "assemble_wordpress_content_final"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "app/assemble_wordpress_content.py",
            workspace_id,
            created_draft_id,
        ],
        step_name=step_name,
        timeout_seconds=900,
        required_stdout_text="WordPress content assembled successfully.",
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
    # Create WordPress draft directly after generation/repair.
    # Stabilization goal: skip intermediate website-draft review.
    # ------------------------------------------------------------
    step_name = "create_wordpress_draft_for_review"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "app/create_wordpress_draft.py",
            workspace_id,
            created_draft_id,
        ],
        step_name=step_name,
        timeout_seconds=900,
        required_stdout_text="WordPress draft created successfully.",
        fail_on_error=True,
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 9A: prepare image assets
    # ------------------------------------------------------------
    step_name = "prepare_draft_image_assets"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "-m",
            "app.image_assets.prepare_draft_image_assets",
            workspace_id,
            created_draft_id,
        ],
        step_name=step_name,
        timeout_seconds=600,
        fail_on_error=True,
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 9A1: create pending AI image generation jobs
    # ------------------------------------------------------------
    step_name = "generate_pending_images"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "-m",
            "app.image_assets.generate_pending_images",
            workspace_id,
            created_draft_id,
        ],
        step_name=step_name,
        timeout_seconds=300,
        fail_on_error=False,
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 9A2: execute pending AI image generation jobs
    # Image failures must not fail the whole content job.
    # ------------------------------------------------------------
    step_name = "process_ai_image_generation_jobs"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "-m",
            "app.image_assets.image_worker",
            workspace_id,
            "--draft-id",
            created_draft_id,
            "--execute",
        ],
        step_name=step_name,
        timeout_seconds=3600,
        fail_on_error=False,
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 9A3: refresh image asset preparation after AI generation
    # This lets newly registered generated images become uploadable assets.
    # ------------------------------------------------------------
    step_name = "refresh_draft_image_assets_after_ai_generation"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "-m",
            "app.image_assets.prepare_draft_image_assets",
            workspace_id,
            created_draft_id,
        ],
        step_name=step_name,
        timeout_seconds=600,
        fail_on_error=False,
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 9B: upload featured image to WordPress
    # ------------------------------------------------------------
    step_name = "upload_featured_image_to_wordpress"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "-m",
            "app.image_assets.upload_featured_image_to_wordpress",
            workspace_id,
            created_draft_id,
        ],
        step_name=step_name,
        timeout_seconds=600,
        required_stdout_text="Featured image uploaded and set successfully.",
        fail_on_error=True,
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 9C: upload in-article images
    # ------------------------------------------------------------
    step_name = "upload_in_article_images_to_wordpress"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "-m",
            "app.image_assets.upload_in_article_images_to_wordpress",
            workspace_id,
            created_draft_id,
        ],
        step_name=step_name,
        timeout_seconds=600,
        fail_on_error=False,
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 9D: insert in-article images into Gutenberg content
    # ------------------------------------------------------------
    step_name = "insert_in_article_images"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "-m",
            "app.image_assets.insert_in_article_images",
            workspace_id,
            created_draft_id,
        ],
        step_name=step_name,
        timeout_seconds=300,
        fail_on_error=False,
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 9E: update WordPress draft with inserted images
    # ------------------------------------------------------------
    step_name = "update_wordpress_draft_after_image_insertion"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "app/update_wordpress_draft.py",
            created_draft_id,
        ],
        step_name=step_name,
        timeout_seconds=900,
        fail_on_error=False,
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 10: real execution
    # Notify examiner only with WordPress-stage review link.
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
            created_draft_id,
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
        "message": "Approved opportunity converted to WordPress draft and sent for final examiner review.",
        "opportunity_id": opportunity_id,
        "simulated_remaining_steps": False,
        "completed_outputs": completed_outputs,
        "draft_id": created_draft_id,
        "wordpress_prepared": True,
        "wordpress_review_notification_sent": True,
        "intermediate_website_review_skipped": True,
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
    6. Validate again as warning, not blocker
    7. Update the existing WordPress draft
    8. Notify examiner with the WordPress review link
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
        required_stdout_text="AI draft revision completed successfully.",
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 2: real execution
    # Assemble revised WordPress-ready content first pass
    # ------------------------------------------------------------
    step_name = "assemble_revised_content_first_pass"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "app/assemble_wordpress_content.py",
            workspace_id,
            draft_id,
        ],
        step_name=step_name,
        timeout_seconds=900,
        required_stdout_text="WordPress content assembled successfully.",
        fail_on_error=True,
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
        # Assemble repaired revised WordPress-ready content
        # ------------------------------------------------------------
        step_name = "assemble_revised_content_second_pass"

        set_current_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

        output = run_pipeline_command(
            command=[
                sys.executable,
                "app/assemble_wordpress_content.py",
                workspace_id,
                draft_id,
            ],
            step_name=step_name,
            timeout_seconds=900,
            required_stdout_text="WordPress content assembled successfully.",
            fail_on_error=True,
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
            fail_on_error=False,
        )

        completed_outputs.append(output)

        if output.get("success") is True:
            print("Repaired revised draft passed validation.")
        else:
            print("Repaired revised draft still has validation warnings.")
            print("Revision will continue to WordPress update instead of failing the job.")

        complete_step(
            workspace_id=workspace_id,
            job_id=job_id,
            step_name=step_name,
        )

    # ------------------------------------------------------------
    # Step 7: real execution
    # Update existing WordPress draft after revision
    # ------------------------------------------------------------
    step_name = "update_wordpress_draft_after_revision"

    set_current_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    output = run_pipeline_command(
        command=[
            sys.executable,
            "app/update_wordpress_draft.py",
            draft_id,
        ],
        step_name=step_name,
        timeout_seconds=900,
        required_stdout_text="WordPress draft updated successfully.",
        fail_on_error=True,
    )

    completed_outputs.append(output)

    complete_step(
        workspace_id=workspace_id,
        job_id=job_id,
        step_name=step_name,
    )

    # ------------------------------------------------------------
    # Step 8: real execution
    # Notify examiner with WordPress review link after revision
    # ------------------------------------------------------------
    step_name = "notify_wordpress_review_after_revision"

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
        "message": "Revised draft updated in WordPress and sent back for examiner review.",
        "draft_id": draft_id,
        "revision_comment": revision_comment,
        "simulated_remaining_steps": False,
        "completed_outputs": completed_outputs,
        "review_notification_sent": True,
        "wordpress_updated": True,
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
            "app/create_wordpress_draft.py",
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

        temporary_timeout = is_timeout_failure(exc, error_details)
        current_attempts = int(job.get("attempts", 0))
        max_attempts = int(job.get("max_attempts", 1))

        if temporary_timeout and current_attempts < max_attempts:
            retry_job = mark_job_retry_pending(
                workspace_id=workspace_id,
                job_id=job_id,
                error_message=str(exc),
                error_details=error_details,
                retry_delay_seconds=300,
            )

            notified = notify_job_failure_to_telegram(
                workspace_id=workspace_id,
                job=retry_job,
                exc=exc,
                error_details=error_details,
            )

            if notified:
                print("Telegram retry notification sent.")
            else:
                print("Telegram retry notification not sent.")

            print("\nJob marked for retry.")
            print_job_summary(retry_job)
            print(f"\nTemporary error: {exc}")

            return retry_job

        failed_job = mark_job_failed(
            workspace_id=workspace_id,
            job_id=job_id,
            error_message=str(exc),
            error_details=error_details,
        )

        notified = notify_job_failure_to_telegram(
            workspace_id=workspace_id,
            job=failed_job,
            exc=exc,
            error_details=error_details,
        )

        if notified:
            print("Telegram failure notification sent.")
        else:
            print("Telegram failure notification not sent.")

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