import json
import os
import re
import subprocess
import time
from pathlib import Path
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

import notify_examiner_review
import notify_opportunity_review


SOFIA_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = SOFIA_ROOT / ".env"
WORKSPACES_PATH = SOFIA_ROOT / "data" / "workspaces.json"
STATE_PATH = SOFIA_ROOT / "logs" / "telegram_listener_state.json"
LOG_PATH = SOFIA_ROOT / "logs" / "telegram_listener.log"
ACTIVATION_PATH = SOFIA_ROOT / "data" / "workspace_activation.json"

load_dotenv(ENV_PATH, override=True)


VALID_REPLY_RE = re.compile(
    r"^(APPROVE|MODIFY|REVISE|REJECT)\s+(?:(\S+)\s+)?([A-Z]+-[A-Z0-9-]+|DRAFT-\d+)(?::\s*(.*))?$",
    re.IGNORECASE,
)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_admin_user_ids():
    raw = os.getenv("SOFIA_TELEGRAM_ADMIN_USER_IDS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def is_admin_user(user_id):
    return str(user_id) in get_admin_user_ids()


def load_activation_state():
    return load_json(ACTIVATION_PATH, {"workspaces": {}, "updated_at": None})


def save_activation_state(data):
    save_json(ACTIVATION_PATH, data)


def get_workspace_label(workspace_id):
    data = load_json(WORKSPACES_PATH, {"workspaces": []})

    for workspace in data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            country = workspace.get("country") or workspace.get("country_name") or ""
            domain = workspace.get("domain") or workspace.get("site_url") or workspace.get("site_target") or ""
            label_parts = [workspace_id]

            if country:
                label_parts.append(country)

            if domain:
                label_parts.append(domain)

            return " | ".join(label_parts)

    return workspace_id


def workspace_exists(workspace_id):
    data = load_json(WORKSPACES_PATH, {"workspaces": []})

    for workspace in data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return True

    return False


def set_workspace_active(workspace_id, active, admin_user_id, admin_name=""):
    state = load_activation_state()

    if "workspaces" not in state:
        state["workspaces"] = {}

    timestamp = now_iso()

    state["workspaces"][workspace_id] = {
        "external_opportunities_active": active,
        "updated_at": timestamp,
        "updated_by_telegram_user_id": str(admin_user_id),
        "updated_by_name": admin_name,
    }
    state["updated_at"] = timestamp

    save_activation_state(state)


def is_workspace_active(workspace_id):
    state = load_activation_state()
    workspace_state = state.get("workspaces", {}).get(workspace_id)

    if not workspace_state:
        return False

    return workspace_state.get("external_opportunities_active") is True


def format_workspace_status(workspace_id):
    active = is_workspace_active(workspace_id)
    status = "external opportunities active ✅" if active else "external opportunities inactive ⛔"
    return f"{workspace_id}: {status}"


def handle_admin_command(msg):
    text = msg.get("text", "").strip()
    user_id = msg.get("from_id") or msg.get("from_user_id")

    if not text.upper().startswith("SOFIA"):
        return False

    if not is_admin_user(user_id):
        send_telegram_message(
            get_bot_token(),
            msg["chat_id"],
            "⚠️ This Sofia admin command is restricted.",
            reply_to_message_id=msg.get("message_id"),
        )
        return True

    parts = text.split()
    command = parts[1].upper() if len(parts) >= 2 else "HELP"
    admin_name = msg.get("from_name") or msg.get("from_username") or ""

    if command in ["HELP", "COMMANDS"]:
        response = (
            "Sofia admin commands:\n\n"
            "SOFIA STATUS\n"
            "SOFIA STATUS local.es\n"
            "SOFIA ACTIVATE local.es\n"
            "SOFIA DEACTIVATE local.es\n"
            "SOFIA ACTIVE LIST"
        )

    elif command == "STATUS":
        if len(parts) >= 3:
            workspace_id = parts[2]
            if not workspace_exists(workspace_id):
                response = f"⚠️ Workspace not found: {workspace_id}"
            else:
                response = (
                    "Sofia workspace status:\n\n"
                    f"{format_workspace_status(workspace_id)}\n"
                    f"{get_workspace_label(workspace_id)}"
                )
        else:
            state = load_activation_state()
            active_items = []

            for workspace_id, info in state.get("workspaces", {}).items():
                if info.get("sofia_active") is True:
                    active_items.append(f"- {get_workspace_label(workspace_id)}")

            if active_items:
                response = "Sofia active workspaces:\n\n" + "\n".join(active_items)
            else:
                response = "No Sofia workspaces are currently active."

    elif command == "ACTIVATE":
        if len(parts) < 3:
            response = "⚠️ Please specify a workspace ID.\nExample: SOFIA ACTIVATE local.es"
        else:
            workspace_id = parts[2]
            if not workspace_exists(workspace_id):
                response = f"⚠️ Workspace not found: {workspace_id}"
            else:
                set_workspace_active(workspace_id, True, user_id, admin_name)
                response = (
                    "✅ External opportunities activated\n\n"
                    f"Workspace: {workspace_id}\n"
                    f"{get_workspace_label(workspace_id)}\n\n"
                    "Sofia may now suggest external content opportunities for this workspace."
                )

    elif command in ["DEACTIVATE", "DESACTIVATE"]:
        if len(parts) < 3:
            response = "⚠️ Please specify a workspace ID.\nExample: SOFIA DEACTIVATE local.es"
        else:
            workspace_id = parts[2]
            if not workspace_exists(workspace_id):
                response = f"⚠️ Workspace not found: {workspace_id}"
            else:
                set_workspace_active(workspace_id, False, user_id, admin_name)
                response = (
                    "⛔ External opportunities deactivated\n\n"
                    f"Workspace: {workspace_id}\n"
                    f"{get_workspace_label(workspace_id)}\n\n"
                    "Sofia will not proactively suggest external content opportunities for this workspace."
                )

    elif command == "ACTIVE" and len(parts) >= 3 and parts[2].upper() == "LIST":
        state = load_activation_state()
        active_items = []

        for workspace_id, info in state.get("workspaces", {}).items():
            if info.get("sofia_active") is True:
                active_items.append(f"- {get_workspace_label(workspace_id)}")

        if active_items:
            response = "Sofia active workspaces:\n\n" + "\n".join(active_items)
        else:
            response = "No Sofia workspaces are currently active."

    else:
        response = (
            "⚠️ Unknown Sofia admin command.\n\n"
            "Try:\n"
            "SOFIA STATUS\n"
            "SOFIA ACTIVATE local.es\n"
            "SOFIA DEACTIVATE local.es"
        )

    send_telegram_message(
        get_bot_token(),
        msg["chat_id"],
        response,
        reply_to_message_id=msg.get("message_id"),
    )

    return True


def log(message):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"{now_iso()} | {message}"
    print(line)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def normalize_language(language):
    if not language:
        return "en"

    language = str(language).lower()

    if language.startswith("pt-br"):
        return "pt-BR"
    if language.startswith("pt"):
        return "pt-PT"
    if language.startswith("es"):
        return "es"
    if language.startswith("fr"):
        return "fr"
    if language.startswith("en"):
        return "en"

    return "en"


def get_workspace_by_id(workspace_id):
    data = load_json(WORKSPACES_PATH, {"workspaces": []})

    for workspace in data.get("workspaces", []):
        if workspace.get("workspace_id") == workspace_id:
            return workspace

    return {}


def get_ui_text(workspace_id):
    workspace = get_workspace_by_id(workspace_id)
    lang = normalize_language(workspace.get("language", "en"))

    texts = {
        "en": {
            "approve": "✅ Approve",
            "revise": "✏️ Revise",
            "modify": "✏️ Modify",
            "reject_delete": "🗑️ Reject/Delete",
            "never": "🚫 Never suggest again",
            "skip": "⏳ Skip for now",
            "angle": "🔄 Suggest different angle",
            "cancel": "❌ Cancel",
            "revise_prompt": "✏️ Please send your revision instructions using this format:\n\nREVISE {item_id}: explain what Sofia should change\n\nExample:\nREVISE {item_id}: mention examiner travel outside Luanda.",
            "modify_prompt": "✏️ Please send your modification instructions using this format:\n\nMODIFY {item_id}: explain what Sofia should change\n\nExample:\nMODIFY {item_id}: focus this opportunity on corporate fraud instead of personal relationship cases.",
            "reject_prompt": "🗑️ Are you sure you want to reject/delete this opportunity?\n\nOpportunity: {item_id}\n\nPlease choose how Sofia should handle similar content in the future:",
        },
        "pt-PT": {
            "approve": "✅ Aprovar",
            "revise": "✏️ Rever",
            "modify": "✏️ Modificar",
            "reject_delete": "🗑️ Rejeitar/Eliminar",
            "never": "🚫 Nunca sugerir novamente",
            "skip": "⏳ Ignorar por agora",
            "angle": "🔄 Sugerir outro ângulo",
            "cancel": "❌ Cancelar",
            "revise_prompt": "✏️ Por favor, envie as instruções de revisão usando este formato:\n\nREVISE {item_id}: explique o que a Sofia deve alterar\n\nExemplo:\nREVISE {item_id}: mencionar que testes fora de Luanda exigem coordenação de deslocação.",
            "modify_prompt": "✏️ Por favor, envie as instruções de modificação usando este formato:\n\nMODIFY {item_id}: explique o que a Sofia deve alterar\n\nExemplo:\nMODIFY {item_id}: focar esta oportunidade em fraude corporativa em vez de casos de relacionamento pessoal.",
            "reject_prompt": "🗑️ Tem a certeza de que deseja rejeitar/eliminar esta oportunidade?\n\nOportunidade: {item_id}\n\nEscolha como a Sofia deve tratar conteúdos semelhantes no futuro:",
        },
        "pt-BR": {
            "approve": "✅ Aprovar",
            "revise": "✏️ Revisar",
            "modify": "✏️ Modificar",
            "reject_delete": "🗑️ Rejeitar/Excluir",
            "never": "🚫 Nunca sugerir novamente",
            "skip": "⏳ Ignorar por enquanto",
            "angle": "🔄 Sugerir outro ângulo",
            "cancel": "❌ Cancelar",
            "revise_prompt": "✏️ Por favor, envie as instruções de revisão usando este formato:\n\nREVISE {item_id}: explique o que a Sofia deve alterar\n\nExemplo:\nREVISE {item_id}: mencionar que testes fora da cidade exigem coordenação de deslocamento.",
            "modify_prompt": "✏️ Por favor, envie as instruções de modificação usando este formato:\n\nMODIFY {item_id}: explique o que a Sofia deve alterar\n\nExemplo:\nMODIFY {item_id}: focar esta oportunidade em fraude corporativa em vez de casos pessoais.",
            "reject_prompt": "🗑️ Tem certeza de que deseja rejeitar/excluir esta oportunidade?\n\nOportunidade: {item_id}\n\nEscolha como a Sofia deve tratar conteúdos semelhantes no futuro:",
        },
        "es": {
            "approve": "✅ Aprobar",
            "revise": "✏️ Revisar",
            "modify": "✏️ Modificar",
            "reject_delete": "🗑️ Rechazar/Eliminar",
            "never": "🚫 No sugerir de nuevo",
            "skip": "⏳ Omitir por ahora",
            "angle": "🔄 Sugerir otro enfoque",
            "cancel": "❌ Cancelar",
            "revise_prompt": "✏️ Por favor, envíe las instrucciones de revisión usando este formato:\n\nREVISE {item_id}: explique lo que Sofia debe cambiar\n\nEjemplo:\nREVISE {item_id}: mencionar que las pruebas fuera de la ciudad requieren coordinación de desplazamiento.",
            "modify_prompt": "✏️ Por favor, envíe las instrucciones de modificación usando este formato:\n\nMODIFY {item_id}: explique lo que Sofia debe cambiar\n\nEjemplo:\nMODIFY {item_id}: enfocar esta oportunidad en fraude corporativo en lugar de casos personales.",
            "reject_prompt": "🗑️ ¿Está seguro de que desea rechazar/eliminar esta oportunidad?\n\nOportunidad: {item_id}\n\nElija cómo debe Sofia tratar contenidos similares en el futuro:",
        },
        "fr": {
            "approve": "✅ Approuver",
            "revise": "✏️ Réviser",
            "modify": "✏️ Modifier",
            "reject_delete": "🗑️ Rejeter/Supprimer",
            "never": "🚫 Ne plus suggérer",
            "skip": "⏳ Ignorer pour l’instant",
            "angle": "🔄 Suggérer un autre angle",
            "cancel": "❌ Annuler",
            "revise_prompt": "✏️ Veuillez envoyer vos instructions de révision avec ce format :\n\nREVISE {item_id}: expliquez ce que Sofia doit modifier\n\nExemple :\nREVISE {item_id}: mentionner que les tests hors de la ville nécessitent une coordination du déplacement.",
            "modify_prompt": "✏️ Veuillez envoyer vos instructions de modification avec ce format :\n\nMODIFY {item_id}: expliquez ce que Sofia doit modifier\n\nExemple :\nMODIFY {item_id}: orienter cette opportunité vers la fraude d’entreprise plutôt que les cas personnels.",
            "reject_prompt": "🗑️ Êtes-vous sûr de vouloir rejeter/supprimer cette opportunité ?\n\nOpportunité : {item_id}\n\nChoisissez comment Sofia doit traiter les contenus similaires à l’avenir :",
        },
    }

    return texts.get(lang, texts["en"])


def get_bot_token():
    token = os.getenv("SOFIA_TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Missing SOFIA_TELEGRAM_BOT_TOKEN in .env")
    return token.strip().strip('"').strip("'")


def load_workspaces_by_chat_id():
    data = load_json(WORKSPACES_PATH, {"workspaces": []})
    mapping = {}

    for workspace in data.get("workspaces", []):
        chat_id = workspace.get("telegram_group_id")
        workspace_id = workspace.get("workspace_id")

        if chat_id is None or not workspace_id:
            continue

        mapping.setdefault(str(chat_id), []).append(workspace_id)

    return mapping


def get_updates(bot_token, offset=None, timeout=30):
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    payload = {
        "timeout": timeout,
        "allowed_updates": ["message", "callback_query"],
    }

    if offset is not None:
        payload["offset"] = offset

    response = requests.get(url, params=payload, timeout=timeout + 10)
    response.raise_for_status()

    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data)

    return data.get("result", [])


