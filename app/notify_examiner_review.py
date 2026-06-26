import json
import os
import sys
import requests
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

from workspace_paths import (
    get_workspace_draft_registry_path,
    empty_draft_registry,
)


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)
WORKSPACES_PATH = ROOT / "data" / "workspaces.json"
TEMPLATES_PATH = ROOT / "data" / "telegram_message_templates.json"
# Deprecated: draft registries are now workspace-level.
GLOBAL_DRAFT_REGISTRY_PATH = ROOT / "sites" / "draft_registry.json"


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


def get_preview_label(language):
    language = normalize_language(language)

    labels = {
        "en": "Content preview",
        "es": "Vista previa del contenido",
        "fr": "Aperçu du contenu",
        "pt-PT": "Pré-visualização do conteúdo",
        "pt-BR": "Prévia do conteúdo",
        "tr": "İçerik önizlemesi",
        "ru": "Предпросмотр содержимого",
    }

    return labels.get(language, labels["en"])


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


def load_workspace_draft_registry(workspace):
    workspace_id = workspace.get("workspace_id", "")
    path = get_workspace_draft_registry_path(workspace_id)

    if not path.exists():
        return empty_draft_registry(workspace_id)

    return load_json(path)


def find_draft_in_workspace_registry(draft_id, workspace):
    registry = load_workspace_draft_registry(workspace)

    for draft in registry.get("drafts", []):
        if draft.get("draft_id") == draft_id:
            return draft

    return None


def find_draft_in_registry(draft_id, workspace):
    return find_draft_in_workspace_registry(draft_id, workspace)


def draft_can_be_sent_for_review(draft_id, workspace):
    draft = find_draft_in_registry(draft_id, workspace)

    if not draft:
        return False

    if not draft.get("html_content") and not draft.get("generated_content", {}).get("content"):
        return False

    validation_status = draft.get("validation", {}).get("status", "")

    return validation_status in ["passed", "warning", "failed", ""]

def draft_has_wordpress_draft(draft_id, workspace):
    draft = find_draft_in_registry(draft_id, workspace)

    if not draft:
        return False

    if draft.get("wordpress_id") or draft.get("wordpress_link"):
        return True

    upload = draft.get("wordpress_upload", {}) or {}
    update = draft.get("wordpress_update", {}) or {}

    return (
        upload.get("uploaded") is True
        and bool(upload.get("wordpress_id"))
    ) or (
        update.get("updated") is True
        and bool(update.get("wordpress_id"))
    )


def get_wordpress_link(draft_id, workspace):
    draft = find_draft_in_registry(draft_id, workspace)

    if not draft:
        return ""

    update = draft.get("wordpress_update", {}) or {}
    upload = draft.get("wordpress_upload", {}) or {}

    return (
        draft.get("wordpress_link")
        or update.get("wordpress_link")
        or upload.get("wordpress_link")
        or ""
    )


def strip_html_for_preview(content):
    if not content:
        return ""

    content = str(content)
    content = content.replace("\n", " ")
    content = content.replace("\r", " ")
    content = content.replace("</p>", "\n")
    content = content.replace("</h1>", "\n")
    content = content.replace("</h2>", "\n")
    content = content.replace("</h3>", "\n")
    content = content.replace("</li>", "\n")

    import re
    content = re.sub(r"<[^>]+>", " ", content)
    content = re.sub(r"\s+", " ", content).strip()

    if len(content) > 700:
        content = content[:700].rsplit(" ", 1)[0] + "..."

    return content


def find_draft_in_global_registry(draft_id):
    # Deprecated compatibility wrapper.
    # notify_examiner_review.py should use find_draft_in_registry(draft_id, workspace).
    if not GLOBAL_DRAFT_REGISTRY_PATH.exists():
        return None

    data = load_json(GLOBAL_DRAFT_REGISTRY_PATH)
    drafts = data.get("drafts", [])

    for draft in drafts:
        if draft.get("draft_id") == draft_id:
            return draft

    return None


