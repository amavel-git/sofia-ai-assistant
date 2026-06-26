#!/usr/bin/env python3
"""
Sofia Image Worker

Processes pending AI image jobs:

pending_generation / retry_pending
→ execute Flux / ComfyUI
→ save master image
→ optimize variants
→ register generated image

AI image generation failures are handled safely:
- retry up to max_retries
- clear seed between attempts
- final failure does not fail the whole Sofia content job
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import traceback
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


from app.image_assets.image_job_registry import (
    find_pending_jobs,
    update_image_job,
    list_image_jobs,
)


def print_job(job):
    print("-" * 60)
    print(f"Job ID: {job.get('job_id')}")
    print(f"Workspace: {job.get('workspace_id')}")
    print(f"Draft: {job.get('draft_id')}")
    print(f"Slot: {job.get('slot_id')}")
    print(f"Status: {job.get('status')}")
    print(f"Provider: {job.get('provider')}")
    print(f"Model: {job.get('model')}")
    print(f"Retry: {job.get('retry_count', 0)} / {job.get('max_retries', 2)}")
    print(f"Master file: {job.get('master_file')}")


def run_module(module_name: str, workspace_id: str, job_id: str, timeout_seconds: int = 2400):
    command = [
        sys.executable,
        "-m",
        module_name,
        workspace_id,
        job_id,
    ]

    print("\nRunning:")
    print(" ".join(command))

    result = subprocess.run(
        command,
        cwd=str(ROOT_DIR),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )

    if result.stdout:
        print(result.stdout)

    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if result.returncode != 0:
        raise RuntimeError(
            f"{module_name} failed with exit code {result.returncode}"
        )

    return result.stdout


def mark_retry_or_failed(workspace_id, job_id, job, exc):
    retry_count = int(job.get("retry_count") or 0)
    max_retries = int(job.get("max_retries") or 2)

    error_text = f"{type(exc).__name__}: {exc}"

    updates = {
        "last_error": error_text,
        "traceback": traceback.format_exc(),
        "pipeline_completed": False,
    }

    if retry_count < max_retries:
        updates.update({
            "status": "pending_generation",
            "retry_count": retry_count + 1,
            "seed": None,
            "retry_reason": error_text,
        })

        updated = update_image_job(
            workspace_id=workspace_id,
            job_id=job_id,
            updates=updates,
        )

        print("\nImage job failed but will retry.")
        print_job(updated)
        return updated, True

    updates.update({
        "status": "failed",
        "failed_after_retries": True,
    })

    updated = update_image_job(
        workspace_id=workspace_id,
        job_id=job_id,
        updates=updates,
    )

    print("\nImage job failed after max retries.")
    print_job(updated)
    return updated, False


def process_image_job(job, execute=False):
    workspace_id = job["workspace_id"]
    job_id = job["job_id"]

    print("\nStarting image job:")
    print_job(job)

    if not execute:
        print("\nDry run only. Use --execute to run Flux generation.")
        return job

    attempts_remaining = int(job.get("max_retries") or 2) - int(job.get("retry_count") or 0) + 1
    attempts_remaining = max(attempts_remaining, 1)

    current_job = job

    for attempt in range(1, attempts_remaining + 1):
        try:
            print(f"\nImage generation attempt {attempt} of {attempts_remaining}")

            run_module(
                "app.image_assets.execute_flux_generation",
                workspace_id,
                job_id,
                timeout_seconds=2400,
            )

            run_module(
                "app.image_assets.optimize_generated_image",
                workspace_id,
                job_id,
                timeout_seconds=900,
            )

            run_module(
                "app.image_assets.register_optimized_generated_image",
                workspace_id,
                job_id,
                timeout_seconds=300,
            )

            update_image_job(
                workspace_id=workspace_id,
                job_id=job_id,
                updates={
                    "last_error": "",
                    "pipeline_completed": True,
                    "failed_after_retries": False,
                },
            )

            print("\nImage job completed.")
            return current_job

        except Exception as exc:
            current_job, should_retry = mark_retry_or_failed(
                workspace_id=workspace_id,
                job_id=job_id,
                job=current_job,
                exc=exc,
            )

            if not should_retry:
                return current_job

    return current_job


def process_pending_image_jobs(workspace_id, draft_id=None, execute=False, limit=None):
    jobs = find_pending_jobs(workspace_id)

    if draft_id:
        jobs = [job for job in jobs if job.get("draft_id") == draft_id]

    if not jobs:
        print(f"No pending image jobs found for workspace: {workspace_id}")
        if draft_id:
            print(f"Draft filter: {draft_id}")
        return []

    if limit:
        jobs = jobs[:limit]

    processed = []

    for job in jobs:
        processed.append(
            process_image_job(
                job,
                execute=execute,
            )
        )

    print(f"\nProcessed image jobs: {len(processed)}")
    return processed


def show_jobs(workspace_id, status=None, draft_id=None):
    jobs = list_image_jobs(workspace_id, status=status)

    if draft_id:
        jobs = [job for job in jobs if job.get("draft_id") == draft_id]

    if not jobs:
        print(f"No image jobs found for workspace: {workspace_id}")
        return

    for job in jobs:
        print_job(job)


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Sofia image generation worker"
    )

    parser.add_argument("workspace_id")

    parser.add_argument(
        "--draft-id",
        default=None,
        help="Optional draft id filter, e.g. DRAFT-0003.",
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List image jobs instead of processing.",
    )

    parser.add_argument(
        "--status",
        default=None,
        help="Optional status filter for --list.",
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute Flux generation, optimization and registration.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of jobs to process.",
    )

    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.list:
        show_jobs(
            workspace_id=args.workspace_id,
            status=args.status,
            draft_id=args.draft_id,
        )
        return

    process_pending_image_jobs(
        workspace_id=args.workspace_id,
        draft_id=args.draft_id,
        execute=args.execute,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
