import json
import os
import sys
import requests
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)
WORKSPACES_PATH = ROOT / "data" / "workspaces.json"
TEMPLATES_PATH = ROOT / "data" / "telegram_message_templates.json"


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


def normalize_language(language):
    if not language:
        return "en"

    language = language.strip()

    if language in ["pt-PT", "pt-BR"]:
        return language

    if language.startswith("pt"):
        return "pt-PT"

    if language.startswith("es"):
        return "es"

    if language.startswith("fr"):
        return "fr"

    if language.startswith("tr"):
        return "tr"

    if language.startswith("ru"):
        return "ru"

    if language.startswith("en"):
        return "en"

    return "en"


def get_template(message_type, language):
    templates = load_json(TEMPLATES_PATH)
    normalized = normalize_language(language)

    message_templates = templates.get(message_type, {})

    return (
        message_templates.get(normalized)
        or message_templates.get("en")
        or {}
    )


def format_enabled_channels(workspace, template):
    channels = workspace.get("channels", {})
    lines = []

    url_not_configured = template.get("url_not_configured", "URL not configured")
    types_label = template.get("types_label", "types")
    no_channels = template.get("no_channels", "No active channels configured.")

    for channel_name, channel in channels.items():
        if channel.get("enabled") is True:
            url = channel.get("url", "")
            content_types = ", ".join(channel.get("content_types", []))
            lines.append(
                f"- {channel_name}: {url or url_not_configured} | {types_label}: {content_types}"
            )

    if not lines:
        return no_channels

    return "\n".join(lines)


def build_message(item, workspace):
    language = workspace.get("language", "en")
    template = get_template("draft_review", language)

    draft_id = item.get("draft_id")
    title = item.get("working_title")
    keyphrase = item.get("target_keyword")

    channels_text = format_enabled_channels(workspace, template)
    check_items = template.get("check_items", [])
    check_items_text = "\n".join([f"- {item}" for item in check_items])

    return f"""
{template.get("header", "[SOFIA – DRAFT REVIEW]")}

{template.get("draft_id_label", "Draft ID")}: {draft_id}
{template.get("workspace_label", "Workspace")}: {workspace.get("workspace_id")}
{template.get("country_label", "Country")}: {workspace.get("country")}
{template.get("language_label", "Language")}: {workspace.get("language")}

{template.get("title_label", "Title")}:
{title}

{template.get("keyphrase_label", "Focus Keyphrase")}:
{keyphrase}

{template.get("channels_label", "Channels where this content may be used")}:
{channels_text}

{template.get("task_label", "Examiner task")}:
{template.get("action", "Please review this draft for professional and local accuracy.")}

{template.get("check_label", "Please confirm:")}
{check_items_text}

{template.get("next_step_label", "Next step after approval")}:
{template.get("next_step", "Sofia will prepare or update the corresponding draft for final review.")}

{template.get("button_instruction", "Use the buttons below to approve or request changes.")}

""".strip()


def get_button_labels(language):
    language = str(language or "en").lower()

    if language.startswith("pt-br"):
        return {
            "approve": "✅ Aprovar",
            "revise": "✏️ Revisar",
        }

    if language.startswith("pt"):
        return {
            "approve": "✅ Aprovar",
            "revise": "✏️ Rever",
        }

    if language.startswith("es"):
        return {
            "approve": "✅ Aprobar",
            "revise": "✏️ Revisar",
        }

    if language.startswith("fr"):
        return {
            "approve": "✅ Approuver",
            "revise": "✏️ Réviser",
        }

    return {
        "approve": "✅ Approve",
        "revise": "✏️ Revise",
    }


def build_decision_keyboard(draft_id, workspace_id, language="en"):
    labels = get_button_labels(language)

    return {
        "inline_keyboard": [
            [
                {"text": labels["approve"], "callback_data": f"APPROVE|{workspace_id}|{draft_id}"},
                {"text": labels["revise"], "callback_data": f"REVISE_PROMPT|{workspace_id}|{draft_id}"},
            ]
        ]
    }


def send_telegram_message(bot_token, chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

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
    if bot_token:
        bot_token = bot_token.strip().strip('"').strip("'")

    if mode == "--send" and not bot_token:
        print("Missing environment variable: SOFIA_TELEGRAM_BOT_TOKEN")
        return

    review_items = review_queue.get("review_items", [])

    pending_reviews = [
        item for item in review_items
        if item.get("status") == "pending_review"
        and item.get("telegram_notified") is not True
    ]

    if not pending_reviews:
        print("No pending examiner review notifications.")
        return

    sent_count = 0

    for review in pending_reviews:
        message = build_message(review, workspace)
        keyboard = build_decision_keyboard(
            draft_id,
            workspace_id,
            workspace.get("language", "en")
        )

        print("\n" + "=" * 60)
        print(f"TELEGRAM GROUP: {telegram_group}")
        print(f"TELEGRAM GROUP ID: {telegram_group_id}")
        print("=" * 60)
        print(message)
        print("=" * 60)

        if mode == "--send":
            send_telegram_message(
                bot_token,
                telegram_group_id,
                message,
                reply_markup=keyboard
            )
            print("Telegram message sent with buttons.")

            review["telegram_notified"] = True
            review["telegram_notified_at"] = now_iso()
            review["updated_at"] = now_iso()
            sent_count += 1
        else:
            sent_count += 1

    if mode == "--send":
        save_json(review_queue_path, review_queue)

    print(f"\nNotifications processed: {sent_count}")
    print(f"Mode: {mode}")


if __name__ == "__main__":
    main()