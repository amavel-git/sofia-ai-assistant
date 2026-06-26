#!/usr/bin/env python3
"""
Optimize a generated AI master image.

Input:
- workspace_id
- image job_id

Output:
- optimized WebP variants
- image job updated to optimized
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


ROOT_DIR = Path(__file__).resolve().parents[2]

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


from app.image_assets.image_job_registry import find_image_job, update_image_job


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def resolve_path(path_value: str) -> Path:
    p = Path(path_value)
    if p.is_absolute():
        return p
    return ROOT_DIR / p


def resize_cover(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)

    new_w = int(src_w * scale)
    new_h = int(src_h * scale)

    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2

    return resized.crop((left, top, left + target_w, top + target_h))


def save_webp(img: Image.Image, output_path: Path, quality: int = 86):
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    img.save(output_path, "WEBP", quality=quality, method=6)

    return {
        "file": str(output_path.relative_to(ROOT_DIR)),
        "filename": output_path.name,
        "format": "webp",
        "width": img.width,
        "height": img.height,
        "size_kb": round(output_path.stat().st_size / 1024),
        "quality": quality,
    }


def optimize_master(master_file: Path, workspace_id: str, job_id: str):
    if not master_file.exists():
        raise RuntimeError(f"Master image not found: {master_file}")

    img = Image.open(master_file).convert("RGB")

    optimized_dir = master_file.parents[1] / "optimized"
    social_dir = master_file.parents[1] / "social"

    base = master_file.stem

    variants = {}

    variants["desktop"] = save_webp(
        resize_cover(img, 1600, 900),
        optimized_dir / f"{base}-1600.webp",
        quality=86,
    )

    variants["tablet"] = save_webp(
        resize_cover(img, 1200, 675),
        optimized_dir / f"{base}-1200.webp",
        quality=86,
    )

    variants["mobile"] = save_webp(
        resize_cover(img, 800, 450),
        optimized_dir / f"{base}-800.webp",
        quality=86,
    )

    variants["thumb"] = save_webp(
        resize_cover(img, 500, 500),
        optimized_dir / f"{base}-thumb.webp",
        quality=84,
    )

    variants["social"] = save_webp(
        resize_cover(img, 1200, 630),
        social_dir / f"{base}-social.webp",
        quality=88,
    )

    metadata = {
        "workspace_id": workspace_id,
        "image_job_id": job_id,
        "optimized_at": now_iso(),
        "master_file": str(master_file.relative_to(ROOT_DIR)),
        "variants": variants,
        "metadata_policy": {
            "title": "media title",
            "alt_text": "accessibility and SEO text",
            "description": "WordPress media description; not visible below image",
            "caption": "intentionally unused by default"
        }
    }

    metadata_path = optimized_dir / f"{base}.optimized.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    metadata["metadata_file"] = str(metadata_path.relative_to(ROOT_DIR))

    return metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace_id")
    parser.add_argument("job_id")
    args = parser.parse_args()

    job = find_image_job(args.workspace_id, args.job_id)

    if not job:
        raise SystemExit(f"Image job not found: {args.job_id}")

    master_file = resolve_path(job.get("master_file", ""))

    result = optimize_master(
        master_file=master_file,
        workspace_id=args.workspace_id,
        job_id=args.job_id,
    )

    update_image_job(
        args.workspace_id,
        args.job_id,
        {
            "status": "optimized",
            "optimized": True,
            "optimized_at": now_iso(),
            "optimized_result": result,
            "last_error": "",
        },
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
