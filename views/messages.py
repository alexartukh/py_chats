from django.http import JsonResponse

from orm import Message, Topic, User
from request_check_helper import (
    check_method,
    get_authorized_user_id,
    get_query_positive_int,
    get_required_int,
    get_required_int_or_null,
    get_required_non_empty_string,
    read_json_object,
)


def messages(request):
    # Открытый endpoint: GET /api/messages?topic_id=<id>
    # Возвращает все сообщения темы в порядке дерева:
    # сообщение, сразу за ним все его ответы (рекурсивно), затем следующее сообщение того же уровня.
    # Сообщения одного уровня идут от старых к новым.
    error = check_method(request, "GET")
    if error is not None:
        return error

    topic_id, error = get_query_positive_int(request, "topic_id")
    if error is not None:
        return error

    if not Topic.objects.filter(topic_id=topic_id).exists():
        return JsonResponse({"error": "topic not found"}, status=404)

    # неструктурированный ответ
    rows = list(
        Message.objects
        .filter(topic_id=topic_id)
        .order_by("created_at", "message_id")
        .values("message_id", "parent_message_id", "t", "user_id", "user__login", "created_at")
    )

    # Раскладываем записи по дереву: корневые сообщения отдельно,
    # ответы - в списки по message_id родителя.
    # Списки сохраняют порядок из запроса (от старых к новым).
    roots = []
    children_by_parent_id = {}
    for row in rows:
        parent_id = row["parent_message_id"]
        if parent_id is None:
            roots.append(row)
        else:
            if parent_id not in children_by_parent_id:
                children_by_parent_id[parent_id] = []
            children_by_parent_id[parent_id].append(row)

    data = []

    # Рекурсивно проставляет depth сообщению и всем его ответам
    # и складывает их в data в порядке дерева: сообщение, затем его ответы.
    def place_with_depth(row, depth):
        row["depth"] = depth
        data.append(row)

        if row["message_id"] in children_by_parent_id:
            for child in children_by_parent_id[row["message_id"]]:
                place_with_depth(child, depth + 1)

    for root in roots:
        place_with_depth(root, 0)

    return JsonResponse(data, safe=False, status=200)

def create_new_message(request):
    # Защищённый endpoint: нужен заголовок "Authorization: Bearer <token>", автор берётся из токена
    # Ожидает POST с JSON-телом:
    # {"login": "...", "email": "...", "topic_id": 1, "parent_message_id": null, "t": "..."}
    # parent_message_id: null - корневое сообщение, число - ответ на это сообщение
    error = check_method(request, "POST")
    if error is not None:
        return error

    user_id, error = get_authorized_user_id(request)
    if error is not None:
        return error

    body, error = read_json_object(request)
    if error is not None:
        return error

    user_login, error = get_required_non_empty_string(body, "login")
    if error is not None:
        return error

    user_email, error = get_required_non_empty_string(body, "email")
    if error is not None:
        return error

    topic_id, error = get_required_int(body, "topic_id")
    if error is not None:
        return error

    parent_message_id, error = get_required_int_or_null(body, "parent_message_id")
    if error is not None:
        return error

    t, error = get_required_non_empty_string(body, "t")
    if error is not None:
        return error

    # login и email из формы должны принадлежать тому же пользователю, что и токен
    if not User.objects.filter(user_id=user_id, login=user_login, email=user_email).exists():
        return JsonResponse({"error": "login and email do not match the token"}, status=403)

    if not Topic.objects.filter(topic_id=topic_id).exists():
        return JsonResponse({"error": "topic not found"}, status=404)

    # Родитель должен существовать и лежать в той же теме - база это не проверяет
    if parent_message_id is not None:
        parent = (
            Message.objects
            .filter(message_id=parent_message_id)
            .values("topic_id")
            .first()
        )
        if parent is None:
            return JsonResponse({"error": "parent message not found"}, status=404)
        if parent["topic_id"] != topic_id:
            return JsonResponse({"error": "parent message belongs to another topic"}, status=400)

    message = Message.objects.create(
        topic_id=topic_id,
        parent_message_id=parent_message_id,
        user_id=user_id,
        t=t,
    )

    data = {
        "message_id": message.message_id,
        "parent_message_id": message.parent_message_id,
        "topic_id": message.topic_id,
        "user_id": message.user_id,
        "t": message.t,
        "created_at": message.created_at,
    }
    return JsonResponse(data, status=200)

def delete_existing_message(request):
    # Защищённый endpoint: нужен заголовок "Authorization: Bearer <token>"
    # Ожидает POST с JSON-телом: {"message_id": 1}
    # Удалить можно только своё сообщение. Вместе с ним удаляются все ответы на него на любую глубину,
    # в том числе ответы других пользователей (on_delete=CASCADE у Message.parent_message).
    error = check_method(request, "POST")
    if error is not None:
        return error

    user_id, error = get_authorized_user_id(request)
    if error is not None:
        return error

    body, error = read_json_object(request)
    if error is not None:
        return error

    message_id, error = get_required_int(body, "message_id")
    if error is not None:
        return error

    message = (
        Message.objects
        .filter(message_id=message_id)
        .values("user_id")
        .first()
    )
    if message is None:
        return JsonResponse({"error": "message not found"}, status=404)

    if message["user_id"] != user_id:
        return JsonResponse({"error": "only the author can delete the message"}, status=403)

    # delete() возвращает (сколько строк удалено всего, {модель: сколько удалено})
    deleted_count, deleted_by_model = Message.objects.filter(message_id=message_id).delete()

    data = {
        "message_id": message_id,
        "deleted_count": deleted_count,
    }
    return JsonResponse(data, status=200)
