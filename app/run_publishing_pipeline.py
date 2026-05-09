import subprocess
import sys


CONTENT_STEPS = [
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
    }
]


EXAMINER_REVIEW_STEPS = [
    {
        "name": "Route draft to examiner review",
        "command_template": ["python", "app/route_draft_to_review.py", "{draft_id}"]
    }
]


WORDPRESS_STEPS = [
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

    combined_output = ""

    if result.stdout:
        print(result.stdout)
        combined_output += result.stdout

    if result.stderr:
        print(result.stderr)
        combined_output += result.stderr

    logical_failure_markers = [
        "Traceback",
        "Exception",
        "WordPress credentials are missing",
        "Draft is not exportable",
        "Draft status is not uploadable",
        "WordPress upload failed",
        "WordPress update failed",
    ]

    code = result.returncode

    if code == 0:
        for marker in logical_failure_markers:
            if marker in combined_output:
                code = 1
                break

    return code, combined_output


def run_steps(steps, draft_id):
    for step in steps:
        print("=" * 70)
        print(f"STEP: {step['name']}")
        print("=" * 70)

        command = build_command(step, draft_id)

        if not command:
            print("ERROR: Step has no command.")
            return False

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
                return False

            continue

        if code != 0:
            print(f"ERROR: Step failed: {step['name']}")
            return False

    return True


def main():
    print("=== Sofia: Run Publishing Pipeline ===\n")

    if len(sys.argv) != 3:
        print("Usage:")
        print("python app/run_publishing_pipeline.py DRAFT-0005 --to-review")
        print("python app/run_publishing_pipeline.py DRAFT-0005 --after-approval")
        return

    draft_id = sys.argv[1]
    mode = sys.argv[2]

    if mode not in ["--to-review", "--after-approval"]:
        print("Invalid mode.")
        print("Use --to-review or --after-approval.")
        return

    if mode == "--to-review":
        print("MODE: Generate content and route to examiner review\n")

        ok = run_steps(CONTENT_STEPS, draft_id)

        if not ok:
            print("ERROR: Content pipeline failed before examiner review.")
            return

        ok = run_steps(EXAMINER_REVIEW_STEPS, draft_id)

        if not ok:
            print("ERROR: Could not route draft to examiner review.")
            return

        print("\n=== Pipeline completed: draft sent to examiner review ===")
        return

    if mode == "--after-approval":
        print("MODE: Continue after examiner approval and create/update WordPress draft\n")

        ok = run_steps(WORDPRESS_STEPS, draft_id)

        if not ok:
            print("ERROR: WordPress pipeline failed.")
            return

        print("\n=== Pipeline completed: WordPress draft ready for examiner publishing ===")


if __name__ == "__main__":
    main()