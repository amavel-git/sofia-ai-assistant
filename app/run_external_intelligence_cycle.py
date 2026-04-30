import subprocess
import sys
from pathlib import Path


SOFIA_ROOT = Path(__file__).resolve().parents[1]


STEPS = [
    {
        "name": "Discover Google suggestions",
        "command": ["python", "app/discover_google_suggestions.py"]
    },
    {
        "name": "Filter external signals",
        "command": ["python", "app/filter_external_signals.py"]
    },
    {
        "name": "Convert relevant signals to opportunities",
        "command": ["python", "app/convert_signals_to_opportunities.py"]
    },
    {
        "name": "Cluster opportunities",
        "command": ["python", "app/cluster_opportunities_v2.py"]
    },
    {
        "name": "Content strategy mapping",
        "command": ["python", "app/content_strategy_mapper.py"]
    },
    {
        "name": "Generate opportunity SEO brief",
        "command": ["python", "app/generate_opportunity_seo_brief.py"]
    },
    {
        "name": "Generate content strategy brief",
        "command": ["python", "app/generate_content_strategy_brief.py"]
    },
    {
        "name": "Pre-validate opportunities",
        "command": ["python", "app/prevalidate_external_opportunities.py"]
    },
    {
        "name": "Validate external opportunities",
        "command": ["python", "app/validate_external_opportunities.py"]
    },
    {
        "name": "Generate examiner review messages",
        "command": ["python", "app/generate_opportunity_review_message.py"]
    },
    {
        "name": "Convert approved opportunities to intake",
        "command": ["python", "app/convert_opportunity_to_intake.py"]
    },
    {
        "name": "Process next intake",
        "command": ["python", "app/process_next_intake.py"]
    },
    {
    "name": "Generate AI draft content",
    "command": ["python", "app/generate_draft_content.py"]
    },
]


def run_step(step):
    print("\n" + "=" * 70)
    print(f"STEP: {step['name']}")
    print("=" * 70)

    result = subprocess.run(
        step["command"],
        cwd=SOFIA_ROOT,
        text=True,
        capture_output=True
    )

    if result.stdout:
        print(result.stdout)

    if result.stderr:
        print("STDERR:")
        print(result.stderr)

    if result.returncode != 0:
        print(f"Step failed: {step['name']}")
        sys.exit(result.returncode)


def main():
    print("=== Sofia: External Intelligence Cycle ===")
    print(f"Workspace root: {SOFIA_ROOT}")

    for step in STEPS:
        run_step(step)

    print("\n=== Cycle completed successfully ===")


if __name__ == "__main__":
    main()