def send_telegram_message(bot_token, chat_id, text, reply_to_message_id=None, reply_markup=None):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text,
    }

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    if reply_markup:
        payload["reply_markup"] = reply_markup

    response = requests.post(url, json=payload, timeout=20)
    response.raise_for_status()

    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data)

    return data


def answer_callback_query(bot_token, callback_query_id, text="Sofia is processing your decision."):
    url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"

    try:
        response = requests.post(
            url,
            json={
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": False,
            },
            timeout=20,
        )

        data = response.json()

        if not data.get("ok"):
            log(f"WARNING answerCallbackQuery failed: {data}")
            return False

        return True

    except Exception as e:
        log(f"WARNING answerCallbackQuery exception: {type(e).__name__}")
        return False


def build_decision_keyboard(item_id, workspace_id):
    item_id = str(item_id)
    t = get_ui_text(workspace_id)

    if item_id.startswith("OPP-"):
        return {
            "inline_keyboard": [
                [
                    {"text": t["approve"], "callback_data": f"APPROVE|{workspace_id}|{item_id}"},
                    {"text": t["modify"], "callback_data": f"MODIFY_PROMPT|{workspace_id}|{item_id}"},
                    {"text": t["reject_delete"], "callback_data": f"REJECT_PROMPT|{workspace_id}|{item_id}"},
                ]
            ]
        }

    return {
        "inline_keyboard": [
            [
                {"text": t["approve"], "callback_data": f"APPROVE|{workspace_id}|{item_id}"},
                {"text": t["revise"], "callback_data": f"REVISE_PROMPT|{workspace_id}|{item_id}"},
            ]
        ]
    }


