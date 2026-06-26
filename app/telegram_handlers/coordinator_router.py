from telegram_handlers.content_request_handler import (
    handle_content_request,
)


def route_examiner_request(
        *,
        parsed_request,
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
    if parsed_request.get("requires_opportunity"):

        return handle_content_request(
            workspace_id=workspace_id,
            workspace=workspace,
            raw_request=raw_request,
            requested_by=requested_by,
            chat_id=chat_id,
            message_id=message_id,
            send_message=send_message,
            build_keyboard=build_keyboard,
            load_json=load_json,
            save_json=save_json,
            now_iso=now_iso,
            log=log,
        )

    routing_target = parsed_request.get(
        "routing_target",
        "",
    )

    log(
        f"Coordinator routing target={routing_target}"
    )

    return False
