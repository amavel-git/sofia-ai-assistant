#!/usr/bin/env python3
"""
Sofia image job registry helpers.

Workspace-aware JSON registry for AI image generation jobs.
No AI calls.
No WordPress calls.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


try:
    from app.workspace_paths import get_workspace_folder_path

except ModuleNotFoundError:

    import sys
    from pathlib import Path

    ROOT_DIR = Path(__file__).resolve().parents[2]

    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

    from app.workspace_paths import get_workspace_folder_path


VALID_STATUSES = {
    "pending_generation",
    "running",
    "generated_master",
    "optimized",
    "registered",
    "uploaded",
    "inserted",
    "awaiting_approval",
    "approved",
    "retry_pending",
    "failed_after_retries",
    "failed",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_image_job_registry_path(workspace_id: str) -> Path:
    return get_workspace_folder_path(workspace_id) / "image_job_registry.json"


def empty_registry(workspace_id: str) -> Dict[str, Any]:
    return {
        "version": "1.0",
        "workspace_id": workspace_id,
        "last_updated": None,
        "jobs": [],
    }


def load_image_job_registry(workspace_id: str) -> Dict[str, Any]:
    path = get_image_job_registry_path(workspace_id)

    if not path.exists():
        return empty_registry(workspace_id)

    data = json.loads(path.read_text(encoding="utf-8"))

    if "jobs" not in data or not isinstance(data["jobs"], list):
        data["jobs"] = []

    data.setdefault("version", "1.0")
    data.setdefault("workspace_id", workspace_id)
    data.setdefault("last_updated", None)

    return data


def save_image_job_registry(workspace_id: str, registry: Dict[str, Any]) -> None:
    path = get_image_job_registry_path(workspace_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    registry["workspace_id"] = workspace_id
    registry.setdefault("version", "1.0")
    registry.setdefault("jobs", [])
    registry["last_updated"] = now_iso()

    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")


def make_image_job_id() -> str:
    return f"IMGJOB-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


def find_image_job(workspace_id: str, job_id: str) -> Dict[str, Any] | None:
    registry = load_image_job_registry(workspace_id)

    for job in registry.get("jobs", []):
        if job.get("job_id") == job_id:
            return job

    return None


def find_existing_slot_job(
    workspace_id: str,
    draft_id: str,
    slot_id: str,
    active_only: bool = True,
) -> Dict[str, Any] | None:
    registry = load_image_job_registry(workspace_id)

    terminal = {"registered", "uploaded", "inserted", "approved", "failed_after_retries", "failed"}

    for job in registry.get("jobs", []):
        if job.get("draft_id") != draft_id:
            continue
        if job.get("slot_id") != slot_id:
            continue
        if active_only and job.get("status") in terminal:
            continue
        return job

    return None


def create_image_job(
    *,
    workspace_id: str,
    draft_id: str,
    slot_id: str,
    provider: str,
    model: str,
    prompt: str,
    master_file: str,
    negative_prompt: str = "",
    source_request: Dict[str, Any] | None = None,
    requires_examiner_approval: bool = True,
    status: str = "pending_generation",
) -> Dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid image job status: {status}")

    registry = load_image_job_registry(workspace_id)

    existing = find_existing_slot_job(
        workspace_id=workspace_id,
        draft_id=draft_id,
        slot_id=slot_id,
        active_only=True,
    )

    if existing:
        return existing

    job = {
        "job_id": make_image_job_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "workspace_id": workspace_id,
        "draft_id": draft_id,
        "slot_id": slot_id,
        "status": status,
        "provider": provider,
        "model": model,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "master_file": master_file,
        "optimized": False,
        "uploaded": False,
        "inserted": False,
        "approved": False,
        "requires_examiner_approval": requires_examiner_approval,
        "retry_count": 0,
        "max_retries": 2,
        "last_error": "",
        "source_request": source_request or {},
    }

    registry["jobs"].append(job)
    save_image_job_registry(workspace_id, registry)

    return job


def update_image_job(
    workspace_id: str,
    job_id: str,
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    registry = load_image_job_registry(workspace_id)

    for job in registry.get("jobs", []):
        if job.get("job_id") == job_id:
            job.update(updates)
            job["updated_at"] = now_iso()

            if "status" in updates and updates["status"] not in VALID_STATUSES:
                raise ValueError(f"Invalid image job status: {updates['status']}")

            save_image_job_registry(workspace_id, registry)
            return job

    raise RuntimeError(f"Image job not found: {job_id}")


def update_image_job_status(
    workspace_id: str,
    job_id: str,
    status: str,
    last_error: str = "",
) -> Dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid image job status: {status}")

    updates = {
        "status": status,
    }

    if last_error:
        updates["last_error"] = last_error

    return update_image_job(workspace_id, job_id, updates)


def find_pending_jobs(workspace_id: str) -> List[Dict[str, Any]]:
    registry = load_image_job_registry(workspace_id)

    return [
        job for job in registry.get("jobs", [])
        if job.get("status") in {"pending_generation", "retry_pending"}
    ]


def list_image_jobs(
    workspace_id: str,
    status: str | None = None,
) -> List[Dict[str, Any]]:
    registry = load_image_job_registry(workspace_id)
    jobs = registry.get("jobs", [])

    if status:
        jobs = [job for job in jobs if job.get("status") == status]

    return jobs


if __name__ == "__main__":
    import sys

    workspace_id = sys.argv[1] if len(sys.argv) > 1 else "local.es"
    print(json.dumps(load_image_job_registry(workspace_id), ensure_ascii=False, indent=2))