def build_opportunity_reject_confirmation_keyboard(opportunity_id, workspace_id):
    t = get_ui_text(workspace_id)

    return {
        "inline_keyboard": [
            [
                {
                    "text": t["never"],
                    "callback_data": f"REJECT_NEVER|{workspace_id}|{opportunity_id}"
                }
            ],
            [
                {
                    "text": t["skip"],
                    "callback_data": f"REJECT_SKIP|{workspace_id}|{opportunity_id}"
                }
            ],
            [
                {
                    "text": t["angle"],
                    "callback_data": f"REJECT_ANGLE|{workspace_id}|{opportunity_id}"
                }
            ],
            [
                {
                    "text": t["cancel"],
                    "callback_data": f"REJECT_CANCEL|{workspace_id}|{opportunity_id}"
                }
            ]
        ]
    }


def extract_message(update):
    message = update.get("message")
    if not message:
        return None

    text = message.get("text", "")
    chat = message.get("chat", {})
    from_user = message.get("from", {})

    return {
        "update_id": update.get("update_id"),
        "message_id": message.get("message_id"),
        "chat_id": str(chat.get("id")),
        "chat_title": chat.get("title", ""),
        "text": text.strip(),
        "from_id": str(from_user.get("id", "")),
        "from_username": from_user.get("username", ""),
        "from_name": " ".join(
            p for p in [
                from_user.get("first_name", ""),
                from_user.get("last_name", ""),
            ]
            if p
        ).strip(),
    }


