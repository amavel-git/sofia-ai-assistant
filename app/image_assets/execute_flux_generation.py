#!/usr/bin/env python3
"""
Execute a Sofia AI image generation job through local ComfyUI / Flux2Klein.

Input:
- workspace_id
- image job_id

Output:
- generated master PNG saved into the job's master_file path
- image job updated to generated_master
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


from app.image_assets.comfyui_client import (
    queue_prompt,
    wait_for_prompt,
    extract_output_images,
    download_image,
)
from app.image_assets.image_job_registry import (
    find_image_job,
    find_pending_jobs,
    update_image_job,
)


WORKFLOW_PATH = ROOT_DIR / "data" / "image_assets" / "comfyui_workflows" / "flux2_klein_text_to_image_api.json"

DEFAULT_NEGATIVE_PROMPT = (
    "cartoon, illustration, anime, blurry, low quality, watermark, logo, text overlay, "
    "extra fingers, duplicate hands, duplicate person, deformed face, unrealistic office, "
    "police interrogation, handcuffs, badge, aggressive scene"
)


def safe_filename_prefix(value: str) -> str:
    value = value or "Sofia_Flux2Klein"
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value[:80] or "Sofia_Flux2Klein"


def resolve_path(path_value: str) -> Path:
    p = Path(path_value)
    if p.is_absolute():
        return p
    return ROOT_DIR / p


def load_workflow() -> dict[str, Any]:
    if not WORKFLOW_PATH.exists():
        raise RuntimeError(f"Workflow not found: {WORKFLOW_PATH}")

    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def replace_placeholders(value: Any, replacements: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)

    if isinstance(value, list):
        return [replace_placeholders(v, replacements) for v in value]

    if isinstance(value, dict):
        return {
            k: replace_placeholders(v, replacements)
            for k, v in value.items()
        }

    return value


def build_runtime_workflow(job: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    workflow = load_workflow()

    prompt = job.get("prompt", "").strip()
    if not prompt:
        raise RuntimeError("Image job has no prompt.")

    negative_prompt = (
        job.get("negative_prompt")
        or DEFAULT_NEGATIVE_PROMPT
    )

    # Keep seed in a conservative 32-bit range for Windows/Comfy compatibility.
    seed = job.get("seed") or random.randint(1, 2147483647)
    width = int(job.get("width") or 1600)
    height = int(job.get("height") or 900)

    filename_prefix = safe_filename_prefix(
        f"Sofia_{job.get('workspace_id', 'workspace')}_{job.get('draft_id', 'draft')}_{job.get('slot_id', 'image')}"
    )

    replacements = {
        "__PROMPT__": prompt,
        "__NEGATIVE_PROMPT__": negative_prompt,
        "__SEED__": seed,
        "__WIDTH__": width,
        "__HEIGHT__": height,
        "__FILENAME_PREFIX__": filename_prefix,
    }

    runtime_workflow = replace_placeholders(workflow, replacements)

    metadata = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "seed": seed,
        "width": width,
        "height": height,
        "filename_prefix": filename_prefix,
    }

    return runtime_workflow, metadata


def status_has_error(history_item: dict[str, Any]) -> str:
    status = history_item.get("status") or {}
    if status.get("status_str") == "error":
        messages = status.get("messages") or []
        return json.dumps(messages, ensure_ascii=False, indent=2)[:4000]
    return ""


def execute_job(workspace_id: str, job_id: str) -> dict[str, Any]:
    job = find_image_job(workspace_id, job_id)

    if not job:
        raise RuntimeError(f"Image job not found: {job_id}")

    update_image_job(
        workspace_id,
        job_id,
        {
            "status": "running",
            "last_error": "",
        },
    )

    runtime_workflow, metadata = build_runtime_workflow(job)

    master_file = resolve_path(job.get("master_file", ""))
    master_file.parent.mkdir(parents=True, exist_ok=True)

    sidecar = master_file.with_suffix(".generation.json")
    sidecar.write_text(
        json.dumps(
            {
                "workspace_id": workspace_id,
                "job_id": job_id,
                "draft_id": job.get("draft_id"),
                "slot_id": job.get("slot_id"),
                "workflow": str(WORKFLOW_PATH.relative_to(ROOT_DIR)),
                "metadata": metadata,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    queued = queue_prompt(runtime_workflow)
    prompt_id = queued.get("prompt_id")

    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return prompt_id: {queued}")

    history_item = wait_for_prompt(
        prompt_id,
        timeout_seconds=1800,
    )

    error_text = status_has_error(history_item)
    if error_text:
        update_image_job(
            workspace_id,
            job_id,
            {
                "status": "failed",
                "last_error": error_text,
                "comfyui_prompt_id": prompt_id,
            },
        )
        raise RuntimeError(f"ComfyUI generation failed: {error_text}")

    images = extract_output_images(history_item)

    if not images:
        update_image_job(
            workspace_id,
            job_id,
            {
                "status": "failed",
                "last_error": "ComfyUI finished but returned no output images.",
                "comfyui_prompt_id": prompt_id,
            },
        )
        raise RuntimeError("ComfyUI finished but returned no output images.")

    image = images[0]

    download_image(
        filename=image["filename"],
        subfolder=image.get("subfolder", ""),
        image_type=image.get("type", "output"),
        output_path=master_file,
    )

    result = {
        "success": True,
        "workspace_id": workspace_id,
        "job_id": job_id,
        "draft_id": job.get("draft_id"),
        "slot_id": job.get("slot_id"),
        "status": "generated_master",
        "comfyui_prompt_id": prompt_id,
        "seed": metadata["seed"],
        "width": metadata["width"],
        "height": metadata["height"],
        "master_file": str(master_file.relative_to(ROOT_DIR)),
        "source_image": image,
        "sidecar": str(sidecar.relative_to(ROOT_DIR)),
    }

    update_image_job(
        workspace_id,
        job_id,
        {
            "status": "generated_master",
            "comfyui_prompt_id": prompt_id,
            "seed": metadata["seed"],
            "width": metadata["width"],
            "height": metadata["height"],
            "master_file": result["master_file"],
            "generated_master": True,
            "generated_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
            "generation_result": result,
            "last_error": "",
        },
    )

    return result


def get_job_id(workspace_id: str, job_id: str | None) -> str:
    if job_id:
        return job_id

    pending = find_pending_jobs(workspace_id)
    if not pending:
        raise RuntimeError(f"No pending image jobs found for workspace: {workspace_id}")

    return pending[0]["job_id"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute a Sofia Flux2Klein image generation job."
    )
    parser.add_argument("workspace_id")
    parser.add_argument("job_id", nargs="?")
    args = parser.parse_args()

    job_id = get_job_id(args.workspace_id, args.job_id)
    result = execute_job(args.workspace_id, job_id)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
