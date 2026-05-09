#!/usr/bin/env python3
"""
Sofia Job Queue Helper

Purpose:
- Store long-running Sofia tasks in a workspace-level job registry.
- Avoid blocking telegram_listener.py during AI generation, repair, validation,
  WordPress upload, or other slow operations.
- Keep job state local to each workspace.

Example workspace registry:
    sites/local_sites/ao/job_registry.json

Initial supported job type:
    approved_opportunity_to_review_draft

This helper does not execute jobs.
Execution will be handled later by app/sofia_worker.py.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
SITES_DIR = ROOT_DIR / "sites"
WORKSPACES_FILE = ROOT_DIR / "data" / "workspaces.json"

SUPPORTED_JOB_TYPES = {
    "approved_opportunity_to_review_draft",
    "revise_draft",
    "approved_draft_to_wordpress_review",
}

TERMINAL_STATUSES = {
    "completed",
    "failed",
    "cancelled",
}

ACTIVE_STATUSES = {
    "queued",
    "running",
}


def utc_now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    """Load JSON safely. Return default if file does not exist."""
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    """Save JSON with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_workspaces() -> Dict[str, Any]:
    """Load Sofia workspaces configuration."""
    if not WORKSPACES_FILE.exists():
        raise FileNotFoundError(f"Missing workspaces file: {WORKSPACES_FILE}")

    data = load_json(WORKSPACES_FILE, {})

    if isinstance(data, dict):
        return data

    raise ValueError("data/workspaces.json must contain a JSON object.")


def get_workspace_config(workspace_id: str) -> Dict[str, Any]:
    """
    Return workspace config for a workspace_id.

    Expected workspace_id example:
        local.ao

    This function is intentionally flexible because earlier Sofia phases may
    have used slightly different workspaces.json structures.
    """

    data = load_workspaces()

    # Common structure:
    # {
    #   "workspaces": [
    #       {"workspace_id": "local.ao", "workspace_path": "sites/local_sites/ao"}
    #   ]
    # }
    if isinstance(data.get("workspaces"), list):
        for workspace in data["workspaces"]:
            if workspace.get("workspace_id") == workspace_id:
                return workspace

    # Alternative structure:
    # {
    #   "local.ao": {...}
    # }
    if workspace_id in data and isinstance(data[workspace_id], dict):
        return data[workspace_id]

    raise ValueError(f"Workspace not found in data/workspaces.json: {workspace_id}")


def get_workspace_path(workspace_id: str) -> Path:
    """
    Resolve the filesystem path for a workspace.

    Preferred:
        workspace_path inside data/workspaces.json

    Fallback:
        local.xx -> sites/local_sites/xx
    """

    workspace = get_workspace_config(workspace_id)

    path_value = (
        workspace.get("workspace_path")
        or workspace.get("path")
        or workspace.get("site_path")
    )

    if path_value:
        path = Path(path_value)
        if not path.is_absolute():
            path = ROOT_DIR / path
        return path

    # Safe fallback for local country workspaces
    if workspace_id.startswith("local."):
        country_code = workspace_id.split(".", 1)[1]
        return SITES_DIR / "local_sites" / country_code

    raise ValueError(
        f"Could not resolve workspace path for {workspace_id}. "
        "Add workspace_path to data/workspaces.json."
    )


def get_job_registry_path(workspace_id: str) -> Path:
    """Return the workspace-level job registry path."""
    return get_workspace_path(workspace_id) / "job_registry.json"


def empty_registry(workspace_id: str) -> Dict[str, Any]:
    """Create an empty job registry structure."""
    return {
        "version": "1.0",
        "workspace_id": workspace_id,
        "last_updated": None,
        "jobs": [],
    }