def get_wordpress_review_info(draft_id, workspace):
    draft = find_draft_in_registry(draft_id, workspace)

    if not draft:
        return {
            "has_wordpress_draft": False,
            "wordpress_id": "",
            "wordpress_link": "",
            "wordpress_status": "",
            "post_type": ""
        }

    update = draft.get("wordpress_update", {}) or {}
    upload = draft.get("wordpress_upload", {}) or {}

    wordpress_id = (
        draft.get("wordpress_id")
        or update.get("wordpress_id")
        or upload.get("wordpress_id")
        or ""
    )

    wordpress_link = (
        draft.get("wordpress_link")
        or update.get("wordpress_link")
        or upload.get("wordpress_link")
        or ""
    )

    wordpress_status = (
        draft.get("wordpress_status")
        or update.get("wordpress_status")
        or upload.get("wordpress_status")
        or ""
    )

    post_type = (
        draft.get("post_type")
        or update.get("post_type")
        or upload.get("post_type")
        or ""
    )

    return {
        "has_wordpress_draft": bool(wordpress_id or wordpress_link),
        "wordpress_id": wordpress_id,
        "wordpress_link": wordpress_link,
        "wordpress_status": wordpress_status,
        "post_type": post_type
    }


def get_draft_content_preview(draft_id, workspace):
    draft = find_draft_in_registry(draft_id, workspace)

    if not draft:
        return "Content preview not available. Draft not found in workspace registry."

    content = (
        draft.get("html_content")
        or draft.get("generated_content", {}).get("content", "")
        or draft.get("draft_content", {}).get("content", "")
    )

    if not content:
        return "Content preview not available yet. The draft content has not been generated."

    return strip_html_for_preview(content)


