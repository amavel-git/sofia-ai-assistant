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
ACTIVATION_PATH = ROOT / "data" / "workspace_activation.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_activation_state():
    if not ACTIVATION_PATH.exists():
        return {"workspaces": {}, "updated_at": None}

    return load_json(ACTIVATION_PATH)


def is_workspace_active(workspace_id):
    state = load_activation_state()
    workspace_state = state.get("workspaces", {}).get(workspace_id)

    if not workspace_state:
        return False

    return (
    workspace_state.get("external_opportunities_active") is True
    or workspace_state.get("sofia_active") is True
)


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
    no_channels = template.get("no_channels", "No active publishing channels configured.")

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


def format_risk_notes(risk_notes):
    if not risk_notes:
        return "None"

    if isinstance(risk_notes, list):
        return "\n".join([f"- {note}" for note in risk_notes])

    return str(risk_notes)


def build_message(opportunity, workspace):
    language = workspace.get("language", "en")
    template = get_template("opportunity_review", language)

    opportunity_id = opportunity.get("id") or opportunity.get("opportunity_id") or "N/A"
    topic = opportunity.get("topic", "N/A")
    opportunity_type = opportunity.get("opportunity_type", "N/A")
    recommended_content_type = opportunity.get("recommended_content_type", "N/A")
    priority = opportunity.get("priority", "N/A")
    business_reason = opportunity.get("business_reason", "")
    risk_notes = opportunity.get("risk_notes", [])

    none_text = template.get("none", "None")

    if not business_reason:
        business_reason = none_text

    risk_notes_text = format_risk_notes(risk_notes)
    if risk_notes_text == "None":
        risk_notes_text = none_text

    channels_text = format_enabled_channels(workspace, template)

    check_items = template.get("check_items", [])
    check_items_text = "\n".join([f"- {item}" for item in check_items])

    return f"""
{template.get("header", "[SOFIA – CONTENT OPPORTUNITY]")}

{template.get("opportunity_id_label", "Opportunity ID")}: {opportunity_id}
{template.get("workspace_label", "Workspace")}: {workspace.get("workspace_id")}
{template.get("country_label", "Country")}: {workspace.get("country")}
{template.get("language_label", "Language")}: {workspace.get("language")}

{template.get("topic_label", "Concept / Topic")}:
{topic}

{template.get("opportunity_type_label", "Opportunity Type")}:
{opportunity_type}

{template.get("recommended_content_type_label", "Recommended Content Type")}:
{recommended_content_type}

{template.get("priority_label", "Priority")}:
{priority}

{template.get("channels_label", "Available Publishing Channels")}:
{channels_text}

{template.get("business_reason_label", "Why Sofia suggests this")}:
{business_reason}

{template.get("risk_notes_label", "Risk / Local Review Notes")}:
{risk_notes_text}

{template.get("examiner_task_label", "Examiner task")}:
{template.get("action", "Please validate the concept before Sofia creates the draft.")}

{template.get("check_label", "Please check:")}
{check_items_text}

{template.get("button_instruction", "Use the buttons below to approve or request changes.")}

""".strip()


def get_button_labels(language):
    language = str(language or "en").lower()

    if language.startswith("pt-br"):
        return {
            "approve": "✅ Aprovar",
            "modify": "✏️ Modificar",
            "reject_delete": "🗑️ Rejeitar/Excluir",
        }

    if language.startswith("pt"):
        return {
            "approve": "✅ Aprovar",
            "modify": "✏️ Modificar",
            "reject_delete": "🗑️ Rejeitar/Eliminar",
        }

    if language.startswith("es"):
        return {
            "approve": "✅ Aprobar",
            "modify": "✏️ Modificar",
            "reject_delete": "🗑️ Rechazar/Eliminar",
        }

    if language.startswith("fr"):
        return {
            "approve": "✅ Approuver",
            "modify": "✏️ Modifier",
            "reject_delete": "🗑️ Rejeter/Supprimer",
        }

    return {
        "approve": "✅ Approve",
        "modify": "✏️ Modify",
        "reject_delete": "🗑️ Reject/Delete",
    }


def build_decision_keyboard(opportunity_id, workspace_id, language="en"):
    labels = get_button_labels(language)

    return {
        "inline_keyboard": [
            [
                {"text": labels["approve"], "callback_data": f"APPROVE|{workspace_id}|{opportunity_id}"},
                {"text": labels["modify"], "callback_data": f"MODIFY_PROMPT|{workspace_id}|{opportunity_id}"},
                {"text": labels["reject_delete"], "callback_data": f"REJECT_PROMPT|{workspace_id}|{opportunity_id}"},
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
        print("  python app/notify_opportunity_review.py WORKSPACE_ID --preview")
        print("  python app/notify_opportunity_review.py WORKSPACE_ID --send")
        print("Example:")
        print("  python app/notify_opportunity_review.py local.ao --send")
        return

    workspace_id = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "--preview"

    if mode not in ["--preview", "--send"]:
        print("Invalid mode. Use --preview or --send.")
        return

    if not TEMPLATES_PATH.exists():
        print(f"Missing template file: {TEMPLATES_PATH}")
        return

    workspaces = load_json(WORKSPACES_PATH)
    workspace = find_workspace(workspaces, workspace_id)

    if not workspace:
        print(f"Workspace not found: {workspace_id}")
        return
    
    if not is_workspace_active(workspace_id):
        print(f"Sofia workspace inactive for {workspace_id}. No opportunity notification sent.")
        return

    folder_path = workspace.get("folder_path", "")
    opportunities_path = ROOT / folder_path / "external_opportunities.json"

    if not opportunities_path.exists():
        print(f"external_opportunities.json not found: {opportunities_path}")
        return

    opportunities_data = load_json(opportunities_path)
    opportunities = opportunities_data.get("opportunities", [])

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

    pending_opportunities = [
        opp for opp in opportunities
        if opp.get("status") == "validated"
        and opp.get("review_status") in ["pending_examiner", "pending", "pending_examiner_review"]
        and opp.get("telegram_notified") is not True
    ]

    if not pending_opportunities:
        print("No pending opportunity review notifications.")
        return

    processed_count = 0

    for opportunity in pending_opportunities:
        message = build_message(opportunity, workspace)
        opportunity_id = opportunity.get("id") or opportunity.get("opportunity_id")
        keyboard = build_decision_keyboard(
            opportunity_id,
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
            print("Telegram opportunity message sent with buttons.")

            opportunity["telegram_notified"] = True
            opportunity["telegram_notified_at"] = now_iso()
            opportunity["updated_at"] = now_iso()

        processed_count += 1

    if mode == "--send":
        save_json(opportunities_path, opportunities_data)

    print(f"\nOpportunity notifications processed: {processed_count}")
    print(f"Mode: {mode}")


if __name__ == "__main__":
    main()