def is_valid_sofia_reply(text):
    return bool(VALID_REPLY_RE.fullmatch(text.strip()))


def resolve_workspace_from_reply(chat_id, text, workspace_by_chat_id):
    workspaces = workspace_by_chat_id.get(str(chat_id), [])

    if not workspaces:
        return None, text, "unmapped_chat"

    parsed = VALID_REPLY_RE.fullmatch(text.strip())
    if not parsed:
        return None, text, "invalid_format"

    decision = parsed.group(1).upper()
    possible_workspace_id = parsed.group(2)
    item_id = parsed.group(3).upper()
    comment = parsed.group(4) or ""

    if len(workspaces) == 1:
        clean_reply = f"{decision} {item_id}"
        if comment:
            clean_reply += f": {comment}"
        return workspaces[0], clean_reply, None

    if possible_workspace_id and possible_workspace_id in workspaces:
        clean_reply = f"{decision} {item_id}"
        if comment:
            clean_reply += f": {comment}"
        return possible_workspace_id, clean_reply, None

    return None, text, "workspace_required"


def process_decision(workspace_id, reply_text):
    cmd = [
        "python3",
        str(SOFIA_ROOT / "app" / "process_examiner_decision.py"),
        workspace_id,
        reply_text,
    ]

    result = subprocess.run(
        cmd,
        cwd=str(SOFIA_ROOT),
        text=True,
        capture_output=True,
    )

    combined_output = ""

    if result.stdout:
        combined_output += result.stdout
        for line in result.stdout.strip().splitlines():
            log(f"PROCESS STDOUT | {line}")

    if result.stderr:
        combined_output += "\n" + result.stderr
        for line in result.stderr.strip().splitlines():
            log(f"PROCESS STDERR | {line}")

    failure_signals = [
        "not found",
        "invalid",
        "could not parse",
        "auto step failed",
        "pipeline failed",
        "wordpress pipeline failed",
        "wordpress update/upload failed",
        "publication preparation was blocked",
        "validation status: failed",
        "no wordpress/platform draft was prepared",
    ]

    stdout_lower = result.stdout.lower() if result.stdout else ""
    stderr_lower = result.stderr.lower() if result.stderr else ""

    for signal in failure_signals:
        if signal in stdout_lower or signal in stderr_lower:
            log(f"Detected logical failure: {signal}")
            return False, combined_output

    return result.returncode == 0, combined_output


