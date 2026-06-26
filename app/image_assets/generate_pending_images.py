#!/usr/bin/env python3
"""
Prepare AI image generation jobs for Sofia drafts.

Phase 1:
- Detect ai_generation_candidate image slots.
- Create master generation request records.
- Do not call Flux yet.
- Do not upload generated images yet.

Later:
- Execute local Flux2Klein generation.
- Save master image.
- Optimize variants.
- Upload/insert like existing assets.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.workspace_paths import get_workspace_folder_path, get_workspace_draft_registry_path
from app.image_assets.image_job_registry import create_image_job

try:
    from app.image_assets.visual_intelligence import enhance_image_generation_request
except Exception:
    from visual_intelligence import enhance_image_generation_request



ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT_DIR / "data" / "image_assets" / "ai_image_generation_config.json"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def find_draft(registry, draft_id):
    for draft in registry.get("drafts", []):
        if draft.get("draft_id") == draft_id:
            return draft
    return None


def collect_generation_candidates(image_plan):
    candidates = []

    featured = image_plan.get("featured_image") or {}
    if featured.get("source_type") == "ai_generation_candidate":
        candidates.append(("featured_image", featured))

    for slot in image_plan.get("in_article_images") or []:
        if slot.get("source_type") == "ai_generation_candidate":
            candidates.append((slot.get("slot_id") or "in_article", slot))

    return candidates


def build_generation_request(*, workspace_id, draft_id, slot_id, slot, config, workspace_folder):
    paths = config.get("paths", {})
    master_rel_dir = paths.get("master_generated_dir", "assets/images/generated/master")
    master_dir = workspace_folder / master_rel_dir

    filename = (
        slot.get("recommended_filename")
        or f"{draft_id.lower()}-{slot_id}.png"
    )

    filename = Path(filename).stem + ".png"
    master_path = master_dir / filename

    return {
        "request_id": f"IMGGEN-{draft_id}-{slot_id}".replace("_", "-"),
        "created_at": now_iso(),
        "workspace_id": workspace_id,
        "draft_id": draft_id,
        "slot_id": slot_id,
        "status": "pending_generation",
        "provider": config.get("default_provider", "local_flux"),
        "model": slot.get("generation_model_preference") or config.get("default_model", "Flux2Klein"),
        "prompt": slot.get("prompt", ""),
        "negative_prompt": slot.get("negative_prompt", ""),
        "master_output": config.get("master_output", {}),
        "master_file": str(master_path.relative_to(ROOT_DIR)),
        "recommended_filename": filename,
        "requires_examiner_approval": slot.get("requires_examiner_approval", True),
        "wordpress_upload_enabled": False,
        "source_slot": slot,
        "notes": [
            "This is a generation request scaffold.",
            "No image has been generated yet.",
            "Generated master should be optimized before WordPress upload."
        ]
    }








def sentence_case(value):
    value = str(value or "").strip()
    if not value:
        return value
    return value[:1].upper() + value[1:]



def build_workspace_context(workspace_id, draft):
    intelligence = (draft or {}).get("opportunity_intelligence") or {}
    return {
        "workspace_id": workspace_id,
        "country": (
            intelligence.get("country_localized")
            or (draft or {}).get("country_localized")
            or (draft or {}).get("country")
            or workspace_id
        ),
    }



def infer_visual_role_from_slot(slot_id, source_slot):
    role = (
        (source_slot or {}).get("visual_role")
        or (source_slot or {}).get("role")
        or ""
    )
    if role:
        return role

    slot_id = str(slot_id or "").lower()
    if slot_id == "featured_image":
        return "problem_scene"
    if "in_article_1" in slot_id:
        return "investigation_scene"
    if "in_article_2" in slot_id:
        return "analysis_scene"
    return "supporting_scene"


def apply_opportunity_intelligence_to_request(request, draft, workspace_folder):
    """
    Final safety layer before image jobs are created.

    Ensures generated image request scaffolds use:
    - opportunity_intelligence.visual_scenarios
    - opportunity_intelligence.recommended_slug

    This does not generate images. It only corrects the pending request/job data.
    """
    intelligence = (draft or {}).get("opportunity_intelligence") or {}
    if not isinstance(intelligence, dict) or not intelligence:
        return request

    source_slot = request.get("source_slot") or {}
    slot_id = request.get("slot_id") or source_slot.get("slot_id") or ""
    role = infer_visual_role_from_slot(slot_id, source_slot)

    scenarios = intelligence.get("visual_scenarios") or {}
    scenario_candidates = scenarios.get(role) or []
    scenario = ""

    if isinstance(scenario_candidates, list) and scenario_candidates:
        scenario = str(scenario_candidates[0]).strip()

    if scenario:
        issue = intelligence.get("issue") or draft.get("issue") or ""
        sector = intelligence.get("sector") or draft.get("sector") or ""
        country = intelligence.get("country_localized") or draft.get("country_localized") or ""

        metadata_by_role = {
            "problem_scene": {
                "title": sentence_case(f"{issue} en {sector}".strip()),
                "alt_text": f"Situación relacionada con {issue} en {sector}".strip(),
                "description": f"Imagen de apoyo visual sobre una situación relacionada con {issue} en {sector}{(' en ' + country) if country else ''}.".strip(),
            },
            "investigation_scene": {
                "title": f"Revisión interna sobre {issue}".strip(),
                "alt_text": f"Revisión profesional de información relacionada con {issue}".strip(),
                "description": f"Imagen de apoyo visual sobre la revisión interna de información en una investigación relacionada con {issue}{(' en ' + country) if country else ''}.".strip(),
            },
            "analysis_scene": {
                "title": f"Análisis documental sobre {issue}".strip(),
                "alt_text": f"Análisis de documentación en una investigación sobre {issue}".strip(),
                "description": f"Imagen de apoyo visual sobre análisis documental, registros y preparación de preguntas en una investigación relacionada con {issue}{(' en ' + country) if country else ''}.".strip(),
            },
        }

        metadata = metadata_by_role.get(role, {})
        for key, value in metadata.items():
            if value:
                request[key] = value[:220]
                source_slot[key] = value[:220]

        old_prompt = request.get("prompt", "") or ""
        new_prompt = re.sub(
            r"Topic:\s*.*?\.\s*Page type:",
            f"Topic: {scenario}. Page type:",
            old_prompt,
            count=1,
            flags=re.I,
        )

        if new_prompt == old_prompt:
            new_prompt = f"{old_prompt} Topic: {scenario}."

        request["prompt"] = new_prompt
        request["visual_scenario"] = scenario
        request["visual_role"] = role

        source_slot["prompt"] = new_prompt
        source_slot["visual_scenario"] = scenario
        source_slot["visual_role"] = role

    recommended_slug = intelligence.get("recommended_slug") or draft.get("slug") or draft.get("suggested_slug") or ""
    recommended_slug = str(recommended_slug).strip("- ")

    if recommended_slug:
        suffix = "" if slot_id == "featured_image" else f"-{slot_id}"
        filename_png = f"{recommended_slug}{suffix}.png"
        filename_webp = f"{recommended_slug}{suffix}.webp"

        master_path = workspace_folder / "assets" / "images" / "generated" / "master" / filename_png

        request["recommended_filename"] = filename_png
        request["master_file"] = str(master_path.relative_to(ROOT_DIR))

        source_slot["recommended_filename"] = filename_webp
        source_slot["source_filename"] = source_slot.get("source_filename", "")

    request["source_slot"] = source_slot
    return request



def main():
    if len(sys.argv) != 3:
        print("Usage:")
        print("python -m app.image_assets.generate_pending_images WORKSPACE_ID DRAFT_ID")
        sys.exit(1)

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]

    config = load_json(CONFIG_PATH, {})
    workspace_folder = get_workspace_folder_path(workspace_id)
    registry_path = get_workspace_draft_registry_path(workspace_id)

    registry = load_json(registry_path)
    draft = find_draft(registry, draft_id)

    if not draft:
        raise SystemExit(f"Draft not found: {draft_id}")

    # Minimal workspace context for visual intelligence.
    # Prefer localized country from the image plan/source slots when available;
    # fall back to workspace_id so generation still works.
    workspace_country_fallbacks = {
        "local.es": "España",
        "local.pt": "Portugal",
        "local.br": "Brasil",
        "local.fr": "France",
        "local.be": "Belgique",
        "local.tr": "Türkiye",
        "local.in": "India",
        "local.ao": "Angola",
        "local.co": "Colombia",
        "local.ae": "Emiratos Árabes Unidos",
    }

    workspace = {
        "workspace_id": workspace_id,
        "country": (
            (draft.get("image_plan") or {}).get("country_localized")
            or (draft.get("workspace") or {}).get("country")
            or workspace_country_fallbacks.get(workspace_id)
            or ""
        ),
    }

    # Use prepared image assets as source of truth when available.
    # This prevents regenerating images that were already generated/optimized.
    preparation = draft.get("image_asset_preparation") or {}
    candidates = []

    featured_prepared = preparation.get("featured_image") or {}
    if featured_prepared.get("source_type") == "ai_generation_candidate":
        candidates.append(("featured_image", featured_prepared))

    for prepared_slot in preparation.get("in_article_images") or []:
        if prepared_slot.get("source_type") == "ai_generation_candidate":
            candidates.append((prepared_slot.get("slot_id") or "in_article", prepared_slot))

    # Backward fallback: if no preparation exists yet, use original image_plan.
    if not candidates and not preparation:
        image_plan = draft.get("image_plan") or {}
        candidates = collect_generation_candidates(image_plan)

    requests = []

    for slot_id, slot in candidates:
        request = build_generation_request(
            workspace_id=workspace_id,
            draft_id=draft_id,
            slot_id=slot_id,
            slot=slot,
            config=config,
            workspace_folder=workspace_folder,
        )
        request = enhance_image_generation_request(request, draft=draft, workspace=build_workspace_context(workspace_id, draft))
        request = apply_opportunity_intelligence_to_request(
            request=request,
            draft=draft,
            workspace_folder=workspace_folder,
        )
        requests.append(request)

        create_image_job(
            workspace_id=workspace_id,
            draft_id=draft_id,
            slot_id=slot_id,
            provider=request.get("provider", "local_flux"),
            model=request.get("model", "Flux2Klein"),
            prompt=request.get("prompt", ""),
            master_file=request.get("master_file", ""),
            negative_prompt=request.get("negative_prompt", ""),
            source_request=request,
            requires_examiner_approval=request.get(
                "requires_examiner_approval",
                True,
            ),
            status="pending_generation",
        )

    draft["ai_image_generation"] = {
        "checked_at": now_iso(),
        "candidate_count": len(candidates),
        "requests": requests,
        "status": "pending_generation" if requests else "no_generation_needed"
    }

    save_json(registry_path, registry)

    print(json.dumps(draft["ai_image_generation"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
