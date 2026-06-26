#!/usr/bin/env python3
"""
Register an optimized generated image in workspace image_metadata.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


from app.image_assets.image_job_registry import find_image_job, update_image_job
from app.image_assets.image_asset_registry import register_image_asset


def pick_variant(variants: dict, key: str) -> str:
    item = variants.get(key) or {}
    return item.get("file", "")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace_id")
    parser.add_argument("job_id")
    args = parser.parse_args()

    job = find_image_job(args.workspace_id, args.job_id)

    if not job:
        raise SystemExit(f"Image job not found: {args.job_id}")

    optimized = job.get("optimized_result") or {}
    variants = optimized.get("variants") or {}

    draft_id = job.get("draft_id", "")
    slot_id = job.get("slot_id", "")

    source_request = job.get("source_request") or {}
    source_slot = source_request.get("source_slot") or {}

    title = (
        source_slot.get("title")
        or source_slot.get("topic")
        or job.get("draft_id")
        or ""
    )

    alt_text = (
        source_slot.get("alt_text")
        or f"Imagen profesional generada para {title}".strip()
    )

    description = (
        source_slot.get("description")
        or source_slot.get("caption")
        or "Imagen profesional utilizada como apoyo visual para una consulta y evaluación poligráfica en España."
    )

    filename = (
        Path(pick_variant(variants, "desktop")).name
        or Path(job.get("master_file", "")).with_suffix(".webp").name
    )

    record = register_image_asset(
        workspace_id=args.workspace_id,
        draft_id=draft_id,
        slot_id=slot_id,
        title=title,
        alt_text=alt_text,
        description=description,
        filename=filename,
        master_png=optimized.get("master_file") or job.get("master_file", ""),
        desktop_webp=pick_variant(variants, "desktop"),
        tablet_webp=pick_variant(variants, "tablet"),
        mobile_webp=pick_variant(variants, "mobile"),
        thumb_webp=pick_variant(variants, "thumb"),
        social_webp=pick_variant(variants, "social"),
        provider=job.get("provider", "local_flux"),
        model=job.get("model", "Flux2Klein"),
        seed=job.get("seed"),
        generation_prompt=job.get("prompt", ""),
        status="optimized",
        source_type="ai_generated",
        image_job_id=args.job_id,
        extra={
            "optimized_result": optimized,
            "metadata_source": "image_job_registry",
        },
    )

    update_image_job(
        args.workspace_id,
        args.job_id,
        {
            "registered_image_id": record["image_id"],
            "registered_at": record["updated_at"],
            "status": "registered",
            "last_error": "",
        },
    )

    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
