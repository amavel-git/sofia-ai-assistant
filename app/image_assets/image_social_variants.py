#!/usr/bin/env python3
"""
Sofia Image Social Variants

Creates platform-specific image variants from a source image.

Outputs to:
sites/local_sites/<workspace>/assets/images/social/
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image

try:
    from app.image_assets.image_optimizer import (
        ROOT_DIR,
        ensure_dir,
        load_json,
        resize_cover,
        save_optimized,
        normalize_format,
        workspace_path_from_id,
    )
except ModuleNotFoundError:
    from image_optimizer import (
        ROOT_DIR,
        ensure_dir,
        load_json,
        resize_cover,
        save_optimized,
        normalize_format,
        workspace_path_from_id,
    )


SOCIAL_PROFILES_PATH = ROOT_DIR / "data" / "image_assets" / "social_image_profiles.json"


def get_workspace_social_dir(workspace_id: str) -> Path:
    return workspace_path_from_id(workspace_id) / "assets" / "images" / "social"


def load_social_profiles() -> Dict[str, Any]:
    return load_json(SOCIAL_PROFILES_PATH, {})


def build_social_filename(base_filename: str, profile_name: str, fmt: str) -> str:
    base = Path(base_filename).stem
    fmt = normalize_format(fmt)
    return f"{base}-{profile_name}.{fmt}"


def save_social_metadata(result: Dict[str, Any], output_dir: Path) -> Path:
    metadata_path = output_dir / f"{Path(result['recommended_filename']).stem}-social.json"

    ensure_dir(metadata_path.parent)

    with metadata_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return metadata_path


def create_social_variants(
    workspace_id: str,
    source_path: str | Path,
    recommended_filename: str,
    output_dir: Optional[str | Path] = None,
) -> Dict[str, Any]:
    source_path = Path(source_path)

    if not source_path.exists():
        raise FileNotFoundError(f"Source image not found: {source_path}")

    output_dir = Path(output_dir) if output_dir else get_workspace_social_dir(workspace_id)
    ensure_dir(output_dir)

    profiles = load_social_profiles()

    if not profiles:
        raise ValueError("No social image profiles found.")

    image = Image.open(source_path)

    result = {
        "workspace_id": workspace_id,
        "source_path": str(source_path),
        "recommended_filename": recommended_filename,
        "profiles_source": str(SOCIAL_PROFILES_PATH),
        "variants": []
    }

    for profile_name, spec in profiles.items():
        # WordPress featured variants are handled by image_optimizer.py
        if profile_name == "wordpress_featured":
            continue

        width = int(spec["width"])
        height = int(spec["height"])
        fmt = normalize_format(spec.get("format") or "jpg")

        variant = resize_cover(image, width, height)

        filename = build_social_filename(
            recommended_filename,
            profile_name,
            fmt
        )

        output_path = output_dir / filename

        saved = save_optimized(
            variant,
            output_path,
            fmt=fmt,
            max_size_kb=int(spec.get("max_size_kb", 0) or 0),
            start_quality=int(spec.get("quality", 88) or 88),
        )

        saved.update({
            "profile": profile_name,
            "width": width,
            "height": height,
            "platform_use": profile_name
        })

        result["variants"].append(saved)

    metadata_path = save_social_metadata(result, output_dir)
    result["metadata_file"] = str(metadata_path)

    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 4:
        print("Usage:")
        print("python -m app.image_assets.image_social_variants WORKSPACE_ID SOURCE_IMAGE recommended-filename.jpg")
        sys.exit(1)

    workspace_id = sys.argv[1]
    source_image = sys.argv[2]
    recommended_filename = sys.argv[3]

    result = create_social_variants(
        workspace_id=workspace_id,
        source_path=source_image,
        recommended_filename=recommended_filename,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