def send_next_pending_item(bot_token, chat_id, workspace_id):
    workspaces_data = load_json(WORKSPACES_PATH, {"workspaces": []})
    workspace = None

    for w in workspaces_data.get("workspaces", []):
        if w.get("workspace_id") == workspace_id:
            workspace = w
            break

    if not workspace:
        log(f"No workspace found for next item: {workspace_id}")
        return False

    # Priority 1: pending drafts
    review_queue_path = SOFIA_ROOT / workspace["review_queue_path"]

    if review_queue_path.exists():
        review_queue = load_json(review_queue_path, {"review_items": []})

        for item in review_queue.get("review_items", []):
            if (
                item.get("status") == "pending_review"
                and item.get("telegram_notified") is not True
            ):
                item_id = item.get("draft_id")
                message = notify_examiner_review.build_message(item, workspace)
                keyboard = build_decision_keyboard(item_id, workspace_id)

                send_telegram_message(
                    bot_token,
                    chat_id,
                    message,
                    reply_markup=keyboard,
                )

                item["telegram_notified"] = True
                item["telegram_notified_at"] = now_iso()
                item["updated_at"] = now_iso()

                save_json(review_queue_path, review_queue)

                log(f"Sent next pending draft: {item_id} workspace={workspace_id}")
                return True

    # Priority 2: pending opportunities
    opportunities_path = SOFIA_ROOT / workspace["folder_path"] / "external_opportunities.json"

    if opportunities_path.exists():
        opportunities_data = load_json(opportunities_path, {"opportunities": []})

        for opportunity in opportunities_data.get("opportunities", []):
            if opportunity.get("telegram_notified") is True:
                continue

            status = opportunity.get("status")
            review_status = opportunity.get("review_status")

            if (
                status not in ["pending_review", "needs_review", "prevalidated", "validated"]
                and review_status not in ["pending_review", "pending_examiner_review", "pending_examiner", "pending"]
            ):
                continue

            opportunity_id = opportunity.get("id") or opportunity.get("opportunity_id")
            message = notify_opportunity_review.build_message(opportunity, workspace)
            keyboard = build_decision_keyboard(opportunity_id, workspace_id)

            send_telegram_message(
                bot_token,
                chat_id,
                message,
                reply_markup=keyboard,
            )

            opportunity["telegram_notified"] = True
            opportunity["telegram_notified_at"] = now_iso()
            opportunity["updated_at"] = now_iso()

            save_json(opportunities_path, opportunities_data)

            log(f"Sent next pending opportunity: {opportunity_id} workspace={workspace_id}")
            return True

    log(f"No pending next item found for workspace={workspace_id}")
    return False


def extract_wordpress_result(process_output):
    if not process_output:
        return {}

    wordpress_id = None
    wordpress_link = None
    wordpress_status = None

    for line in process_output.splitlines():
        clean = line.strip()

        if clean.startswith("WordPress ID:"):
            wordpress_id = clean.replace("WordPress ID:", "").strip()

        elif clean.startswith("Link:"):
            wordpress_link = clean.replace("Link:", "").strip()

        elif "WordPress draft updated successfully" in clean:
            wordpress_status = "updated"

        elif "WordPress draft created successfully" in clean:
            wordpress_status = "created"

    return {
        "wordpress_id": wordpress_id,
        "wordpress_link": wordpress_link,
        "wordpress_status": wordpress_status,
    }