def build_message(item, workspace):
    language = workspace.get("language", "en")
    normalized_language = normalize_language(language)

    draft_id = item.get("draft_id")
    draft = find_draft_in_registry(draft_id, workspace) or {}

    title = (
        item.get("working_title")
        or item.get("title")
        or draft.get("working_title")
        or draft.get("title")
        or ""
    )

    keyphrase = (
        item.get("target_keyword")
        or item.get("focus_keyphrase")
        or draft.get("target_keyword")
        or draft.get("focus_keyphrase")
        or ""
    )

    content_type = (
        item.get("content_type")
        or draft.get("content_type")
        or "unknown"
    )

    validation_status = (
        draft.get("validation", {}).get("status")
        or item.get("validation_status")
        or "unknown"
    )

    validation_warnings = (
    draft.get("validation", {}).get("warnings")
    or []
    )

    summary = (
        draft.get("summary")
        or draft.get("notes")
        or item.get("summary")
        or item.get("notes")
        or ""
    )

    if not summary:
        if normalized_language.startswith("pt"):
            summary = f"Rascunho focado em {keyphrase} para o mercado local."
        elif normalized_language == "es":
            summary = f"Borrador enfocado en {keyphrase} para el mercado local."
        elif normalized_language == "fr":
            summary = f"Brouillon axé sur {keyphrase} pour le marché local."
        else:
            summary = f"Draft focused on {keyphrase} for the local market."

    warnings_text = ""

    if validation_warnings:
        if normalized_language.startswith("pt"):
            warnings_text = "\nAvisos para revisão do examinador:\n"
        elif normalized_language == "es":
            warnings_text = "\nAvisos para revisión del examinador:\n"
        elif normalized_language == "fr":
            warnings_text = "\nAvertissements pour révision par l’examinateur :\n"
        else:
            warnings_text = "\nWarnings for examiner review:\n"

        for warning in validation_warnings[:10]:
            warnings_text += f"- {warning}\n"

    wp_info = get_wordpress_review_info(draft_id, workspace)

    if normalized_language.startswith("pt"):
        labels = {
            "website_header": "[SOFIA – RASCUNHO DE WEBSITE PRONTO]",
            "wordpress_header": "[SOFIA – RASCUNHO WORDPRESS PRONTO PARA REVISÃO]",
            "draft": "Rascunho",
            "workspace": "Workspace",
            "type": "Tipo",
            "wordpress_type": "Tipo no WordPress",
            "title": "Título",
            "focus": "Frase-chave",
            "validation": "Validação",
            "summary": "Resumo",
            "wordpress_draft": "Rascunho WordPress",
            "wordpress_id": "ID no WordPress",
            "wordpress_status": "Estado no WordPress",
            "next_step": "Próximo passo",
            "approve": "Clique em Aprovar se o rascunho pode seguir para preparação no WordPress.",
            "complete": "Clique em Finalizado se o rascunho está pronto para revisão/publicação manual.",
            "revise": "Clique em Rever se deseja pedir alterações.",
        }
    elif normalized_language == "es":
        labels = {
            "website_header": "[SOFIA – BORRADOR DE SITIO WEB LISTO]",
            "wordpress_header": "[SOFIA – BORRADOR WORDPRESS LISTO PARA REVISIÓN]",
            "draft": "Borrador",
            "workspace": "Workspace",
            "type": "Tipo",
            "wordpress_type": "Tipo en WordPress",
            "title": "Título",
            "focus": "Frase clave",
            "validation": "Validación",
            "summary": "Resumen",
            "wordpress_draft": "Borrador WordPress",
            "wordpress_id": "ID de WordPress",
            "wordpress_status": "Estado en WordPress",
            "next_step": "Próximo paso",
            "approve": "Haga clic en Aprobar si el borrador puede pasar a preparación en WordPress.",
            "complete": "Haga clic en Finalizado si el borrador está listo para revisión/publicación manual.",
            "revise": "Haga clic en Revisar si desea pedir cambios.",
        }
    elif normalized_language == "fr":
        labels = {
            "website_header": "[SOFIA – BROUILLON DE SITE WEB PRÊT]",
            "wordpress_header": "[SOFIA – BROUILLON WORDPRESS PRÊT POUR RÉVISION]",
            "draft": "Brouillon",
            "workspace": "Workspace",
            "type": "Type",
            "wordpress_type": "Type WordPress",
            "title": "Titre",
            "focus": "Requête principale",
            "validation": "Validation",
            "summary": "Résumé",
            "wordpress_draft": "Brouillon WordPress",
            "wordpress_id": "ID WordPress",
            "wordpress_status": "Statut WordPress",
            "next_step": "Prochaine étape",
            "approve": "Cliquez sur Approuver si le brouillon peut passer à la préparation WordPress.",
            "complete": "Cliquez sur Terminé si le brouillon est prêt pour révision/publication manuelle.",
            "revise": "Cliquez sur Réviser si vous souhaitez demander des modifications.",
        }
    else:
        labels = {
            "website_header": "[SOFIA – WEBSITE DRAFT READY]",
            "wordpress_header": "[SOFIA – WORDPRESS DRAFT READY FOR REVIEW]",
            "draft": "Draft",
            "workspace": "Workspace",
            "type": "Type",
            "wordpress_type": "WordPress type",
            "title": "Title",
            "focus": "Focus keyword",
            "validation": "Validation",
            "summary": "Summary",
            "wordpress_draft": "WordPress draft",
            "wordpress_id": "WordPress ID",
            "wordpress_status": "WordPress status",
            "next_step": "Next step",
            "approve": "Click Approve if the draft can move to WordPress preparation.",
            "complete": "Click Completed if the draft is ready for manual review/publication.",
            "revise": "Click Revise if you want changes.",
        }

    if wp_info.get("has_wordpress_draft"):
        wordpress_link = wp_info.get("wordpress_link") or "Link not available"

        # WordPress-first stabilization:
        # The examiner only needs the review link and next action.
        # Internal fields such as validation status, WordPress ID, post type,
        # and WordPress status remain in the registry/logs, not in Telegram.
        if normalized_language.startswith("pt"):
            return f"""
[SOFIA – RASCUNHO PRONTO PARA REVISÃO]

Título:
{title}

Link para revisão no WordPress:
{wordpress_link}

Resumo:
{summary}

{warnings_text}

Próximo passo:
- Clique em Finalizado se o rascunho está pronto.
- Clique em Rever se deseja pedir alterações.
""".strip()

        if normalized_language == "es":
            return f"""
[SOFIA – BORRADOR LISTO PARA REVISIÓN]

Título:
{title}

Enlace para revisión en WordPress:
{wordpress_link}

Resumen:
{summary}

{warnings_text}

Próximo paso:
- Haga clic en Finalizado si el borrador está listo.
- Haga clic en Revisar si desea pedir cambios.
""".strip()

        if normalized_language == "fr":
            return f"""
[SOFIA – BROUILLON PRÊT POUR RÉVISION]

Titre :
{title}

Lien de révision WordPress :
{wordpress_link}

Résumé :
{summary}

{warnings_text}

Prochaine étape :
- Cliquez sur Terminé si le brouillon est prêt.
- Cliquez sur Réviser si vous souhaitez demander des modifications.
""".strip()

        return f"""
[SOFIA – DRAFT READY FOR REVIEW]

Title:
{title}

WordPress review link:
{wordpress_link}

Summary:
{summary}

{warnings_text}

Next step:
- Click Completed if the draft is ready.
- Click Revise if you want changes.
""".strip()

    return f"""
{labels["website_header"]}

{labels["draft"]}: {draft_id}
{labels["workspace"]}: {workspace.get("workspace_id")}
{labels["type"]}: {content_type}

{labels["title"]}:
{title}

{labels["focus"]}:
{keyphrase}

{labels["validation"]}:
{validation_status}

{labels["summary"]}:
{summary}

{labels["next_step"]}:
- {labels["approve"]}
- {labels["revise"]}
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


def build_decision_keyboard(draft_id, workspace_id, language="en", workspace=None):
    labels = get_button_labels(language)

    if workspace and draft_has_wordpress_draft(draft_id, workspace):
        normalized = normalize_language(language)

        if normalized.startswith("pt"):
            complete_label = "✅ Finalizado"
        elif normalized == "es":
            complete_label = "✅ Finalizado"
        elif normalized == "fr":
            complete_label = "✅ Terminé"
        else:
            complete_label = "✅ Completed"

        return {
            "inline_keyboard": [
                [
                    {"text": complete_label, "callback_data": f"COMPLETE|{workspace_id}|{draft_id}"},
                    {"text": labels["revise"], "callback_data": f"REVISE_PROMPT|{workspace_id}|{draft_id}"},
                ]
            ]
        }

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



def load_external_opportunities(workspace):
    path = ROOT / workspace.get("folder_path", "") / "external_opportunities.json"

    if not path.exists():
        return path, {"version": "1.0", "opportunities": []}

    data = load_json(path)

    if isinstance(data, list):
        data = {
            "version": "1.0",
            "opportunities": data
        }

    data.setdefault("opportunities", [])
    return path, data


def find_opportunity(opportunities, opportunity_id):
    for item in opportunities:
        if (
            item.get("opportunity_id") == opportunity_id
            or item.get("id") == opportunity_id
        ):
            return item
    return None



def load_language_profile_for_workspace(workspace):
    folder_path = workspace.get("folder_path", "")
    if not folder_path:
        return {}

    path = ROOT / folder_path / "language_profile.json"

    if not path.exists():
        return {}

    try:
        return load_json(path)
    except Exception:
        return {}


def display_label(language_profile, group, value):
    value = str(value or "").strip()
    labels = (
        language_profile
        .get("examiner_display_labels", {})
        .get(group, {})
    )

    return labels.get(value, value)


def build_opportunity_rationale(opportunity, language_profile):
    templates = language_profile.get("opportunity_messages", {}) or {}

    competitor_total_pages = opportunity.get("competitor_total_pages")
    competitor_coverage_count = opportunity.get("competitor_coverage_count")
    our_coverage_count = opportunity.get("our_coverage_count", 0)

    if competitor_total_pages is not None and competitor_coverage_count is not None:
        template = templates.get("competitor_gap")
        if template:
            try:
                return template.format(
                    competitor_total_pages=competitor_total_pages,
                    competitor_coverage_count=competitor_coverage_count,
                    our_coverage_count=our_coverage_count,
                )
            except Exception:
                pass

    return (
        opportunity.get("rationale")
        or templates.get("default_rationale")
        or "Sofia recommends reviewing this opportunity for the local market."
    )

def build_opportunity_message(opportunity, workspace):
    language = normalize_language(workspace.get("language", "en"))
    language_profile = load_language_profile_for_workspace(workspace)

    title = opportunity.get("title") or opportunity.get("topic_label") or opportunity.get("topic") or ""

    raw_page_type = opportunity.get("page_type") or "unknown"
    raw_blueprint_id = opportunity.get("blueprint_id") or ""
    raw_intent_type = opportunity.get("intent_type") or ""

    page_type = display_label(language_profile, "page_types", raw_page_type)
    blueprint_id = display_label(language_profile, "blueprints", raw_blueprint_id)
    intent_type = display_label(language_profile, "intent_types", raw_intent_type)

    rationale = build_opportunity_rationale(opportunity, language_profile)

    if language == "es":
        return f"""
