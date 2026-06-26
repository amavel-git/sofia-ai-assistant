#!/usr/bin/env python3
"""
ComfyUI service helper for Sofia.

Responsibilities:
- Check whether ComfyUI is reachable.
- Start ComfyUI automatically if needed.
- Wait until API is ready.

No image generation logic here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import requests


ROOT_DIR = Path(__file__).resolve().parents[2]

COMFYUI_BASE_DIR = Path(
    os.getenv("SOFIA_COMFYUI_BASE_DIR", "/mnt/c/AI/image/ComfyUI")
)

COMFYUI_ROOT = Path(
    os.getenv("SOFIA_COMFYUI_ROOT", str(COMFYUI_BASE_DIR / "ComfyUI"))
)

COMFYUI_PYTHON = Path(
    os.getenv("SOFIA_COMFYUI_PYTHON", str(COMFYUI_BASE_DIR / "python_embeded" / "python.exe"))
)

COMFYUI_MAIN = Path(
    os.getenv("SOFIA_COMFYUI_MAIN", str(COMFYUI_ROOT / "main.py"))
)

COMFYUI_PORT = int(os.getenv("SOFIA_COMFYUI_PORT", "8188"))
COMFYUI_LISTEN = os.getenv("SOFIA_COMFYUI_LISTEN", "0.0.0.0")
COMFYUI_EXTRA_ARGS = os.getenv("SOFIA_COMFYUI_EXTRA_ARGS", "--lowvram").split()

# From WSL, localhost may not reach Windows python.exe processes.
# We test several likely addresses.
DEFAULT_URLS = [
    f"http://127.0.0.1:{COMFYUI_PORT}",
]


def _run_text(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return (completed.stdout or "").strip()
    except Exception:
        return ""



def to_windows_path(path: Path) -> str:
    """
    Convert WSL /mnt/c/... paths to Windows paths for python.exe.
    """
    converted = _run_text(["wslpath", "-w", str(path)])
    return converted or str(path)


def get_windows_gateway_ip() -> str:
    output = _run_text(["bash", "-lc", "ip route | awk '/default/ {print $3; exit}'"])
    return output.strip()


def get_candidate_urls() -> list[str]:
    urls = list(DEFAULT_URLS)

    env_url = os.getenv("SOFIA_COMFYUI_URL", "").strip()
    if env_url:
        urls.insert(0, env_url.rstrip("/"))

    gateway = get_windows_gateway_ip()
    if gateway:
        urls.append(f"http://{gateway}:{COMFYUI_PORT}")

    # Remove duplicates while preserving order.
    deduped = []
    seen = set()
    for url in urls:
        if url and url not in seen:
            deduped.append(url.rstrip("/"))
            seen.add(url)

    return deduped


def is_comfyui_running(url: str, timeout: int = 3) -> bool:
    try:
        response = requests.get(
            f"{url.rstrip('/')}/system_stats",
            timeout=timeout,
        )
        return response.status_code == 200
    except Exception:
        return False


def find_running_comfyui_url() -> Optional[str]:
    for url in get_candidate_urls():
        if is_comfyui_running(url):
            return url
    return None


def validate_paths() -> None:
    missing = []

    if not COMFYUI_PYTHON.exists():
        missing.append(f"COMFYUI_PYTHON not found: {COMFYUI_PYTHON}")

    if not COMFYUI_MAIN.exists():
        missing.append(f"COMFYUI_MAIN not found: {COMFYUI_MAIN}")

    if not COMFYUI_ROOT.exists():
        missing.append(f"COMFYUI_ROOT not found: {COMFYUI_ROOT}")

    if missing:
        raise RuntimeError("\\n".join(missing))


def start_comfyui_background() -> subprocess.Popen:
    validate_paths()

    command = [
        str(COMFYUI_PYTHON),
        to_windows_path(COMFYUI_MAIN),
        "--listen",
        COMFYUI_LISTEN,
        "--port",
        str(COMFYUI_PORT),
        *COMFYUI_EXTRA_ARGS,
    ]

    log_dir = ROOT_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "comfyui_service.log"

    log_handle = log_file.open("a", encoding="utf-8")

    process = subprocess.Popen(
        command,
        cwd=str(COMFYUI_ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    return process


def wait_for_comfyui(timeout_seconds: int = 120) -> str:
    deadline = time.time() + timeout_seconds
    last_urls = []

    while time.time() < deadline:
        urls = get_candidate_urls()
        last_urls = urls

        for url in urls:
            if is_comfyui_running(url):
                return url

        time.sleep(2)

    raise TimeoutError(
        "ComfyUI did not become reachable. Tried: "
        + ", ".join(last_urls)
    )


def start_comfyui_if_needed(timeout_seconds: int = 120) -> str:
    running_url = find_running_comfyui_url()

    if running_url:
        return running_url

    start_comfyui_background()

    return wait_for_comfyui(timeout_seconds=timeout_seconds)


def main() -> None:
    if "--start" in sys.argv:
        url = start_comfyui_if_needed()
        print(json.dumps({
            "running": True,
            "url": url,
            "started_if_needed": True,
        }, ensure_ascii=False, indent=2))
        return

    url = find_running_comfyui_url()
    print(json.dumps({
        "running": bool(url),
        "url": url,
        "candidate_urls": get_candidate_urls(),
        "python": str(COMFYUI_PYTHON),
        "main": str(COMFYUI_MAIN),
        "root": str(COMFYUI_ROOT),
        "listen": COMFYUI_LISTEN,
        "port": COMFYUI_PORT,
        "extra_args": COMFYUI_EXTRA_ARGS,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