def load_job_registry(workspace_id: str) -> Dict[str, Any]:
    """
    Load a workspace-level job registry.

    If the registry does not exist yet, return a valid empty registry.
    """

    path = get_job_registry_path(workspace_id)
    registry = load_json(path, empty_registry(workspace_id))

    if not isinstance(registry, dict):
        raise ValueError(f"Invalid job registry format: {path}")

    if "jobs" not in registry:
        registry["jobs"] = []

    if not isinstance(registry["jobs"], list):
        raise ValueError(f"job_registry.json field 'jobs' must be a list: {path}")

    registry.setdefault("version", "1.0")
    registry.setdefault("workspace_id", workspace_id)
    registry.setdefault("last_updated", None)

    return registry


def save_job_registry(workspace_id: str, registry: Dict[str, Any]) -> None:
    """Save a workspace-level job registry."""
    registry["workspace_id"] = workspace_id
    registry["last_updated"] = utc_now_iso()

    path = get_job_registry_path(workspace_id)
    save_json(path, registry)


def generate_job_id(job_type: str) -> str:
    """
    Generate a readable job id.

    Examples:
        JOB-OPP2DRAFT-20260506-8F3A2C
        JOB-REVISE-20260506-8F3A2C
    """

    short_uuid = uuid.uuid4().hex[:6].upper()
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")

    if job_type == "approved_opportunity_to_review_draft":
        prefix = "JOB-OPP2DRAFT"

    elif job_type == "revise_draft":
        prefix = "JOB-REVISE"

    elif job_type == "approved_draft_to_wordpress_review":
        prefix = "JOB-WP-DRAFT"

    else:
        prefix = "JOB"

    return f"{prefix}-{date_part}-{short_uuid}"


def find_job(registry: Dict[str, Any], job_id: str) -> Optional[Dict[str, Any]]:
    """Find a job by job_id."""
    for job in registry.get("jobs", []):
        if job.get("job_id") == job_id:
            return job
    return None


