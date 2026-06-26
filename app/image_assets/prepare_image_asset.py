#!/usr/bin/env python3
"""
Sofia Image Asset Preparation Pipeline

Runs:
1. Website optimization
2. Social variants
3. Combined metadata generation
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    from app.image_assets.image_optimizer import optimize_image_variants
    from app.image_assets.image_social_variants import create_social_variants
except ModuleNotFoundError:
    from image_optimizer import optimize_image_variants
    from image_social_variants import create_social_variants


def prepare_image_asset(
    workspace_id: str,
    source_path: str,
    recommended_filename: str
):
    workspace_suffix = workspace_id.split(".")[-1]

    optimized_output_dir = (
        Path("sites")
        / "local_sites"
        / workspace_suffix
        / "assets"
        / "images"
        / "optimized"
    )

    optimized_result = optimize_image_variants(
        source_path=source_path,
        recommended_filename=recommended_filename,
        profile_name="featured_image",
        output_dir=optimized_output_dir
    )

    social_result = create_social_variants(
        workspace_id=workspace_id,
        source_path=source_path,
        recommended_filename=Path(recommended_filename).with_suffix(".jpg").name
    )

    combined = {
        "workspace_id": workspace_id,
        "source_path": source_path,
        "recommended_filename": recommended_filename,
        "optimized": optimized_result,
        "social": social_result
    }

    workspace_suffix = workspace_id.split(".")[-1]

    metadata_path = (
        Path("sites")
        / "local_sites"
        / workspace_suffix
        / "assets"
        / "images"
        / "generated"
        / f"{Path(recommended_filename).stem}.json"
    )

    metadata_path.parent.mkdir(parents=True, exist_ok=True)

    with metadata_path.open("w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    combined["metadata_file"] = str(metadata_path)

    return combined


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 4:
        print("Usage:")
        print(
            "python -m app.image_assets.prepare_image_asset "
            "WORKSPACE_ID SOURCE_IMAGE recommended-filename.webp"
        )
        raise SystemExit(1)

    result = prepare_image_asset(
        workspace_id=sys.argv[1],
        source_path=sys.argv[2],
        recommended_filename=sys.argv[3]
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
