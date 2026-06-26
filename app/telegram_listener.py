import json
import os
import re
import subprocess
import time
import unicodedata
from pathlib import Path
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

import notify_examiner_review
import notify_opportunity_review
import create_internal_opportunity

from parse_examiner_request import parse_examiner_request
from telegram_handlers.coordinator_router import route_examiner_request

from workspace_paths import (
    find_draft_any_workspace,
    get_workspace_draft_registry_path,
)


SOFIA_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = SOFIA_ROOT / ".env"
WORKSPACES_PATH = SOFIA_ROOT / "data" / "workspaces.json"
STATE_PATH = SOFIA_ROOT / "logs" / "telegram_listener_state.json"
PENDING_CONTEXT_PATH = SOFIA_ROOT / "logs" / "telegram_pending_contexts.json"
BUTTON_ACTIONS_PATH = SOFIA_ROOT / "logs" / "telegram_button_actions.json"
PENDING_REVISION_TTL_SECONDS = 60 * 60
LOG_PATH = SOFIA_ROOT / "logs" / "telegram_listener.log"
ACTIVATION_PATH = SOFIA_ROOT / "data" / "workspace_activation.json"
# Deprecated: draft registries are now workspace-level.
GLOBAL_DRAFT_REGISTRY_PATH = SOFIA_ROOT / "sites" / "draft_registry.json"

load_dotenv(ENV_PATH, override=True)


VALID_REPLY_RE = re.compile(
    r"^(APPROVE|MODIFY|REVISE|REJECT|COMPLETE)\s+(?:(\S+)\s+)?([A-Z]+-[A-Z0-9-]+|DRAFT-\d+)(?::\s*(.*))?$",
    re.IGNORECASE,
)

ADMIN_COMMAND_RE = re.compile(
    r"^\s*SOFIA\s+(STATUS|ACTIVATE|DEACTIVATE|DESACTIVATE|ACTIVE|HELP|COMMANDS)\b",
    re.IGNORECASE,
)

INTERNAL_TRIGGER_RE = re.compile(
    r"^\s*SOFIA\s*[,:\-]?\s+("
    r"create|prepare|generate|write|make|"
    r"create\s+a|create\s+an|"
    r"criar|cria|crie|preparar|prepara|prepare|gerar|gera|gere|"
    r"crear|crea|preparar|prepara|generar|genera|"
    r"rédiger|rediger|créer|creer|crée|cree|préparer|preparer|prépare|prepare"
    r")\b",
    re.IGNORECASE,
)

JOB_STATUS_TRIGGER_RE = re.compile(
    r"^\s*sofia\s*[,:\-]?\s+.*("
    r"job|jobs|task|tasks|pending|queued|running|working|failed|failure|error|retry|status|"
    r"tarefa|tarefas|pendente|pendentes|fila|processamento|falhou|falharam|erro|erros|estado|"
    r"trabajo|trabajos|tarea|tareas|pendiente|pendientes|falló|fallaron|estado|"
    r"travail|travaux|tâche|tâches|attente|échec|erreur|statut"
    r")",
    re.IGNORECASE,
)

def normalize_trigger_text(text):
    text = str(text or "")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


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


def load_pending_contexts():
    return load_json(PENDING_CONTEXT_PATH, {"revision": {}})


def save_pending_contexts(data):
    save_json(PENDING_CONTEXT_PATH, data)


def make_pending_revision_key(chat_id, user_id, workspace_id):
    return f"{chat_id}|{user_id}|{workspace_id}"


def cleanup_expired_pending_contexts():
    data = load_pending_contexts()
    now_ts = time.time()
    changed = False

    revision_contexts = data.setdefault("revision", {})

    for key, context in list(revision_contexts.items()):
        expires_at = context.get("expires_at_ts", 0)
        if expires_at and expires_at < now_ts:
            revision_contexts.pop(key, None)
            changed = True

    if changed:
        save_pending_contexts(data)

    return data


def set_pending_revision_context(chat_id, user_id, workspace_id, draft_id):
    data = cleanup_expired_pending_contexts()
    key = make_pending_revision_key(chat_id, user_id, workspace_id)
    now_ts = time.time()

    data.setdefault("revision", {})[key] = {
        "workspace_id": workspace_id,
        "draft_id": draft_id,
        "chat_id": str(chat_id),
        "user_id": str(user_id),
        "created_at": now_iso(),
        "created_at_ts": now_ts,
        "expires_at_ts": now_ts + PENDING_REVISION_TTL_SECONDS,
        "status": "waiting_for_instruction",
    }

    save_pending_contexts(data)


def get_pending_revision_context(chat_id, user_id, workspace_id):
    data = cleanup_expired_pending_contexts()
    key = make_pending_revision_key(chat_id, user_id, workspace_id)
    return data.get("revision", {}).get(key)


def clear_pending_revision_context(chat_id, user_id, workspace_id):
    data = load_pending_contexts()
    key = make_pending_revision_key(chat_id, user_id, workspace_id)

    if key in data.get("revision", {}):
        data["revision"].pop(key, None)
        save_pending_contexts(data)


def load_button_actions():
    return load_json(BUTTON_ACTIONS_PATH, {"actions": {}})


def save_button_actions(data):
    save_json(BUTTON_ACTIONS_PATH, data)


def make_button_action_key(chat_id, message_id, workspace_id, item_id, decision):
    return f"{chat_id}|{message_id}|{workspace_id}|{item_id}|{decision}"


def get_button_action(chat_id, message_id, workspace_id, item_id, decision):
    data = load_button_actions()
    key = make_button_action_key(chat_id, message_id, workspace_id, item_id, decision)
    return data.get("actions", {}).get(key)


