#!/usr/bin/env python3
"""
ComfyUI API client for Sofia.

No workflow-specific logic here.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict

import requests

from app.image_assets.comfyui_service import start_comfyui_if_needed


def get_comfyui_url() -> str:
    return start_comfyui_if_needed().rstrip("/")


def get_system_stats(url: str | None = None) -> Dict[str, Any]:
    url = (url or get_comfyui_url()).rstrip("/")
    r = requests.get(f"{url}/system_stats", timeout=20)
    r.raise_for_status()
    return r.json()


def queue_prompt(prompt_workflow: Dict[str, Any], url: str | None = None) -> Dict[str, Any]:
    url = (url or get_comfyui_url()).rstrip("/")
    client_id = str(uuid.uuid4())

    payload = {
        "prompt": prompt_workflow,
        "client_id": client_id,
    }

    r = requests.post(f"{url}/prompt", json=payload, timeout=60)
    r.raise_for_status()

    data = r.json()
    data["client_id"] = client_id
    return data


def get_history(prompt_id: str, url: str | None = None) -> Dict[str, Any]:
    url = (url or get_comfyui_url()).rstrip("/")
    r = requests.get(f"{url}/history/{prompt_id}", timeout=30)
    r.raise_for_status()
    return r.json()


def wait_for_prompt(prompt_id: str, url: str | None = None, timeout_seconds: int = 900) -> Dict[str, Any]:
    url = (url or get_comfyui_url()).rstrip("/")
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        history = get_history(prompt_id, url=url)

        if prompt_id in history:
            return history[prompt_id]

        time.sleep(2)

    raise TimeoutError(f"ComfyUI prompt did not finish in {timeout_seconds} seconds: {prompt_id}")


def download_image(
    *,
    filename: str,
    subfolder: str = "",
    image_type: str = "output",
    output_path: str | Path,
    url: str | None = None,
) -> Path:
    url = (url or get_comfyui_url()).rstrip("/")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    params = {
        "filename": filename,
        "subfolder": subfolder,
        "type": image_type,
    }

    r = requests.get(f"{url}/view", params=params, timeout=120)
    r.raise_for_status()

    output_path.write_bytes(r.content)
    return output_path


def extract_output_images(history_item: Dict[str, Any]) -> list[Dict[str, Any]]:
    images = []

    outputs = history_item.get("outputs") or {}

    for node_id, node_output in outputs.items():
        for image in node_output.get("images", []) or []:
            images.append({
                "node_id": node_id,
                "filename": image.get("filename", ""),
                "subfolder": image.get("subfolder", ""),
                "type": image.get("type", "output"),
            })

    return images


if __name__ == "__main__":
    url = get_comfyui_url()
    print(json.dumps({
        "url": url,
        "system_stats": get_system_stats(url),
    }, ensure_ascii=False, indent=2)[:3000])
