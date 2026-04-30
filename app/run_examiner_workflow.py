import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_command(command):
    print("\n" + "=" * 70)
    print("RUNNING:", " ".join(command))
    print("=" * 70)

    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True
    )

    print(result.stdout)

    if result.stderr:
        print(result.stderr)

    if result.returncode != 0:
        print("Workflow stopped due to error.")
        sys.exit(result.returncode)


def main():
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python app/run_examiner_workflow.py WORKSPACE_ID DRAFT_ID --preview")
        print("  python app/run_examiner_workflow.py WORKSPACE_ID DRAFT_ID --send")
        print("")
        print("Example:")
        print("  python app/run_examiner_workflow.py local.ao DRAFT-0001 --preview")
        return

    workspace_id = sys.argv[1]
    draft_id = sys.argv[2]
    mode = sys.argv[3] if len(sys.argv) > 3 else "--preview"

    if mode not in ["--preview", "--send"]:
        print("Invalid mode. Use --preview or --send.")
        return

    run_command([
        sys.executable,
        "app/send_to_examiner_review.py",
        workspace_id,
        draft_id
    ])

    run_command([
        sys.executable,
        "app/notify_examiner_review.py",
        workspace_id,
        mode
    ])

    print("\nExaminer workflow completed.")
    print(f"Workspace: {workspace_id}")
    print(f"Draft: {draft_id}")
    print(f"Mode: {mode}")


if __name__ == "__main__":
    main()