import json
import os
import sys
import requests
from pathlib import Path
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_PATH = ROOT / "data" / "workspaces.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def find_workspace(workspaces, workspace_id):
    for workspace in workspaces.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace
    return None


def build_message(review):
    return f"""
[SOFIA – DRAFT REVIEW]

Draft ID: {review.get("draft_id")}
Review ID: {review.get("review_id")}
Country: {review.get("country")}
Workspace: {review.get("workspace_id")}
Language: {review.get("language")}
Title: {review.get("title")}
Content Type: {review.get("content_type")}
Focus Keyphrase: {review.get("focus_keyphrase")}
Priority: {review.get("review_priority")}

ACTION REQUIRED:

Please review this draft for professional and local accuracy.

Sofia is responsible for:
- SEO structure
- GEO / AI-friendly formatting
- keyword targeting
- internal links
- cannibalization avoidance

The examiner is responsible for:
- professional correctness
- local legal/cultural suitability
- terminology accuracy
- service availability
- pricing/logistical accuracy

Reply using one of these formats:

APPROVE {review.get("draft_id")}

REVISE {review.get("draft_id")}: explain what must be changed

REJECT {review.get("draft_id")}: explain why this draft should not be used
""".strip()


def send_telegram_message(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }

    response = requests.post(url, json=payload, timeout=20)
    response.raise_for_status()

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(result)

    return result


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python app/notify_examiner_review.py WORKSPACE_ID --preview")
        print("  python app/notify_examiner_review.py WORKSPACE_ID --send")
        print("Example:")
        print("  python app/notify_examiner_review.py local.ao --send")
        return

    workspace_id = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "--preview"

    if mode not in ["--preview", "--send"]:
        print("Invalid mode. Use --preview or --send.")
        return

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, workspace_id)

    if not workspace:
        print(f"Workspace not found: {workspace_id}")
        return

    review_queue_path = ROOT / workspace["review_queue_path"]
    review_queue = load_json(review_queue_path)

    telegram_group_id = workspace.get("telegram_group_id")
    telegram_group = workspace.get("telegram_group", "")

    if mode == "--send" and not telegram_group_id:
        print(f"No telegram_group_id found for workspace: {workspace_id}")
        return

    bot_token = os.getenv("SOFIA_TELEGRAM_BOT_TOKEN")

    if mode == "--send" and not bot_token:
        print("Missing environment variable: SOFIA_TELEGRAM_BOT_TOKEN")
        print("Set it temporarily like this:")
        print("export SOFIA_TELEGRAM_BOT_TOKEN='YOUR_BOT_TOKEN'")
        return

    pending_reviews = [
        review for review in review_queue.get("reviews", [])
        if review.get("status") == "in_examiner_review"
        and review.get("telegram_notified") is False
    ]

    if not pending_reviews:
        print("No pending examiner review notifications.")
        return

    sent_count = 0

    for review in pending_reviews:
        message = build_message(review)

        print("\n" + "=" * 60)
        print(f"TELEGRAM GROUP: {telegram_group}")
        print(f"TELEGRAM GROUP ID: {telegram_group_id}")
        print("=" * 60)
        print(message)
        print("=" * 60)

        if mode == "--send":
            send_telegram_message(bot_token, telegram_group_id, message)
            print("Telegram message sent.")

        if mode == "--send":
            review["telegram_notified"] = True
            review["telegram_notified_at"] = now_iso()
            review["updated_at"] = now_iso()
            sent_count += 1
        else:
            # preview mode → do not modify data
            sent_count += 1

    if mode == "--send":
        save_json(review_queue_path, review_queue)

    print(f"\nNotifications processed: {sent_count}")
    print(f"Mode: {mode}")


if __name__ == "__main__":
    main()