def send_processing_result(chat_id, reply_to_message_id, workspace_id, item_id, decision, ok, process_output=""):
    is_draft = str(item_id).startswith("DRAFT-")
    is_opportunity = str(item_id).startswith("OPP-")

    wp_result = extract_wordpress_result(process_output)

    if ok and is_draft and decision == "APPROVE":
        wordpress_status = wp_result.get("wordpress_status")
        wordpress_id = wp_result.get("wordpress_id")
        wordpress_link = wp_result.get("wordpress_link")

        prepared_lines = []

        if wordpress_status:
            prepared_lines.append(f"- WordPress draft {wordpress_status} successfully")
        else:
            prepared_lines.append("- WordPress / website draft: prepared or updated if configured")

        if wordpress_id:
            prepared_lines.append(f"- WordPress ID: {wordpress_id}")

        if wordpress_link:
            prepared_lines.append(f"- Draft link: {wordpress_link}")

        prepared_text = "\n".join(prepared_lines)

        text = (
            "✅ Draft approved and prepared for publication\n\n"
            f"Workspace: {workspace_id}\n"
            f"Draft: {item_id}\n\n"
            "Prepared:\n"
            f"{prepared_text}\n\n"
            "Final live publication has NOT been done automatically.\n"
            "Please review the draft in WordPress and publish manually when ready."
        )

    elif ok and is_draft and decision == "REVISE":
        text = (
            "✅ Revision request processed\n\n"
            f"Workspace: {workspace_id}\n"
            f"Draft: {item_id}\n\n"
            "Sofia has processed the revision request and will return the draft for review."
        )

    elif ok and is_opportunity and decision == "APPROVE":
        text = (
            "✅ Opportunity approved\n\n"
            f"Workspace: {workspace_id}\n"
            f"Opportunity: {item_id}\n\n"
            "Sofia has converted the approved opportunity into the next content workflow step."
        )

    elif ok:
        text = (
            "✅ Sofia decision processed\n\n"
            f"Workspace: {workspace_id}\n"
            f"Item: {item_id}\n"
            f"Decision: {decision}"
        )

    else:
        if is_draft and decision == "APPROVE":
            text = (
                "⚠️ Draft approved, but publication preparation was blocked\n\n"
                f"Workspace: {workspace_id}\n"
                f"Draft: {item_id}\n\n"
                "The examiner approval was received, but Sofia could not prepare the publication draft yet "
                "because the content still needs internal SEO/quality refinement.\n\n"
                "No WordPress/platform draft has been prepared.\n"
                "Sofia should continue refining the content until validation passes."
            )
        else:
            text = (
                "⚠️ Sofia could not process this decision.\n\n"
                f"Workspace: {workspace_id}\n"
                f"Item: {item_id}\n"
                f"Decision: {decision}\n\n"
                "Please check that the ID exists and the format is correct."
            )

    send_telegram_message(
        get_bot_token(),
        chat_id,
        text,
        reply_to_message_id=reply_to_message_id,
    )


