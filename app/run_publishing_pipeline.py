import subprocess
import sys


STEPS = [
    {
        "name": "Generate AI draft content",
        "command": ["python", "app/generate_draft_content.py"]
    },
    {
        "name": "Clean generated HTML",
        "command_template": ["python", "app/clean_generated_html.py", "{draft_id}"]
    },
    {
        "name": "Validate generated content",
        "command_template": ["python", "app/validate_generated_content.py", "{draft_id}"]
    },
    {
        "name": "Repair generated content if needed",
        "command_template": ["python", "app/repair_generated_content.py", "{draft_id}"],
        "optional": True
    },
    {
        "name": "Clean repaired HTML",
        "command_template": ["python", "app/clean_generated_html.py", "{draft_id}"],
        "optional": True
    },
    {
        "name": "Validate repaired content",
        "command_template": ["python", "app/validate_generated_content.py", "{draft_id}"],
        "optional": True
    },
    {
        "name": "Inject base internal links",
        "command_template": ["python", "app/inject_internal_links.py", "{draft_id}"]
    },
    {
        "name": "Optimize internal link anchors",
        "command_template": ["python", "app/optimize_internal_link_anchors.py", "{draft_id}"]
    },
    {
        "name": "Apply AI internal links",
        "command_template": ["python", "app/apply_ai_internal_links.py", "{draft_id}"]
    },
    {
        "name": "Final clean HTML",
        "command_template": ["python", "app/clean_generated_html.py", "{draft_id}"]
    },
    {
        "name": "Final validation",
        "command_template": ["python", "app/validate_generated_content.py", "{draft_id}"]
    },
    {
        "name": "Export WordPress package",
        "command_template": ["python", "app/export_wordpress_package.py", "{draft_id}"]
    },
    {
        "name": "Upload or update WordPress draft",
        "command_template": ["python", "app/update_wordpress_draft.py", "{draft_id}"],
        "fallback_command_template": ["python", "app/upload_wordpress_draft.py", "{draft_id}"]
    }
]


def build_command(step, draft_id, key="command_template"):
    if "command" in step and key == "command_template":
        return step["command"]

    template = step.get(key)
    if not template:
        return None

    return [part.replace("{draft_id}", draft_id) for part in template]


def run_command(command):
    result = subprocess.run(command, text=True, capture_output=True)

    print(result.stdout)

    if result.stderr:
        print(result.stderr)

    return result.returncode, result.stdout + result.stderr


def main():
    print("=== Sofia: Run Publishing Pipeline ===\n")

    if len(sys.argv) != 2:
        print("Usage:")
        print("python app/run_publishing_pipeline.py DRAFT-0005")
        return

    draft_id = sys.argv[1]

    for step in STEPS:
        print("=" * 70)
        print(f"STEP: {step['name']}")
        print("=" * 70)

        command = build_command(step, draft_id)

        if not command:
            print("ERROR: Step has no command.")
            return

        code, output = run_command(command)

        if step["name"] == "Validate generated content" and "Validation status: failed" in output:
            print("Validation failed. Repair steps will run next.\n")
            continue

        if step.get("optional") and code != 0:
            print("Optional step failed or skipped. Continuing.\n")
            continue

        if step["name"] == "Upload or update WordPress draft" and code != 0:
            print("Update failed. Trying first upload fallback...\n")
            fallback = build_command(step, draft_id, key="fallback_command_template")
            fallback_code, _ = run_command(fallback)

            if fallback_code != 0:
                print("ERROR: WordPress update/upload failed.")
                return

            continue

        if code != 0:
            print(f"ERROR: Step failed: {step['name']}")
            return

    print("\n=== Publishing pipeline completed ===")


if __name__ == "__main__":
    main()