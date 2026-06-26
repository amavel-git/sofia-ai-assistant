from pathlib import Path

import create_internal_opportunity
import notify_opportunity_review

SOFIA_ROOT = Path(__file__).resolve().parents[2]


def handle_content_request(
        *,
        workspace_id,
        workspace,
        raw_request,
        requested_by,
        chat_id,
        message_id,
        send_message,
        build_keyboard,
        load_json,
        save_json,
        now_iso,
        log,
):
    try:
        opportunity, opportunities_path = (
            create_internal_opportunity.create_internal_opportunity(
                workspace_id=workspace_id,
                raw_request=raw_request,
                requested_by=requested_by,
                telegram_chat_id=chat_id,
                telegram_message_id=message_id,
            )
        )

        opportunity_id = (
            opportunity.get("id")
            or opportunity.get("opportunity_id")
        )

        message = notify_opportunity_review.build_message(
            opportunity,
            workspace,
        )

        keyboard = build_keyboard(
            opportunity_id,
            workspace_id,
        )

        send_message(
            chat_id,
            message,
            reply_to_message_id=message_id,
            reply_markup=keyboard,
        )

        opportunity["telegram_notified"] = True
        opportunity["telegram_notified_at"] = now_iso()
        opportunity["updated_at"] = now_iso()

        data = load_json(
            opportunities_path,
            {"opportunities": []},
        )

        for stored in data.get("opportunities", []):
            stored_id = (
                stored.get("id")
                or stored.get("opportunity_id")
            )

            if stored_id == opportunity_id:
                stored.update(opportunity)
                break

        save_json(opportunities_path, data)

        log(
            f"CREATED internal opportunity "
            f"workspace={workspace_id} "
            f"chat_id={chat_id} "
            f"opportunity={opportunity_id}"
        )

        return True

    except Exception as e:

        log(
            f"ERROR creating internal opportunity: "
            f"{type(e).__name__}: {e}"
        )

        send_message(
            chat_id,
            (
                "⚠️ Sofia could not create the internal content opportunity.\n\n"
                f"Workspace: {workspace_id}\n"
                f"Error: {type(e).__name__}"
            ),
            reply_to_message_id=message_id,
        )

        return True