def has_active_job_for_item(
    workspace_id: str,
    job_type: str,
    item_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Check whether an active queued/running job already exists for the same item.

    This prevents duplicate Telegram clicks from creating duplicate background jobs.
    """

    registry = load_job_registry(workspace_id)

    for job in registry.get("jobs", []):
        if (
            job.get("job_type") == job_type
            and job.get("item_id") == item_id
            and job.get("status") in ACTIVE_STATUSES
        ):
            return job

    return None


def create_job(
    workspace_id: str,
    job_type: str,
    item_id: str,
    payload: Optional[Dict[str, Any]] = None,
    created_by: str = "system",
    source: str = "manual",
) -> Dict[str, Any]:
    """
    Create a queued job in the workspace-level registry.

    Args:
        workspace_id:
            Sofia workspace id, e.g. local.ao

        job_type:
            Type of background job.

        item_id:
            Primary object being processed.
            For the first job type, this should be the opportunity id,
            e.g. OPP-AO-001.

        payload:
            Extra data needed by the worker.

        created_by:
            Who or what created the job.
            Examples: telegram_listener, process_examiner_decision, manual

        source:
            Source channel or trigger.
            Examples: telegram, cli, internal

    Returns:
        The created job object.
    """

    if job_type not in SUPPORTED_JOB_TYPES:
        raise ValueError(f"Unsupported job type: {job_type}")

    existing_job = has_active_job_for_item(
        workspace_id=workspace_id,
        job_type=job_type,
        item_id=item_id,
    )

    if existing_job:
        return existing_job

    registry = load_job_registry(workspace_id)

    now = utc_now_iso()

    job = {
        "job_id": generate_job_id(job_type),
        "workspace_id": workspace_id,
        "job_type": job_type,
        "item_id": item_id,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
        "created_by": created_by,
        "source": source,
        "payload": payload or {},
        "attempts": 0,
        "max_attempts": 1,
        "current_step": None,
        "steps_completed": [],
        "result": None,
        "error": None,
        "telegram": {
            "ack_sent": False,
            "completion_sent": False,
            "failure_sent": False,
            "chat_id": None,
            "message_id": None
        },
    }

    registry["jobs"].append(job)
    save_job_registry(workspace_id, registry)

    return job


def update_job(
    workspace_id: str,
    job_id: str,
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Update a job by job_id.

    Returns the updated job.
    """

    registry = load_job_registry(workspace_id)
    job = find_job(registry, job_id)

    if not job:
        raise ValueError(f"Job not found: {job_id}")

    for key, value in updates.items():
        job[key] = value

    job["updated_at"] = utc_now_iso()

    save_job_registry(workspace_id, registry)
    return job


def mark_job_running(workspace_id: str, job_id: str, current_step: Optional[str] = None) -> Dict[str, Any]:
    """Mark a queued job as running."""
    registry = load_job_registry(workspace_id)
    job = find_job(registry, job_id)

    if not job:
        raise ValueError(f"Job not found: {job_id}")

    now = utc_now_iso()

    job["status"] = "running"
    job["started_at"] = job.get("started_at") or now
    job["updated_at"] = now
    job["attempts"] = int(job.get("attempts", 0)) + 1

    if current_step:
        job["current_step"] = current_step

    save_job_registry(workspace_id, registry)
    return job


def mark_step_completed(workspace_id: str, job_id: str, step_name: str) -> Dict[str, Any]:
    """Add a completed step to a running job."""
    registry = load_job_registry(workspace_id)
    job = find_job(registry, job_id)

    if not job:
        raise ValueError(f"Job not found: {job_id}")

    steps = job.setdefault("steps_completed", [])

    if step_name not in steps:
        steps.append(step_name)

    job["current_step"] = None
    job["updated_at"] = utc_now_iso()

    save_job_registry(workspace_id, registry)
    return job


def mark_job_completed(
    workspace_id: str,
    job_id: str,
    result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Mark a job as completed."""
    return update_job(
        workspace_id,
        job_id,
        {
            "status": "completed",
            "completed_at": utc_now_iso(),
            "current_step": None,
            "result": result or {},
            "error": None,
        },
    )


def mark_job_failed(
    workspace_id: str,
    job_id: str,
    error_message: str,
    error_details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Mark a job as failed.

    Important:
    This only stores the internal error.
    It does not send Telegram messages.
    """

    return update_job(
        workspace_id,
        job_id,
        {
            "status": "failed",
            "completed_at": utc_now_iso(),
            "current_step": None,
            "error": {
                "message": error_message,
                "details": error_details or {},
                "recorded_at": utc_now_iso(),
            },
        },
    )


def get_next_queued_job(
    workspace_id: str,
    job_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Return the oldest queued job for a workspace.

    The future worker will use this.
    """

    registry = load_job_registry(workspace_id)

    queued_jobs: List[Dict[str, Any]] = []

    for job in registry.get("jobs", []):
        if job.get("status") != "queued":
            continue

        if job_type and job.get("job_type") != job_type:
            continue

        queued_jobs.append(job)

    if not queued_jobs:
        return None

    queued_jobs.sort(key=lambda job: job.get("created_at") or "")
    return queued_jobs[0]


def list_jobs(
    workspace_id: str,
    status: Optional[str] = None,
    job_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List jobs for a workspace, optionally filtered by status and job type."""
    registry = load_job_registry(workspace_id)

    jobs = registry.get("jobs", [])

    if status:
        jobs = [job for job in jobs if job.get("status") == status]

    if job_type:
        jobs = [job for job in jobs if job.get("job_type") == job_type]

    return jobs


def print_job_summary(job: Dict[str, Any]) -> None:
    """Print a short CLI-friendly job summary."""
    print(f"Job ID: {job.get('job_id')}")
    print(f"Workspace: {job.get('workspace_id')}")
    print(f"Type: {job.get('job_type')}")
    print(f"Item: {job.get('item_id')}")
    print(f"Status: {job.get('status')}")
    print(f"Created: {job.get('created_at')}")
    print(f"Current step: {job.get('current_step')}")