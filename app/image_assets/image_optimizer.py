#!/usr/bin/env python3
"""
Sofia Image Optimizer

Phase 2 foundation:
- resize images
- convert to WebP/JPG
- create desktop/tablet/mobile variants
- keep filenames SEO-friendly
- control file weight

No WordPress upload yet.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image


ROOT_DIR = Path(__file__).resolve().parents[2]
IMAGE_ASSET_DATA_DIR = ROOT_DIR / "data" / "image_assets"
OPTIMIZATION_PROFILES_PATH = IMAGE_ASSET_DATA_DIR / "image_optimization_profiles.json"

DEFAULT_OUTPUT_DIR = IMAGE_ASSET_DATA_DIR / "generated"
SITES_DIR = ROOT_DIR / "sites" / "local_sites"


def workspace_path_from_id(workspace_id: str) -> Path:
    if not workspace_id:
        raise ValueError("workspace_id is required")
    suffix = workspace_id.split(".")[-1]
    return SITES_DIR / suffix


def get_workspace_optimized_dir(workspace_id: str) -> Path:
    return workspace_path_from_id(workspace_id) / "assets" / "images" / "optimized"


def load_json(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if default is None:
        default = {}

    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def get_file_size_kb(path: Path) -> int:
    if not path.exists():
        return 0
    return round(path.stat().st_size / 1024)


def normalize_format(fmt: str) -> str:
    fmt = (fmt or "webp").lower().strip()
    if fmt == "jpeg":
        return "jpg"
    return fmt


def resize_cover(image: Image.Image, width: int, height: int) -> Image.Image:
    """
    Resize and center-crop to exact target size.
    Good for featured/social images where aspect ratio must be controlled.
    """
    image = image.convert("RGB")

    source_w, source_h = image.size
    source_ratio = source_w / source_h
    target_ratio = width / height

    if source_ratio > target_ratio:
        new_h = height
        new_w = round(height * source_ratio)
    else:
        new_w = width
        new_h = round(width / source_ratio)

    resized = image.resize((new_w, new_h), Image.LANCZOS)

    left = max((new_w - width) // 2, 0)
    top = max((new_h - height) // 2, 0)
    right = left + width
    bottom = top + height

    return resized.crop((left, top, right, bottom))


def save_optimized(
    image: Image.Image,
    output_path: Path,
    fmt: str,
    max_size_kb: Optional[int] = None,
    start_quality: int = 86,
    min_quality: int = 58
) -> Dict[str, Any]:
    """
    Saves image with decreasing quality until it reaches target weight,
    or until min_quality is reached.
    """
    fmt = normalize_format(fmt)
    ensure_dir(output_path.parent)

    quality = start_quality
    save_format = "JPEG" if fmt == "jpg" else fmt.upper()

    while True:
        save_kwargs = {}

        if fmt in ["jpg", "webp"]:
            save_kwargs["quality"] = quality
            save_kwargs["optimize"] = True

        if fmt == "webp":
            save_kwargs["method"] = 6

        image.save(output_path, save_format, **save_kwargs)

        size_kb = get_file_size_kb(output_path)

        if not max_size_kb:
            break

        if size_kb <= max_size_kb:
            break

        if quality <= min_quality:
            break

        quality -= 4

    return {
        "file": str(output_path),
        "filename": output_path.name,
        "format": fmt,
        "size_kb": get_file_size_kb(output_path),
        "quality": quality
    }


def load_optimization_profiles() -> Dict[str, Any]:
    return load_json(OPTIMIZATION_PROFILES_PATH, {})


def get_profile(profile_name: str) -> Dict[str, Any]:
    profiles = load_optimization_profiles()
    return profiles.get(profile_name, {})


def build_variant_filename(base_filename: str, width: int, fmt: str) -> str:
    base = Path(base_filename).stem
    fmt = normalize_format(fmt)
    return f"{base}-{width}.{fmt}"



def save_variant_metadata(result: Dict[str, Any], output_dir: Path) -> Path:
    """
    Save optimizer output metadata alongside generated workspace images.

    Example:
    sites/local_sites/es/assets/images/optimized/prueba-poligrafo-infidelidad-espana.json
    """
    metadata_path = output_dir / f"{Path(result['recommended_filename']).stem}.json"

    ensure_dir(metadata_path.parent)

    with metadata_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return metadata_path

def optimize_image_variants(
    source_path: str | Path,
    recommended_filename: str,
    profile_name: str = "featured_image",
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    default_format: str = "webp"
) -> Dict[str, Any]:
    source_path = Path(source_path)
    output_dir = Path(output_dir)
    profile = get_profile(profile_name)

    if not source_path.exists():
        raise FileNotFoundError(f"Source image not found: {source_path}")

    if not profile:
        raise ValueError(f"Optimization profile not found: {profile_name}")

    image = Image.open(source_path)

    result = {
        "source_path": str(source_path),
        "recommended_filename": recommended_filename,
        "profile": profile_name,
        "variants": []
    }

    # Featured image profile has desktop/tablet/mobile.
    if all(k in profile for k in ["desktop", "tablet", "mobile"]):
        for label in ["desktop", "tablet", "mobile"]:
            spec = profile[label]
            width = int(spec["width"])
            height = int(spec["height"])
            max_size_kb = int(spec.get("max_size_kb", 0) or 0)
            fmt = normalize_format(spec.get("format") or default_format)

            variant = resize_cover(image, width, height)
            filename = build_variant_filename(recommended_filename, width, fmt)
            output_path = output_dir / filename

            saved = save_optimized(
                variant,
                output_path,
                fmt=fmt,
                max_size_kb=max_size_kb
            )

            saved.update({
                "label": label,
                "width": width,
                "height": height,
                "max_size_kb": max_size_kb
            })

            result["variants"].append(saved)

    # Simpler inline profile.
    else:
        width = int(profile["width"])
        height = int(profile["height"])
        max_size_kb = int(profile.get("max_size_kb", 0) or 0)
        fmt = normalize_format(profile.get("format") or default_format)

        variant = resize_cover(image, width, height)
        filename = build_variant_filename(recommended_filename, width, fmt)
        output_path = output_dir / filename

        saved = save_optimized(
            variant,
            output_path,
            fmt=fmt,
            max_size_kb=max_size_kb
        )

        saved.update({
            "label": profile_name,
            "width": width,
            "height": height,
            "max_size_kb": max_size_kb
        })

        result["variants"].append(saved)

    metadata_path = save_variant_metadata(result, output_dir)
    result["metadata_file"] = str(metadata_path)

    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 4:
        print("Usage:")
        print("python -m app.image_assets.image_optimizer WORKSPACE_ID SOURCE_IMAGE recommended-filename.webp")
        sys.exit(1)

    workspace_id = sys.argv[1]
    source_image = sys.argv[2]
    recommended_filename = sys.argv[3]

    output_dir = get_workspace_optimized_dir(workspace_id)

    result = optimize_image_variants(
        source_path=source_image,
        recommended_filename=recommended_filename,
        profile_name="featured_image",
        output_dir=output_dir
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