def mark_button_action_processed(chat_id, message_id, workspace_id, item_id, decision, user_id=""):
    data = load_button_actions()
    key = make_button_action_key(chat_id, message_id, workspace_id, item_id, decision)

    data.setdefault("actions", {})[key] = {
        "chat_id": str(chat_id),
        "message_id": str(message_id),
        "workspace_id": workspace_id,
        "item_id": item_id,
        "decision": decision,
        "processed_at": now_iso(),
        "processed_by_user_id": str(user_id or ""),
    }

    save_button_actions(data)

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

    if not ADMIN_COMMAND_RE.match(text):
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
            "complete": "✅ Completed",
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
            "complete": "✅ Finalizado",
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
            "complete": "✅ Finalizado",
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
            "complete": "✅ Finalizado",
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
            "complete": "✅ Terminé",
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


def build_button_already_processed_message(workspace_id, item_id):
    workspace = get_workspace_by_id(workspace_id)
    lang = normalize_language(workspace.get("language", "en"))

    if str(item_id).startswith("DRAFT-"):
        item_label_pt = "Rascunho"
        item_label_es = "Borrador"
        item_label_fr = "Brouillon"
        item_label_en = "Draft"
    elif str(item_id).startswith("OPP-"):
        item_label_pt = "Oportunidade"
        item_label_es = "Oportunidad"
        item_label_fr = "Opportunité"
        item_label_en = "Opportunity"
    else:
        item_label_pt = "Item"
        item_label_es = "Item"
        item_label_fr = "Élément"
        item_label_en = "Item"

    if lang.startswith("pt"):
        return (
            "⚠️ Esta ação já foi processada anteriormente.\n\n"
            f"{item_label_pt}: {item_id}\n\n"
            "Nenhuma nova tarefa foi criada."
        )

    if lang == "es":
        return (
            "⚠️ Esta acción ya fue procesada anteriormente.\n\n"
            f"{item_label_es}: {item_id}\n\n"
            "No se creó ninguna tarea nueva."
        )

    if lang == "fr":
        return (
            "⚠️ Cette action a déjà été traitée précédemment.\n\n"
            f"{item_label_fr} : {item_id}\n\n"
            "Aucune nouvelle tâche n’a été créée."
        )

    return (
        "⚠️ This action has already been processed.\n\n"
        f"{item_label_en}: {item_id}\n\n"
        "No new task was created."
    )


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

    if draft_has_wordpress_draft(item_id, workspace_id):
        return {
            "inline_keyboard": [
                [
                    {"text": t.get("complete", "✅ Completed"), "callback_data": f"COMPLETE|{workspace_id}|{item_id}"},
                    {"text": t["revise"], "callback_data": f"REVISE_PROMPT|{workspace_id}|{item_id}"},
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


def is_internal_content_trigger(text):
    normalized = normalize_trigger_text(text)
    return bool(INTERNAL_TRIGGER_RE.match(normalized.strip()))


def resolve_workspace_from_group_for_internal_trigger(chat_id, workspace_by_chat_id):
    workspaces = workspace_by_chat_id.get(str(chat_id), [])

    if not workspaces:
        return None, "unmapped_chat"

    if len(workspaces) == 1:
        return workspaces[0], None

    return None, "workspace_required"


def is_job_status_trigger(text):
    normalized = normalize_trigger_text(text)
    return bool(JOB_STATUS_TRIGGER_RE.match(normalized.strip()))


def resolve_workspace_from_group_for_job_status(chat_id, workspace_by_chat_id):
    workspaces = workspace_by_chat_id.get(str(chat_id), [])

    if not workspaces:
        return None, "unmapped_chat"

    if len(workspaces) == 1:
        return workspaces[0], None

    return None, "workspace_required"


def get_workspace_path_from_id(workspace_id):
    workspace = get_workspace_by_id(workspace_id)

    folder_path = workspace.get("folder_path") or workspace.get("workspace_path")
    if folder_path:
        return SOFIA_ROOT / folder_path

    if workspace_id.startswith("local."):
        country_code = workspace_id.split(".", 1)[1]
        return SOFIA_ROOT / "sites" / "local_sites" / country_code

    return None


def load_job_registry_for_workspace(workspace_id):
    workspace_path = get_workspace_path_from_id(workspace_id)
    if not workspace_path:
        return {"jobs": []}

    path = workspace_path / "job_registry.json"
    return load_json(path, {"jobs": []})


def detect_job_status_filter(text):
    text_lower = str(text or "").lower()

    if any(word in text_lower for word in ["failed", "failure", "error", "falhou", "falharam", "erro", "falló", "fallaron", "échec", "erreur"]):
        return "failed"

    if any(word in text_lower for word in ["retry", "delayed", "retry_pending", "voltar a tentar", "reintentar", "réessayer"]):
        return "retry_pending"

    if any(word in text_lower for word in ["running", "working", "processing", "processamento", "procesando", "traitement"]):
        return "running"

    if any(word in text_lower for word in ["pending", "queued", "fila", "pendente", "pendentes", "pendiente", "pendientes", "attente"]):
        return "queued"

    return "summary"


def build_job_status_message(workspace_id, jobs, status_filter="summary"):
    workspace = get_workspace_by_id(workspace_id)
    lang = normalize_language(workspace.get("language", "en"))

    counts = {
        "queued": 0,
        "running": 0,
        "retry_pending": 0,
        "failed": 0,
        "failed_after_retries": 0,
        "completed": 0,
    }

    for job in jobs:
        status = job.get("status", "unknown")
        if status in counts:
            counts[status] += 1

    if status_filter == "summary":
        selected = [
            job for job in jobs
            if job.get("status") in ["queued", "running", "retry_pending", "failed", "failed_after_retries"]
        ]
    elif status_filter == "failed":
        selected = [
            job for job in jobs
            if job.get("status") in ["failed", "failed_after_retries"]
        ]
    else:
        selected = [
            job for job in jobs
            if job.get("status") == status_filter
        ]

    selected = sorted(
        selected,
        key=lambda job: job.get("updated_at") or job.get("created_at") or "",
        reverse=True,
    )[:8]

    lines = []
    for job in selected:
        lines.append(
            f"- {job.get('job_id')} | {job.get('job_type')} | {job.get('item_id')} | {job.get('status')}"
        )

    recent_text = "\n".join(lines) if lines else "No matching jobs."

    if lang.startswith("pt"):
        return (
            f"📋 Estado das tarefas da Sofia\n\n"
            f"Workspace: {workspace_id}\n\n"
            f"Em fila: {counts['queued']}\n"
            f"Em processamento: {counts['running']}\n"
            f"A aguardar nova tentativa: {counts['retry_pending']}\n"
            f"Falhadas: {counts['failed'] + counts['failed_after_retries']}\n"
            f"Concluídas: {counts['completed']}\n\n"
            f"Tarefas relevantes:\n{recent_text}"
        )

    if lang == "es":
        return (
            f"📋 Estado de las tareas de Sofia\n\n"
            f"Workspace: {workspace_id}\n\n"
            f"En cola: {counts['queued']}\n"
            f"En procesamiento: {counts['running']}\n"
            f"Pendientes de reintento: {counts['retry_pending']}\n"
            f"Fallidas: {counts['failed'] + counts['failed_after_retries']}\n"
            f"Completadas: {counts['completed']}\n\n"
            f"Tareas relevantes:\n{recent_text}"
        )

    if lang == "fr":
        return (
            f"📋 État des tâches de Sofia\n\n"
            f"Workspace : {workspace_id}\n\n"
            f"En file : {counts['queued']}\n"
            f"En traitement : {counts['running']}\n"
            f"En attente de nouvel essai : {counts['retry_pending']}\n"
            f"Échouées : {counts['failed'] + counts['failed_after_retries']}\n"
            f"Terminées : {counts['completed']}\n\n"
            f"Tâches pertinentes :\n{recent_text}"
        )

    return (
        f"📋 Sofia job status\n\n"
        f"Workspace: {workspace_id}\n\n"
        f"Queued: {counts['queued']}\n"
        f"Running: {counts['running']}\n"
        f"Retry pending: {counts['retry_pending']}\n"
        f"Failed: {counts['failed'] + counts['failed_after_retries']}\n"
        f"Completed: {counts['completed']}\n\n"
        f"Relevant jobs:\n{recent_text}"
    )


def handle_job_status_request(msg, workspace_by_chat_id):
    text = msg.get("text", "").strip()

    if not is_job_status_trigger(text):
        return False

    bot_token = get_bot_token()
    chat_id = msg["chat_id"]

    workspace_id, error = resolve_workspace_from_group_for_job_status(
        chat_id,
        workspace_by_chat_id,
    )

    if error == "unmapped_chat":
        workspaces_data = load_json(WORKSPACES_PATH, {"workspaces": []})
        status_filter = detect_job_status_filter(text)

        summary_lines = []
        total_counts = {
            "queued": 0,
            "running": 0,
            "retry_pending": 0,
            "failed": 0,
            "failed_after_retries": 0,
            "completed": 0,
        }

        for workspace in workspaces_data.get("workspaces", []):
            workspace_id = workspace.get("workspace_id")
            if not workspace_id:
                continue

            registry = load_job_registry_for_workspace(workspace_id)
            jobs = registry.get("jobs", [])

            counts = {
                "queued": 0,
                "running": 0,
                "retry_pending": 0,
                "failed": 0,
                "failed_after_retries": 0,
                "completed": 0,
            }

            for job in jobs:
                status = job.get("status", "unknown")
                if status in counts:
                    counts[status] += 1
                    total_counts[status] += 1

            active_count = (
                counts["queued"]
                + counts["running"]
                + counts["retry_pending"]
                + counts["failed"]
                + counts["failed_after_retries"]
            )

            if active_count > 0:
                summary_lines.append(
                    f"- {workspace_id}: "
                    f"queued {counts['queued']}, "
                    f"running {counts['running']}, "
                    f"retry {counts['retry_pending']}, "
                    f"failed {counts['failed'] + counts['failed_after_retries']}"
                )

        if not summary_lines:
            summary_lines.append("- No active or failed Sofia jobs found.")

        response = (
            "📋 Sofia global job status\n\n"
            f"Queued: {total_counts['queued']}\n"
            f"Running: {total_counts['running']}\n"
            f"Retry pending: {total_counts['retry_pending']}\n"
            f"Failed: {total_counts['failed'] + total_counts['failed_after_retries']}\n"
            f"Completed: {total_counts['completed']}\n\n"
            "Workspaces with active/issues:\n"
            + "\n".join(summary_lines[:20])
        )

        send_telegram_message(
            bot_token,
            chat_id,
            response,
            reply_to_message_id=msg.get("message_id"),
        )

        log(
            "SENT global job status response "
            f"chat_id={chat_id} filter={status_filter}"
        )

        return True

    if error == "workspace_required":
        available = workspace_by_chat_id.get(str(chat_id), [])
        send_telegram_message(
            bot_token,
            chat_id,
            (
                "⚠️ This Telegram group manages multiple Sofia workspaces.\n\n"
                "Please mention the workspace you want to check.\n\n"
                "Available workspaces:\n"
                + "\n".join(f"- {w}" for w in available)
            ),
            reply_to_message_id=msg.get("message_id"),
        )
        return True

    registry = load_job_registry_for_workspace(workspace_id)
    jobs = registry.get("jobs", [])
    status_filter = detect_job_status_filter(text)

    response = build_job_status_message(
        workspace_id=workspace_id,
        jobs=jobs,
        status_filter=status_filter,
    )

    send_telegram_message(
        bot_token,
        chat_id,
        response,
        reply_to_message_id=msg.get("message_id"),
    )

    log(
        "SENT job status response "
        f"workspace={workspace_id} chat_id={chat_id} filter={status_filter}"
    )

    return True


def handle_internal_content_trigger(msg, workspace_by_chat_id):
    text = msg.get("text", "").strip()

    if not is_internal_content_trigger(text):
        return False

    bot_token = get_bot_token()
    chat_id = msg["chat_id"]

    workspace_id, error = resolve_workspace_from_group_for_internal_trigger(
        chat_id,
        workspace_by_chat_id,
    )

    if error == "unmapped_chat":
        log(
            "IGNORED internal trigger from unmapped Telegram chat "
            f"chat_id={chat_id} chat_title={msg.get('chat_title', '')} text={text!r}"
        )
        send_telegram_message(
            bot_token,
            chat_id,
            "⚠️ This Telegram group is not mapped to a Sofia workspace yet.",
            reply_to_message_id=msg.get("message_id"),
        )
        return True

    if error == "workspace_required":
        available = workspace_by_chat_id.get(chat_id, [])
        guidance = (
            "⚠️ This Telegram group manages multiple Sofia workspaces.\n\n"
            "Please include the workspace ID in the request for now.\n\n"
            "Examples:\n"
            "Sofia en.forensics create a landing page about corporate polygraph services\n"
            "Sofia es.forensics create a landing page about prueba de polígrafo empresarial\n\n"
            "Available workspaces:\n"
            + "\n".join(f"- {w}" for w in available)
        )

        send_telegram_message(
            bot_token,
            chat_id,
            guidance,
            reply_to_message_id=msg.get("message_id"),
        )
        return True

    workspace = get_workspace_by_id(workspace_id)

    requested_by = msg.get("from_name") or msg.get("from_username") or msg.get("from_id") or ""

    parsed_request = parse_examiner_request(
        workspace_id=workspace_id,
        raw_text=text,
    )

    return route_examiner_request(
        parsed_request=parsed_request,
        workspace_id=workspace_id,
        workspace=workspace,
        raw_request=text,
        requested_by=requested_by,
        chat_id=chat_id,
        message_id=msg.get("message_id"),
        send_message=lambda *args, **kwargs: send_telegram_message(
            bot_token,
            *args,
            **kwargs,
        ),
        build_keyboard=build_decision_keyboard,
        load_json=load_json,
        save_json=save_json,
        now_iso=now_iso,
        log=log,
    )


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
        "could not parse examiner reply",
        "invalid opportunity decision",
        "invalid draft decision",
        "workspace not found",
        "opportunity not found",
        "draft not found",
        "pipeline failed",
        "wordpress pipeline failed",
        "wordpress update/upload failed",
        "publication preparation was blocked",
        "no wordpress/platform draft was prepared",
    ]

    stdout_lower = result.stdout.lower() if result.stdout else ""
    stderr_lower = result.stderr.lower() if result.stderr else ""

    for signal in failure_signals:
        if signal in stdout_lower or signal in stderr_lower:
            log(f"Detected logical failure: {signal}")
            return False, combined_output

    return result.returncode == 0, combined_output


def find_draft_in_global_registry(draft_id):
    # Deprecated compatibility wrapper.
    # Drafts are now stored in workspace-level draft_registry.json files.
    workspace_id, draft = find_draft_any_workspace(draft_id)
    return draft


def find_draft_in_workspace_registry(draft_id, workspace_id):
    try:
        registry_path = get_workspace_draft_registry_path(workspace_id)
    except Exception:
        return None

    if not registry_path.exists():
        return None

    data = load_json(registry_path, {"drafts": []})

    for draft in data.get("drafts", []):
        if draft.get("draft_id") == draft_id:
            return draft

    return None


def is_draft_ready_for_examiner_review(draft_id):
    draft = find_draft_in_global_registry(draft_id)

    if not draft:
        return False

    return draft.get("validation", {}).get("status") == "passed"


def draft_has_wordpress_draft(draft_id, workspace_id=None):
    if workspace_id:
        draft = find_draft_in_workspace_registry(draft_id, workspace_id)
    else:
        draft = find_draft_in_global_registry(draft_id)

    if not draft:
        return False

    upload = draft.get("wordpress_upload", {}) or {}
    update = draft.get("wordpress_update", {}) or {}

    return (
        upload.get("uploaded") is True
        and bool(upload.get("wordpress_id"))
    ) or (
        update.get("updated") is True
        and bool(update.get("wordpress_id"))
    )


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

            if not is_draft_ready_for_examiner_review(item_id):
                log(
                    "Skipped pending draft because validation has not passed "
                    f"workspace={workspace_id} draft={item_id}"
                )
                continue

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

        elif "WordPress draft uploaded successfully" in clean:
            wordpress_status = "uploaded"

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

    output_lower = process_output.lower() if process_output else ""
    reused_active_job = (
        "existing active background job found" in output_lower
        or "no new background job was created" in output_lower
    )

    if ok and reused_active_job:
        workspace = get_workspace_by_id(workspace_id)
        lang = normalize_language(workspace.get("language", "en"))

        if lang.startswith("pt"):
            text = (
                "⚠️ Esta tarefa já está a ser processada pela Sofia.\n\n"
                f"Workspace: {workspace_id}\n"
                f"Item: {item_id}\n\n"
                "Nenhuma nova tarefa foi criada."
            )
        elif lang == "es":
            text = (
                "⚠️ Esta tarea ya está siendo procesada por Sofia.\n\n"
                f"Workspace: {workspace_id}\n"
                f"Item: {item_id}\n\n"
                "No se ha creado ninguna nueva tarea."
            )
        elif lang == "fr":
            text = (
                "⚠️ Cette tâche est déjà en cours de traitement par Sofia.\n\n"
                f"Workspace: {workspace_id}\n"
                f"Élément : {item_id}\n\n"
                "Aucune nouvelle tâche n’a été créée."
            )
        else:
            text = (
                "⚠️ Sofia is already processing this task.\n\n"
                f"Workspace: {workspace_id}\n"
                f"Item: {item_id}\n\n"
                "No new task was created."
            )

        send_telegram_message(
            get_bot_token(),
            chat_id,
            text,
            reply_to_message_id=reply_to_message_id,
        )
        return

    wp_result = extract_wordpress_result(process_output)

    if ok and is_draft and decision == "APPROVE":
        workspace = get_workspace_by_id(workspace_id)
        lang = normalize_language(workspace.get("language", "en"))

        output_lower = process_output.lower() if process_output else ""
        background_wp_job_created = (
            "background job created for wordpress draft preparation" in output_lower
            or "wordpress preparation pipeline will be handled by sofia_worker.py" in output_lower
            or "job-wp-draft" in output_lower
        )

        wordpress_status = wp_result.get("wordpress_status")
        wordpress_id = wp_result.get("wordpress_id")
        wordpress_link = wp_result.get("wordpress_link")

        if background_wp_job_created:
            if lang.startswith("pt"):
                text = (
                    "✅ Aprovação recebida\n\n"
                    f"Workspace: {workspace_id}\n"
                    f"Rascunho: {item_id}\n\n"
                    "A Sofia colocou a preparação do rascunho WordPress na fila de processamento em segundo plano.\n\n"
                    "Quando o rascunho WordPress estiver pronto, a Sofia enviará uma nova mensagem com o link para revisão final.\n\n"
                    "Nenhuma ação é necessária neste momento."
                )

            elif lang == "es":
                text = (
                    "✅ Aprobación recibida\n\n"
                    f"Workspace: {workspace_id}\n"
                    f"Borrador: {item_id}\n\n"
                    "Sofia ha puesto la preparación del borrador WordPress en la cola de procesamiento en segundo plano.\n\n"
                    "Cuando el borrador WordPress esté listo, Sofia enviará un nuevo mensaje con el enlace para revisión final.\n\n"
                    "No se requiere ninguna acción en este momento."
                )

            elif lang == "fr":
                text = (
                    "✅ Approbation reçue\n\n"
                    f"Workspace: {workspace_id}\n"
                    f"Brouillon : {item_id}\n\n"
                    "Sofia a placé la préparation du brouillon WordPress dans la file de traitement en arrière-plan.\n\n"
                    "Lorsque le brouillon WordPress sera prêt, Sofia enverra un nouveau message avec le lien pour révision finale.\n\n"
                    "Aucune action n’est nécessaire pour le moment."
                )

            else:
                text = (
                    "✅ Approval received\n\n"
                    f"Workspace: {workspace_id}\n"
                    f"Draft: {item_id}\n\n"
                    "Sofia has queued WordPress draft preparation for background processing.\n\n"
                    "When the WordPress draft is ready, Sofia will send a new message with the final review link.\n\n"
                    "No action is needed right now."
                )

        else:
            prepared_lines = []

            if lang.startswith("pt"):
                if wordpress_status:
                    prepared_lines.append(f"- Rascunho WordPress {wordpress_status} com sucesso")
                else:
                    prepared_lines.append("- Rascunho WordPress / website: preparado ou atualizado, se configurado")

                if wordpress_id:
                    prepared_lines.append(f"- ID no WordPress: {wordpress_id}")

                if wordpress_link:
                    prepared_lines.append(f"- Link do rascunho: {wordpress_link}")

                prepared_text = "\n".join(prepared_lines)

                text = (
                    "✅ Rascunho aprovado e preparado para publicação\n\n"
                    f"Workspace: {workspace_id}\n"
                    f"Rascunho: {item_id}\n\n"
                    "Preparado:\n"
                    f"{prepared_text}\n\n"
                    "A publicação final ao vivo NÃO foi feita automaticamente.\n"
                    "Por favor, reveja o rascunho no WordPress e publique manualmente quando estiver pronto."
                )

            elif lang == "es":
                if wordpress_status:
                    prepared_lines.append(f"- Borrador de WordPress {wordpress_status} correctamente")
                else:
                    prepared_lines.append("- Borrador de WordPress / sitio web: preparado o actualizado si está configurado")

                if wordpress_id:
                    prepared_lines.append(f"- ID de WordPress: {wordpress_id}")

                if wordpress_link:
                    prepared_lines.append(f"- Enlace del borrador: {wordpress_link}")

                prepared_text = "\n".join(prepared_lines)

                text = (
                    "✅ Borrador aprobado y preparado para publicación\n\n"
                    f"Workspace: {workspace_id}\n"
                    f"Borrador: {item_id}\n\n"
                    "Preparado:\n"
                    f"{prepared_text}\n\n"
                    "La publicación final en vivo NO se ha realizado automáticamente.\n"
                    "Por favor, revise el borrador en WordPress y publíquelo manualmente cuando esté listo."
                )

            elif lang == "fr":
                if wordpress_status:
                    prepared_lines.append(f"- Brouillon WordPress {wordpress_status} avec succès")
                else:
                    prepared_lines.append("- Brouillon WordPress / site web : préparé ou mis à jour si configuré")

                if wordpress_id:
                    prepared_lines.append(f"- ID WordPress : {wordpress_id}")

                if wordpress_link:
                    prepared_lines.append(f"- Lien du brouillon : {wordpress_link}")

                prepared_text = "\n".join(prepared_lines)

                text = (
                    "✅ Brouillon approuvé et préparé pour publication\n\n"
                    f"Workspace: {workspace_id}\n"
                    f"Brouillon : {item_id}\n\n"
                    "Préparé :\n"
                    f"{prepared_text}\n\n"
                    "La publication finale en ligne n’a PAS été effectuée automatiquement.\n"
                    "Veuillez examiner le brouillon dans WordPress et le publier manuellement lorsqu’il est prêt."
                )

            else:
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

    elif ok and is_draft and decision == "COMPLETE":
        workspace = get_workspace_by_id(workspace_id)
        lang = normalize_language(workspace.get("language", "en"))

        if lang.startswith("pt"):
            text = (
                "✅ Rascunho marcado como finalizado\n\n"
                f"Workspace: {workspace_id}\n"
                f"Rascunho: {item_id}\n\n"
                "A Sofia registou este rascunho como concluído para revisão/publicação manual no WordPress.\n\n"
                "A publicação final ao vivo NÃO foi feita automaticamente."
            )
        elif lang == "es":
            text = (
                "✅ Borrador marcado como finalizado\n\n"
                f"Workspace: {workspace_id}\n"
                f"Borrador: {item_id}\n\n"
                "Sofia registró este borrador como completado para revisión/publicación manual en WordPress.\n\n"
                "La publicación final en vivo NO se realizó automáticamente."
            )
        elif lang == "fr":
            text = (
                "✅ Brouillon marqué comme terminé\n\n"
                f"Workspace: {workspace_id}\n"
                f"Brouillon : {item_id}\n\n"
                "Sofia a enregistré ce brouillon comme terminé pour révision/publication manuelle dans WordPress.\n\n"
                "La publication finale en ligne n’a PAS été effectuée automatiquement."
            )
        else:
            text = (
                "✅ Draft marked as completed\n\n"
                f"Workspace: {workspace_id}\n"
                f"Draft: {item_id}\n\n"
                "Sofia recorded this draft as completed for manual WordPress review/publication.\n\n"
                "Final live publication has NOT been done automatically."
            )

    elif ok and is_draft and decision == "REVISE":
        workspace = get_workspace_by_id(workspace_id)
        lang = normalize_language(workspace.get("language", "en"))

        if lang.startswith("pt"):
            text = (
                "✅ Pedido de revisão recebido\n\n"
                f"Workspace: {workspace_id}\n"
                f"Rascunho: {item_id}\n\n"
                "A Sofia colocou esta revisão na fila de processamento em segundo plano.\n\n"
                "A revisão será aplicada, limpa e validada internamente. "
                "Quando estiver pronta, a Sofia enviará uma nova mensagem para revisão do examinador.\n\n"
                "Nenhuma ação é necessária neste momento."
            )

        elif lang == "es":
            text = (
                "✅ Solicitud de revisión recibida\n\n"
                f"Workspace: {workspace_id}\n"
                f"Borrador: {item_id}\n\n"
                "Sofia ha puesto esta revisión en la cola de procesamiento en segundo plano.\n\n"
                "La revisión será aplicada, limpiada y validada internamente. "
                "Cuando esté lista, Sofia enviará un nuevo mensaje para revisión del examinador.\n\n"
                "No se requiere ninguna acción en este momento."
            )

        elif lang == "fr":
            text = (
                "✅ Demande de révision reçue\n\n"
                f"Workspace: {workspace_id}\n"
                f"Brouillon : {item_id}\n\n"
                "Sofia a placé cette révision dans la file de traitement en arrière-plan.\n\n"
                "La révision sera appliquée, nettoyée et validée en interne. "
                "Lorsqu’elle sera prête, Sofia enverra un nouveau message pour révision par l’examinateur.\n\n"
                "Aucune action n’est nécessaire pour le moment."
            )

        else:
            text = (
                "✅ Revision request received\n\n"
                f"Workspace: {workspace_id}\n"
                f"Draft: {item_id}\n\n"
                "Sofia has queued this revision for background processing.\n\n"
                "The revision will be applied, cleaned, and validated internally. "
                "When it is ready, Sofia will send a new message for examiner review.\n\n"
                "No action is needed right now."
            )

    elif ok and is_opportunity and decision == "APPROVE":
        workspace = get_workspace_by_id(workspace_id)
        lang = normalize_language(workspace.get("language", "en"))

        if lang.startswith("pt"):
            text = (
                "✅ Pedido recebido\n\n"
                "A Sofia está a preparar o conteúdo.\n"
                "Será enviada uma ligação para revisão quando o rascunho estiver pronto."
            )
        elif lang == "es":
            text = (
                "✅ Solicitud recibida\n\n"
                "Sofia está preparando el contenido.\n"
                "Se enviará un enlace para revisión cuando el borrador esté listo."
            )
        elif lang == "fr":
            text = (
                "✅ Demande reçue\n\n"
                "Sofia prépare le contenu.\n"
                "Un lien de révision sera envoyé lorsque le brouillon sera prêt."
            )
        else:
            text = (
                "✅ Request received\n\n"
                "Sofia is preparing the content.\n"
                "A review link will be sent when the draft is ready."
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


def build_long_processing_message(workspace_id, item_id, decision):
    workspace = get_workspace_by_id(workspace_id)
    lang = normalize_language(workspace.get("language", "en"))

    is_opportunity_approval = (
        decision == "APPROVE"
        and str(item_id).startswith("OPP-")
    )

    is_draft_revision = (
        decision == "REVISE"
        and str(item_id).startswith("DRAFT-")
    )

    is_draft_approval = (
        decision == "APPROVE"
        and str(item_id).startswith("DRAFT-")
    )

    if lang.startswith("pt"):
        if is_opportunity_approval:
            return (
                "✅ Oportunidade aprovada\n\n"
                f"Workspace: {workspace_id}\n"
                f"Oportunidade: {item_id}\n\n"
                "A Sofia colocou este pedido na fila de processamento em segundo plano.\n\n"
                "O rascunho será gerado, limpo e validado internamente. "
                "Quando estiver pronto, a Sofia enviará uma nova mensagem para revisão do examinador.\n\n"
                "Nenhuma ação é necessária neste momento."
            )

        if is_draft_revision:
            return (
                "✅ Pedido de revisão recebido\n\n"
                f"Workspace: {workspace_id}\n"
                f"Rascunho: {item_id}\n\n"
                "A Sofia vai aplicar as instruções de revisão e validar novamente o conteúdo."
            )

        if is_draft_approval:
            return (
                "✅ Aprovação recebida\n\n"
                f"Workspace: {workspace_id}\n"
                f"Rascunho: {item_id}\n\n"
                "A Sofia vai preparar o rascunho para o WordPress ou para os canais configurados."
            )

    if lang == "es":
        if is_opportunity_approval:
            return (
                "✅ Oportunidad aprobada\n\n"
                f"Workspace: {workspace_id}\n"
                f"Oportunidad: {item_id}\n\n"
                "Sofia ha puesto este pedido en la cola de procesamiento en segundo plano.\n\n"
                "El borrador será generado, limpiado y validado internamente. "
                "Cuando esté listo, Sofia enviará un nuevo mensaje para la revisión del examinador.\n\n"
                "No se requiere ninguna acción en este momento."
            )

        if is_draft_revision:
            return (
                "✅ Solicitud de revisión recibida\n\n"
                f"Workspace: {workspace_id}\n"
                f"Borrador: {item_id}\n\n"
                "Sofia va a aplicar las instrucciones de revisión y validar nuevamente el contenido."
            )

        if is_draft_approval:
            return (
                "✅ Aprobación recibida\n\n"
                f"Workspace: {workspace_id}\n"
                f"Borrador: {item_id}\n\n"
                "Sofia va a preparar el borrador para WordPress o para los canales configurados."
            )

    if lang == "fr":
        if is_opportunity_approval:
            return (
                "✅ Opportunité approuvée\n\n"
                f"Workspace: {workspace_id}\n"
                f"Opportunité : {item_id}\n\n"
                "Sofia a placé cette demande dans la file de traitement en arrière-plan.\n\n"
                "Le brouillon sera généré, nettoyé et validé en interne. "
                "Lorsqu’il sera prêt, Sofia enverra un nouveau message pour révision par l’examinateur.\n\n"
                "Aucune action n’est nécessaire pour le moment."
            )

        if is_draft_revision:
            return (
                "✅ Demande de révision reçue\n\n"
                f"Workspace: {workspace_id}\n"
                f"Brouillon : {item_id}\n\n"
                "Sofia va appliquer les instructions de révision et valider à nouveau le contenu."
            )

        if is_draft_approval:
            return (
                "✅ Approbation reçue\n\n"
                f"Workspace: {workspace_id}\n"
                f"Brouillon : {item_id}\n\n"
                "Sofia va préparer le brouillon pour WordPress ou les canaux configurés."
            )

    if is_opportunity_approval:
        return (
            "✅ Opportunity approved\n\n"
            f"Workspace: {workspace_id}\n"
            f"Opportunity: {item_id}\n\n"
            "Sofia has queued this request for background processing.\n\n"
            "The draft will be generated, cleaned, and validated internally. "
            "When it is ready, Sofia will send a new message for examiner review.\n\n"
            "No action is needed right now."
        )

    if is_draft_revision:
        return (
            "✅ Revision request received\n\n"
            f"Workspace: {workspace_id}\n"
            f"Draft: {item_id}\n\n"
            "Sofia will apply the revision instructions and validate the content again."
        )

    if is_draft_approval:
        return (
            "✅ Approval received\n\n"
            f"Workspace: {workspace_id}\n"
            f"Draft: {item_id}\n\n"
            "Sofia will prepare the draft for WordPress or the configured channels."
        )

    return ""


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


    duplicate_safe_decisions = {
        "APPROVE",
        "COMPLETE",
        "REJECT_NEVER",
        "REJECT_SKIP",
        "REJECT_ANGLE",
    }

    if decision in duplicate_safe_decisions:
        previous_action = get_button_action(
            chat_id=chat_id,
            message_id=message_id,
            workspace_id=workspace_id,
            item_id=item_id,
            decision=decision,
        )

        if previous_action:
            send_telegram_message(
                bot_token,
                chat_id,
                build_button_already_processed_message(workspace_id, item_id),
                reply_to_message_id=message_id,
            )
            return

    if decision in ["REVISE_PROMPT", "REVISE"]:
        log(
            "CALLBACK revise prompt "
            f"workspace={workspace_id} chat_id={chat_id} item={item_id} decision={decision}"
        )

        user_id = str(from_user.get("id", ""))

        if not user_id:
            send_telegram_message(
                bot_token,
                chat_id,
                (
                    "⚠️ Sofia could not start the revision flow because the examiner "
                    "user could not be identified."
                ),
                reply_to_message_id=message_id,
            )
            return

        set_pending_revision_context(
            chat_id=chat_id,
            user_id=user_id,
            workspace_id=workspace_id,
            draft_id=item_id,
        )

        lang = normalize_language(get_workspace_by_id(workspace_id).get("language", "en"))

        if lang.startswith("pt"):
            instruction = (
                "✏️ A Sofia está pronta para rever este rascunho.\n\n"
                f"Rascunho: {item_id}\n\n"
                "Por favor, envie as instruções de revisão na próxima mensagem. "
                "Não precisa usar nenhum formato de comando."
            )
        elif lang == "es":
            instruction = (
                "✏️ Sofia está lista para revisar este borrador.\n\n"
                f"Borrador: {item_id}\n\n"
                "Por favor, envíe las instrucciones de revisión en su próximo mensaje. "
                "No necesita usar ningún formato de comando."
            )
        elif lang == "fr":
            instruction = (
                "✏️ Sofia est prête à réviser ce brouillon.\n\n"
                f"Brouillon : {item_id}\n\n"
                "Veuillez envoyer les instructions de révision dans votre prochain message. "
                "Aucun format de commande n’est nécessaire."
            )
        else:
            instruction = (
                "✏️ Sofia is ready to revise this draft.\n\n"
                f"Draft: {item_id}\n\n"
                "Please send the revision instructions in your next message. "
                "You do not need to use any command format."
            )

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

    is_background_job = (
        (
            decision == "APPROVE"
            and str(item_id).startswith("OPP-")
        )
        or
        (
            decision == "REVISE"
            and str(item_id).startswith("DRAFT-")
        )
        or
        (
            decision == "APPROVE"
            and str(item_id).startswith("DRAFT-")
        )
    )

    long_processing_message = ""

    if not is_background_job:
        long_processing_message = build_long_processing_message(
            workspace_id,
            item_id,
            decision,
        )

    if long_processing_message:
        send_telegram_message(
            bot_token,
            chat_id,
            long_processing_message,
            reply_to_message_id=message_id,
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

    if ok and decision in duplicate_safe_decisions:
        mark_button_action_processed(
            chat_id=chat_id,
            message_id=message_id,
            workspace_id=workspace_id,
            item_id=item_id,
            decision=decision,
            user_id=from_user.get("id", ""),
        )

    if ok:
        is_background_job = (
            (
                decision == "APPROVE"
                and str(item_id).startswith("OPP-")
            )
            or
            (
                decision == "REVISE"
                and str(item_id).startswith("DRAFT-")
            )
            or
            (
                decision == "APPROVE"
                and str(item_id).startswith("DRAFT-")
            )
        )

        if is_background_job:
            log(
                "Decision queued as background job; "
                f"not sending next pending item immediately workspace={workspace_id} item={item_id} decision={decision}"
            )
            return

        output_lower = process_output.lower() if process_output else ""

        draft_not_ready = (
            "draft still has validation issues after repair" in output_lower
            or "draft generation failed" in output_lower
        )

        if draft_not_ready:
            log(
                "Draft not sent to examiner review because generated content is not ready "
                f"workspace={workspace_id} item={item_id}"
            )
        else:
            send_next_pending_item(bot_token, chat_id, workspace_id)



def normalize_revision_instruction(text):
    text = str(text or "").strip()
    text = text.replace("\r", "\n")

    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        line = line.lstrip("-*• ").strip()
        lines.append(line)

    return "; ".join(lines)

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
    
    if handle_job_status_request(msg, workspace_by_chat_id):
        return

    user_id = msg.get("from_id")
    possible_workspaces = workspace_by_chat_id.get(str(chat_id), [])

    if len(possible_workspaces) == 1 and user_id:
        pending_workspace_id = possible_workspaces[0]

        pending = get_pending_revision_context(
            chat_id=chat_id,
            user_id=user_id,
            workspace_id=pending_workspace_id,
        )

        if pending:
            draft_id = pending["draft_id"]
            revision_instruction = normalize_revision_instruction(text)

            if revision_instruction:
                clean_text = f"REVISE {draft_id}: {revision_instruction}"

                lang = normalize_language(
                    get_workspace_by_id(pending_workspace_id).get("language", "en")
                )

                if lang.startswith("pt"):
                    ack_text = (
                        "✅ Instruções de revisão recebidas.\n\n"
                        "A Sofia começou a processar a versão revista. "
                        "Receberá o rascunho atualizado quando estiver pronto."
                    )
                elif lang == "es":
                    ack_text = (
                        "✅ Instrucciones de revisión recibidas.\n\n"
                        "Sofia ha empezado a procesar la versión revisada. "
                        "Recibirá el borrador actualizado cuando esté listo."
                    )
                elif lang == "fr":
                    ack_text = (
                        "✅ Instructions de révision reçues.\n\n"
                        "Sofia a commencé à traiter la version révisée. "
                        "Vous recevrez le brouillon mis à jour lorsqu’il sera prêt."
                    )
                else:
                    ack_text = (
                        "✅ Revision instructions received.\n\n"
                        "Sofia has started processing the revised draft. "
                        "You will receive the updated draft when it is ready."
                    )

                send_telegram_message(
                    get_bot_token(),
                    chat_id,
                    ack_text,
                    reply_to_message_id=msg.get("message_id"),
                )

                clear_pending_revision_context(
                    chat_id=chat_id,
                    user_id=user_id,
                    workspace_id=pending_workspace_id,
                )

                log(
                    "PENDING revision instruction received "
                    f"workspace={pending_workspace_id} "
                    f"chat_id={chat_id} "
                    f"draft={draft_id} "
                    f"text={revision_instruction!r}"
                )

                ok, process_output = process_decision(
                    pending_workspace_id,
                    clean_text,
                )

                if not ok:
                    send_processing_result(
                        chat_id=chat_id,
                        reply_to_message_id=msg.get("message_id"),
                        workspace_id=pending_workspace_id,
                        item_id=draft_id,
                        decision="REVISE",
                        ok=ok,
                        process_output=process_output,
                    )

                return

    if handle_internal_content_trigger(msg, workspace_by_chat_id):
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
        available = workspace_by_chat_id.get(str(chat_id), [])
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
        is_background_job = (
            (
                decision == "APPROVE"
                and str(item_id).startswith("OPP-")
            )
            or
            (
                decision == "REVISE"
                and str(item_id).startswith("DRAFT-")
            )
            or
            (
                decision == "APPROVE"
                and str(item_id).startswith("DRAFT-")
            )
        )

        if is_background_job:
            log(
                "Decision queued as background job; "
                f"not sending next pending item immediately workspace={workspace_id} item={item_id} decision={decision}"
            )
            return

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