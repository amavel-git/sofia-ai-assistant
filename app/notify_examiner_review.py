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


def draft_validation_passed(draft_id, workspace):
    draft = find_draft_in_registry(draft_id, workspace)

    if not draft:
        return False

    return draft.get("validation", {}).get("status") == "passed"

def draft_has_wordpress_draft(draft_id, workspace):
    draft = find_draft_in_registry(draft_id, workspace)

    if not draft:
        return False

    upload = draft.get("wordpress_upload", {})
    update = draft.get("wordpress_update", {})

    return (
        upload.get("uploaded") is True
        and bool(upload.get("wordpress_id"))
    ) or (
        update.get("updated") is True
        and bool(update.get("wordpress_id"))
    )

    if not draft:
        return False

    upload = draft.get("wordpress_upload", {})
    update = draft.get("wordpress_update", {})

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

    update = draft.get("wordpress_update", {})
    upload = draft.get("wordpress_upload", {})

    return (
        update.get("wordpress_link")
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

    if len(content) > 1200:
        content = content[:1200].rsplit(" ", 1)[0] + "..."

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
        update.get("wordpress_id")
        or upload.get("wordpress_id")
        or ""
    )

    wordpress_link = (
        update.get("wordpress_link")
        or upload.get("wordpress_link")
        or ""
    )

    wordpress_status = (
        update.get("wordpress_status")
        or upload.get("wordpress_status")
        or ""
    )

    post_type = (
        update.get("post_type")
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
    template = get_template("draft_review", language)

    draft_id = item.get("draft_id")
    title = item.get("working_title")
    keyphrase = item.get("target_keyword")

    channels_text = format_enabled_channels(workspace, template)
    check_items = template.get("check_items", [])
    check_items_text = "\n".join([f"- {item}" for item in check_items])
    content_preview = get_draft_content_preview(draft_id, workspace)
    preview_label = get_preview_label(language)
    wp_info = get_wordpress_review_info(draft_id, workspace)

    normalized_language = normalize_language(language)

    if wp_info.get("has_wordpress_draft"):
        wordpress_link = wp_info.get("wordpress_link") or "Link not available"
        wordpress_id = wp_info.get("wordpress_id") or "N/A"
        wordpress_status = wp_info.get("wordpress_status") or "draft"

        if normalized_language.startswith("pt"):
            return f"""
[SOFIA – RASCUNHO WORDPRESS ATUALIZADO]

ID do rascunho: {draft_id}
Workspace: {workspace.get("workspace_id")}
País: {workspace.get("country")}
Idioma: {workspace.get("language")}

Título:
{title}

Frase-chave principal:
{keyphrase}

Rascunho WordPress:
{wordpress_link}

ID no WordPress:
{wordpress_id}

Estado no WordPress:
{wordpress_status}

Canais onde o conteúdo poderá ser usado:
{channels_text}

Pré-visualização do conteúdo:
{content_preview}

Tarefa do examinador:
Por favor, reveja o rascunho diretamente no WordPress e confirme se está pronto para revisão/publicação manual.

Por favor, confirme:
- O conteúdo está profissionalmente correto?
- A terminologia está adequada ao mercado local?
- O Yoast SEO está adequado?
- Existe algum risco legal, cultural ou comercial?
- O serviço descrito está realmente disponível neste país?

A publicação final ao vivo NÃO foi feita automaticamente.

Próximo passo:
- Clique em Finalizado se o rascunho está pronto para revisão/publicação manual no WordPress.
- Clique em Rever se deseja que a Sofia faça alterações ao rascunho.

Use os botões abaixo para finalizar ou solicitar alterações.
""".strip()

        if normalized_language == "es":
            return f"""
[SOFIA – BORRADOR WORDPRESS ACTUALIZADO]

ID del borrador: {draft_id}
Workspace: {workspace.get("workspace_id")}
País: {workspace.get("country")}
Idioma: {workspace.get("language")}

Título:
{title}

Frase clave principal:
{keyphrase}

Borrador WordPress:
{wordpress_link}

ID de WordPress:
{wordpress_id}

Estado en WordPress:
{wordpress_status}

Canales donde se podrá usar el contenido:
{channels_text}

Vista previa del contenido:
{content_preview}

Tarea del examinador:
Por favor, revise el borrador directamente en WordPress y confirme si está listo para revisión/publicación manual.

Por favor, confirme:
- ¿El contenido es profesionalmente correcto?
- ¿La terminología es adecuada para el mercado local?
- ¿El Yoast SEO está adecuado?
- ¿Existe algún riesgo legal, cultural o comercial?
- ¿El servicio descrito está realmente disponible en este país?

La publicación final en vivo NO se ha realizado automáticamente.

Próximo paso:
- Haga clic en Finalizado si el borrador está listo para revisión/publicación manual en WordPress.
- Haga clic en Revisar si desea que Sofia haga cambios en el borrador.

Use los botones de abajo para finalizar o solicitar cambios.
""".strip()

        if normalized_language == "fr":
            return f"""
[SOFIA – BROUILLON WORDPRESS MIS À JOUR]

ID du brouillon : {draft_id}
Workspace : {workspace.get("workspace_id")}
Pays : {workspace.get("country")}
Langue : {workspace.get("language")}

Titre :
{title}

Requête principale :
{keyphrase}

Brouillon WordPress :
{wordpress_link}

ID WordPress :
{wordpress_id}

Statut WordPress :
{wordpress_status}

Canaux où le contenu pourra être utilisé :
{channels_text}

Aperçu du contenu :
{content_preview}

Tâche de l’examinateur :
Veuillez examiner le brouillon directement dans WordPress et confirmer s’il est prêt pour révision/publication manuelle.

Veuillez confirmer :
- Le contenu est-il professionnellement correct ?
- La terminologie est-elle adaptée au marché local ?
- Le Yoast SEO est-il approprié ?
- Existe-t-il un risque juridique, culturel ou commercial ?
- Le service décrit est-il réellement disponible dans ce pays ?

La publication finale en ligne n’a PAS été effectuée automatiquement.

Prochaine étape :
- Cliquez sur Terminé si le brouillon est prêt pour révision/publication manuelle dans WordPress.
- Cliquez sur Réviser si vous souhaitez que Sofia modifie le brouillon.

Utilisez les boutons ci-dessous pour terminer ou demander des modifications.
""".strip()

        return f"""
[SOFIA – WORDPRESS DRAFT UPDATED]

Draft ID: {draft_id}
Workspace: {workspace.get("workspace_id")}
Country: {workspace.get("country")}
Language: {workspace.get("language")}

Title:
{title}

Focus Keyphrase:
{keyphrase}

WordPress Draft:
{wordpress_link}

WordPress ID:
{wordpress_id}

WordPress Status:
{wordpress_status}

Channels where this content may be used:
{channels_text}

Content preview:
{content_preview}

Examiner task:
Please review the draft directly in WordPress and confirm whether it is ready for manual review/publication.

Please confirm:
- Is the content professionally correct?
- Is the terminology appropriate for the local market?
- Is the Yoast SEO appropriate?
- Is there any legal, cultural, or commercial risk?
- Is the described service actually available in this country?

Final live publication has NOT been done automatically.

Next step:
- Click Completed if the draft is ready for manual WordPress review/publication.
- Click Revise if you want Sofia to make changes to the draft.

Use the buttons below to complete or request changes.
""".strip()

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

{preview_label}:
{content_preview}

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


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python app/notify_examiner_review.py WORKSPACE_ID --preview")
        print("  python app/notify_examiner_review.py WORKSPACE_ID --send")
        print("  python app/notify_examiner_review.py WORKSPACE_ID --send-draft DRAFT_ID")
        print("Example:")
        print("  python app/notify_examiner_review.py local.ao --send")
        print("  python app/notify_examiner_review.py local.ao --send-draft DRAFT-0001")
        return

    workspace_id = sys.argv[1]

    mode = sys.argv[2] if len(sys.argv) > 2 else "--preview"
    specific_draft_id = None

    if mode == "--send-draft":
        if len(sys.argv) < 4:
            print("Usage:")
            print("  python app/notify_examiner_review.py WORKSPACE_ID --send-draft DRAFT_ID")
            return
        specific_draft_id = sys.argv[3]

    if mode not in ["--preview", "--send", "--send-draft"]:
        print("Invalid mode. Use --preview, --send, or --send-draft.")
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

    sending = mode in ["--send", "--send-draft"]

    if sending and not telegram_group_id:
        print(f"No telegram_group_id found for workspace: {workspace_id}")
        return

    bot_token = os.getenv("SOFIA_TELEGRAM_BOT_TOKEN")
    if bot_token:
        bot_token = bot_token.strip().strip('"').strip("'")

    if sending and not bot_token:
        print("Missing environment variable: SOFIA_TELEGRAM_BOT_TOKEN")
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

        if draft.get("validation", {}).get("status") != "passed":
            print(f"Draft validation has not passed: {specific_draft_id}")
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
        and draft_validation_passed(item.get("draft_id"), workspace)
    ]

    if not pending_reviews:
        print("No pending examiner review notifications with validation status 'passed'.")
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