def handle_callback(update, workspace_by_chat_id):
    callback = update.get("callback_query")
    if not callback:
        return

    bot_token = get_bot_token()
    callback_id = callback.get("id")
    data = callback.get("data", "")
    from_user = callback.get("from", {})
    message = callback.get("message", {})
    chat = message.get("chat", {})
    chat_id = str(chat.get("id"))
    message_id = message.get("message_id")

    if callback_id:
        answer_callback_query(bot_token, callback_id)

    parts = data.split("|")

    if len(parts) == 3:
        decision, workspace_id, item_id = parts
    elif len(parts) == 2:
        decision, item_id = parts
        workspaces = workspace_by_chat_id.get(chat_id, [])
        if len(workspaces) == 1:
            workspace_id = workspaces[0]
        else:
            send_telegram_message(
                bot_token,
                chat_id,
                "⚠️ This button cannot be processed because the workspace is ambiguous.",
                reply_to_message_id=message_id,
            )
            return
    else:
        log(f"Invalid callback data: {data!r}")
        return

    decision = decision.upper()
    item_id = item_id.upper()
    t = get_ui_text(workspace_id)

    if decision == "REVISE_PROMPT":
        log(
            "CALLBACK revise prompt "
            f"workspace={workspace_id} chat_id={chat_id} item={item_id}"
        )

        instruction = t["revise_prompt"].format(item_id=item_id)

        send_telegram_message(
            bot_token,
            chat_id,
            instruction,
            reply_to_message_id=message_id,
        )
        return

    if decision == "MODIFY_PROMPT":
        log(
            "CALLBACK modify prompt "
            f"workspace={workspace_id} chat_id={chat_id} item={item_id}"
        )

        if not item_id.startswith("OPP-"):
            send_telegram_message(
                bot_token,
                chat_id,
                "⚠️ Modify is currently only available for opportunities.",
                reply_to_message_id=message_id,
            )
            return

        instruction = t["modify_prompt"].format(item_id=item_id)

        send_telegram_message(
            bot_token,
            chat_id,
            instruction,
            reply_to_message_id=message_id,
        )
        return

    if decision == "REJECT_PROMPT":
        log(
            "CALLBACK reject prompt "
            f"workspace={workspace_id} chat_id={chat_id} item={item_id}"
        )

        if not item_id.startswith("OPP-"):
            send_telegram_message(
                bot_token,
                chat_id,
                "⚠️ Reject/Delete confirmation is currently only available for opportunities.",
                reply_to_message_id=message_id,
            )
            return

        text = t["reject_prompt"].format(item_id=item_id)

        keyboard = build_opportunity_reject_confirmation_keyboard(
            item_id,
            workspace_id
        )

        send_telegram_message(
            bot_token,
            chat_id,
            text,
            reply_to_message_id=message_id,
            reply_markup=keyboard,
        )
        return

    if decision in ["REJECT_NEVER", "REJECT_SKIP", "REJECT_ANGLE", "REJECT_CANCEL"]:
        log(
            "CALLBACK opportunity reject option "
            f"workspace={workspace_id} chat_id={chat_id} item={item_id} option={decision}"
        )

        if decision == "REJECT_CANCEL":
            send_telegram_message(
                bot_token,
                chat_id,
                f"{t['cancel']} Rejeição cancelada.\n\nOportunidade: {item_id}"
                if normalize_language(get_workspace_by_id(workspace_id).get("language", "en")).startswith("pt")
                else f"{t['cancel']} Rejection cancelled.\n\nOpportunity: {item_id}",
                reply_to_message_id=message_id,
            )
            return

        preference_labels = {
            "REJECT_NEVER": "never_suggest_again",
            "REJECT_SKIP": "skip_for_now",
            "REJECT_ANGLE": "suggest_different_angle",
        }

        preference = preference_labels.get(decision, "rejected")
        reply_text = f"REJECT {item_id}: {preference}"

        ok, process_output = process_decision(workspace_id, reply_text)

        lang = normalize_language(get_workspace_by_id(workspace_id).get("language", "en"))

        if ok:
            if decision == "REJECT_NEVER":
                if lang.startswith("pt"):
                    text = (
                        "🚫 Oportunidade rejeitada.\n\n"
                        f"Workspace: {workspace_id}\n"
                        f"Oportunidade: {item_id}\n\n"
                        "A Sofia tentará não sugerir este mesmo tema novamente."
                    )
                elif lang == "es":
                    text = (
                        "🚫 Oportunidad rechazada.\n\n"
                        f"Workspace: {workspace_id}\n"
                        f"Oportunidad: {item_id}\n\n"
                        "Sofia intentará no volver a sugerir este mismo tema."
                    )
                elif lang == "fr":
                    text = (
                        "🚫 Opportunité rejetée.\n\n"
                        f"Workspace: {workspace_id}\n"
                        f"Opportunité : {item_id}\n\n"
                        "Sofia essaiera de ne plus suggérer ce même sujet."
                    )
                else:
                    text = (
                        "🚫 Opportunity rejected.\n\n"
                        f"Workspace: {workspace_id}\n"
                        f"Opportunity: {item_id}\n\n"
                        "Sofia will try not to suggest this same topic again."
                    )

            elif decision == "REJECT_SKIP":
                if lang.startswith("pt"):
                    text = (
                        "⏳ Oportunidade ignorada por agora.\n\n"
                        f"Workspace: {workspace_id}\n"
                        f"Oportunidade: {item_id}\n\n"
                        "A Sofia poderá sugerir conteúdo semelhante mais tarde, se voltar a ser relevante."
                    )
                elif lang == "es":
                    text = (
                        "⏳ Oportunidad omitida por ahora.\n\n"
                        f"Workspace: {workspace_id}\n"
                        f"Oportunidad: {item_id}\n\n"
                        "Sofia podrá sugerir contenido similar más adelante si vuelve a ser relevante."
                    )
                elif lang == "fr":
                    text = (
                        "⏳ Opportunité ignorée pour l’instant.\n\n"
                        f"Workspace: {workspace_id}\n"
                        f"Opportunité : {item_id}\n\n"
                        "Sofia pourra suggérer un contenu similaire plus tard si cela redevient pertinent."
                    )
                else:
                    text = (
                        "⏳ Opportunity skipped for now.\n\n"
                        f"Workspace: {workspace_id}\n"
                        f"Opportunity: {item_id}\n\n"
                        "Sofia may suggest similar content later if it becomes relevant."
                    )

            else:
                if lang.startswith("pt"):
                    text = (
                        "🔄 Oportunidade rejeitada com pedido de outro ângulo.\n\n"
                        f"Workspace: {workspace_id}\n"
                        f"Oportunidade: {item_id}\n\n"
                        "A Sofia deverá procurar um ângulo melhor antes de sugerir este tema novamente."
                    )
                elif lang == "es":
                    text = (
                        "🔄 Oportunidad rechazada con solicitud de otro enfoque.\n\n"
                        f"Workspace: {workspace_id}\n"
                        f"Oportunidad: {item_id}\n\n"
                        "Sofia deberá buscar un mejor enfoque antes de volver a sugerir este tema."
                    )
                elif lang == "fr":
                    text = (
                        "🔄 Opportunité rejetée avec demande d’un autre angle.\n\n"
                        f"Workspace: {workspace_id}\n"
                        f"Opportunité : {item_id}\n\n"
                        "Sofia devra chercher un meilleur angle avant de suggérer à nouveau ce sujet."
                    )
                else:
                    text = (
                        "🔄 Opportunity rejected with request for a different angle.\n\n"
                        f"Workspace: {workspace_id}\n"
                        f"Opportunity: {item_id}\n\n"
                        "Sofia should look for a better angle before suggesting this topic again."
                    )
        else:
            if lang.startswith("pt"):
                text = (
                    "⚠️ A Sofia não conseguiu rejeitar esta oportunidade.\n\n"
                    f"Workspace: {workspace_id}\n"
                    f"Oportunidade: {item_id}"
                )
            elif lang == "es":
                text = (
                    "⚠️ Sofia no pudo rechazar esta oportunidad.\n\n"
                    f"Workspace: {workspace_id}\n"
                    f"Oportunidad: {item_id}"
                )
            elif lang == "fr":
                text = (
                    "⚠️ Sofia n’a pas pu rejeter cette opportunité.\n\n"
                    f"Workspace: {workspace_id}\n"
                    f"Opportunité : {item_id}"
                )
            else:
                text = (
                    "⚠️ Sofia could not reject this opportunity.\n\n"
                    f"Workspace: {workspace_id}\n"
                    f"Opportunity: {item_id}"
                )

        send_telegram_message(
            bot_token,
            chat_id,
            text,
            reply_to_message_id=message_id,
        )

        if ok:
            send_next_pending_item(bot_token, chat_id, workspace_id)

        return

    reply_text = f"{decision} {item_id}"

    log(
        "CALLBACK Sofia decision "
        f"workspace={workspace_id} chat_id={chat_id} "
        f"from={from_user.get('first_name', '')} text={reply_text!r}"
    )

    ok, process_output = process_decision(workspace_id, reply_text)

    send_processing_result(
        chat_id=chat_id,
        reply_to_message_id=message_id,
        workspace_id=workspace_id,
        item_id=item_id,
        decision=decision,
        ok=ok,
        process_output=process_output,
    )

    if ok:
        send_next_pending_item(bot_token, chat_id, workspace_id)


    reply_text = f"{decision} {item_id}"

    log(
        "CALLBACK Sofia decision "
        f"workspace={workspace_id} chat_id={chat_id} "
        f"from={from_user.get('first_name', '')} text={reply_text!r}"
    )

    ok, process_output = process_decision(workspace_id, reply_text)

    send_processing_result(
        chat_id=chat_id,
        reply_to_message_id=message_id,
        workspace_id=workspace_id,
        item_id=item_id,
        decision=decision,
        ok=ok,
        process_output=process_output,
    )

    if ok:
        send_next_pending_item(bot_token, chat_id, workspace_id)