[SOFIA – OPORTUNIDAD DE CONTENIDO]

Título:
{title}

Tipo de página:
{page_type}

Intención:
{intent_type}

Blueprint recomendado:
{blueprint_id}

Motivo:
{rationale}

Próximo paso:
- Haga clic en Aprobar si desea que Sofia prepare el borrador.
- Haga clic en Revisar si desea modificar el enfoque.
- Haga clic en Rechazar si no desea trabajar esta oportunidad.
""".strip()

    return f"""
[SOFIA – CONTENT OPPORTUNITY]

Title:
{title}

Page type:
{page_type}

Intent:
{intent_type}

Recommended blueprint:
{blueprint_id}

Reason:
{rationale}

Next step:
- Click Approve if Sofia should prepare the draft.
- Click Revise if you want to modify the angle.
- Click Reject if you do not want this opportunity.
""".strip()


def build_opportunity_keyboard(opportunity_id, workspace_id, language="en"):
    language = normalize_language(language)

    if language == "es":
        approve = "✅ Aprobar"
        modify = "✏️ Revisar"
        reject = "❌ Rechazar"
    elif language.startswith("pt"):
        approve = "✅ Aprovar"
        modify = "✏️ Rever"
        reject = "❌ Rejeitar"
    elif language == "fr":
        approve = "✅ Approuver"
        modify = "✏️ Réviser"
        reject = "❌ Rejeter"
    else:
        approve = "✅ Approve"
        modify = "✏️ Modify"
        reject = "❌ Reject"

    return {
        "inline_keyboard": [
            [
                {"text": approve, "callback_data": f"APPROVE|{workspace_id}|{opportunity_id}"},
                {"text": modify, "callback_data": f"MODIFY|{workspace_id}|{opportunity_id}"},
                {"text": reject, "callback_data": f"REJECT|{workspace_id}|{opportunity_id}"},
            ]
        ]
    }


def send_specific_opportunity(workspace, workspace_id, opportunity_id, sending):
    opportunity_path, data = load_external_opportunities(workspace)
    opportunity = find_opportunity(data.get("opportunities", []), opportunity_id)

    if not opportunity:
        print(f"Opportunity not found: {opportunity_id}")
        return False

    telegram_group_id = workspace.get("telegram_group_id")
    telegram_group = workspace.get("telegram_group", "")

    if sending and not telegram_group_id:
        print(f"No telegram_group_id found for workspace: {workspace_id}")
        return False

    bot_token = os.getenv("SOFIA_TELEGRAM_BOT_TOKEN")
    if bot_token:
        bot_token = bot_token.strip().strip('"').strip("'")

    if sending and not bot_token:
        print("Missing environment variable: SOFIA_TELEGRAM_BOT_TOKEN")
        return False

    message = build_opportunity_message(opportunity, workspace)
    keyboard = build_opportunity_keyboard(
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

    if sending:
        send_telegram_message(
            bot_token,
            telegram_group_id,
            message,
            reply_markup=keyboard
        )

        opportunity["telegram_notified"] = True
        opportunity["telegram_notified_at"] = now_iso()
        opportunity["updated_at"] = now_iso()
        save_json(opportunity_path, data)

        print("Telegram opportunity message sent with buttons.")

    return True

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python app/notify_examiner_review.py WORKSPACE_ID --preview")
        print("  python app/notify_examiner_review.py WORKSPACE_ID --send")
        print("  python app/notify_examiner_review.py WORKSPACE_ID --send-draft DRAFT_ID")
        print("  python app/notify_examiner_review.py WORKSPACE_ID --send-opportunity OPP-ID")
        print("Example:")
        print("  python app/notify_examiner_review.py local.ao --send")
        print("  python app/notify_examiner_review.py local.ao --send-draft DRAFT-0001")
        return

    workspace_id = sys.argv[1]

    mode = sys.argv[2] if len(sys.argv) > 2 else "--preview"
    specific_draft_id = None
    specific_opportunity_id = None

    if mode == "--send-draft":
        if len(sys.argv) < 4:
            print("Usage:")
            print("  python app/notify_examiner_review.py WORKSPACE_ID --send-draft DRAFT_ID")
            return
        specific_draft_id = sys.argv[3]

    if mode == "--send-opportunity":
        if len(sys.argv) < 4:
            print("Usage:")
            print("  python app/notify_examiner_review.py WORKSPACE_ID --send-opportunity OPP-ID")
            return
        specific_opportunity_id = sys.argv[3]

    if mode not in ["--preview", "--send", "--send-draft", "--send-opportunity"]:
        print("Invalid mode. Use --preview, --send, --send-draft, or --send-opportunity.")
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

    sending = mode in ["--send", "--send-draft", "--send-opportunity"]

    if sending and not telegram_group_id:
        print(f"No telegram_group_id found for workspace: {workspace_id}")
        return

    bot_token = os.getenv("SOFIA_TELEGRAM_BOT_TOKEN")
    if bot_token:
        bot_token = bot_token.strip().strip('"').strip("'")

    if sending and not bot_token:
        print("Missing environment variable: SOFIA_TELEGRAM_BOT_TOKEN")
        return

    if specific_opportunity_id:
        send_specific_opportunity(
            workspace=workspace,
            workspace_id=workspace_id,
            opportunity_id=specific_opportunity_id,
            sending=sending
        )
        return

    review_items = review_queue.get("review_items", [])

    # ------------------------------------------------------------
    # Specific draft mode:
    # Used after APPROVE DRAFT when WordPress draft was prepared.
    # This must work even if the review queue item is no longer
    # status == pending_review.
    # ------------------------------------------------------------
    if specific_draft_id:
        draft = find_draft_in_registry(specific_draft_id, workspace)

        if not draft:
            print(f"Draft not found in workspace registry: {specific_draft_id}")
            return

        if not draft.get("html_content") and not draft.get("generated_content", {}).get("content"):
            print(f"Draft has no generated content ready: {specific_draft_id}")
            return

        wp_info = get_wordpress_review_info(specific_draft_id, workspace)

        if not wp_info.get("has_wordpress_draft"):
            print(f"Draft has no WordPress draft/link yet: {specific_draft_id}")
            return

        review = None

        for item in review_items:
            if item.get("draft_id") == specific_draft_id:
                review = item
                break

        if review is None:
            review = {
                "draft_id": specific_draft_id,
                "intake_id": draft.get("created_from_intake_id", ""),
                "added_at": now_iso(),
                "status": "pending_wordpress_review",
                "working_title": draft.get("working_title") or draft.get("title") or "",
                "target_keyword": draft.get("target_keyword") or draft.get("focus_keyphrase") or "",
                "notes": "Created automatically for WordPress-stage review notification.",
                "telegram_notified": False,
                "telegram_notified_at": None,
                "updated_at": now_iso(),
            }
            review_items.append(review)
            review_queue["review_items"] = review_items
        else:
            review["working_title"] = (
                review.get("working_title")
                or draft.get("working_title")
                or draft.get("title")
                or ""
            )
            review["target_keyword"] = (
                review.get("target_keyword")
                or draft.get("target_keyword")
                or draft.get("focus_keyphrase")
                or ""
            )
            review["status"] = "pending_wordpress_review"
            review["telegram_notified"] = False
            review["telegram_notified_at"] = None
            review["updated_at"] = now_iso()

        message = build_message(review, workspace)
        keyboard = build_decision_keyboard(
            specific_draft_id,
            workspace_id,
            workspace.get("language", "en"),
            workspace=workspace
        )

        print("\n" + "=" * 60)
        print(f"TELEGRAM GROUP: {telegram_group}")
        print(f"TELEGRAM GROUP ID: {telegram_group_id}")
        print("=" * 60)
        print(message)
        print("=" * 60)

        if sending:
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
            save_json(review_queue_path, review_queue)

        print("\nNotifications processed: 1")
        print(f"Mode: {mode}")
        return

    # ------------------------------------------------------------
    # Existing normal pending-review mode.
    # ------------------------------------------------------------
    pending_reviews = [
        item for item in review_items
        if item.get("status") == "pending_review"
        and item.get("telegram_notified") is not True
        and draft_can_be_sent_for_review(item.get("draft_id"), workspace)
    ]

    if not pending_reviews:
        print("No pending examiner review notifications with generated content ready.")
        return

    sent_count = 0

    for review in pending_reviews:
        message = build_message(review, workspace)
        draft_id = review.get("draft_id")

        keyboard = build_decision_keyboard(
            draft_id,
            workspace_id,
            workspace.get("language", "en"),
            workspace=workspace
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