def handle_update(update, workspace_by_chat_id):
    msg = extract_message(update)
    if not msg:
        return

    update_id = msg["update_id"]
    chat_id = msg["chat_id"]
    text = msg["text"]

    if not text:
        return
    
    if handle_admin_command(msg):
        return

    if not is_valid_sofia_reply(text):
        return

    workspace_id, clean_text, error = resolve_workspace_from_reply(
        chat_id,
        text,
        workspace_by_chat_id,
    )

    if error == "unmapped_chat":
        log(
            "IGNORED valid-looking Sofia reply from unmapped Telegram chat "
            f"chat_id={chat_id} chat_title={msg['chat_title']} text={text!r}"
        )
        return

    if error == "workspace_required":
        available = workspace_by_chat_id.get(chat_id, [])
        guidance = (
            "⚠️ This Telegram group manages multiple Sofia workspaces.\n\n"
            "Please include the workspace ID in your reply.\n\n"
            "Examples:\n"
            "APPROVE en.forensics DRAFT-0005\n"
            "REVISE es.forensics DRAFT-0007: change terminology\n\n"
            "Available workspaces:\n"
            + "\n".join(f"- {w}" for w in available)
        )

        send_telegram_message(
            get_bot_token(),
            chat_id,
            guidance,
            reply_to_message_id=msg.get("message_id"),
        )
        return

    log(
        "RECEIVED Sofia decision "
        f"workspace={workspace_id} chat_id={chat_id} "
        f"from={msg['from_name'] or msg['from_username']} text={clean_text!r}"
    )

    ok, process_output = process_decision(workspace_id, clean_text)

    parsed = VALID_REPLY_RE.fullmatch(clean_text.strip())
    decision = parsed.group(1).upper()
    item_id = parsed.group(3).upper()

    if ok:
        log(f"PROCESSED update_id={update_id} workspace={workspace_id}")
    else:
        log(f"FAILED update_id={update_id} workspace={workspace_id}")

    send_processing_result(
        chat_id=chat_id,
        reply_to_message_id=msg.get("message_id"),
        workspace_id=workspace_id,
        item_id=item_id,
        decision=decision,
        ok=ok,
        process_output=process_output,
    )

    if ok:
        send_next_pending_item(
            get_bot_token(),
            chat_id,
            workspace_id,
        )


def main():
    print("=== Sofia Telegram Listener ===\n")

    bot_token = get_bot_token()
    state = load_json(STATE_PATH, {})
    offset = state.get("offset")

    log("Listener started.")
    log(f"State file: {STATE_PATH}")

    while True:
        try:
            workspace_by_chat_id = load_workspaces_by_chat_id()
            updates = get_updates(bot_token, offset=offset)

            for update in updates:
                update_id = update.get("update_id")

                if "callback_query" in update:
                    handle_callback(update, workspace_by_chat_id)
                else:
                    handle_update(update, workspace_by_chat_id)

                if update_id is not None:
                    offset = update_id + 1
                    save_json(STATE_PATH, {"offset": offset, "updated_at": now_iso()})

        except KeyboardInterrupt:
            log("Listener stopped by user.")
            break

        except Exception as e:
            log(f"ERROR {type(e).__name__}: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()