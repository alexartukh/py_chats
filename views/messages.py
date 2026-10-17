import json

from django.http import JsonResponse

from auth import token_service
from orm import Message, Topic


def messages(request):
    # Открытый endpoint: GET /api/messages?topic_id=<id>
    # Возвращает все сообщения темы в порядке дерева:
    # сообщение, сразу за ним все его ответы (рекурсивно), затем следующее сообщение того же уровня.
    # Сообщения одного уровня идут от старых к новым.
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)

    topic_id = request.GET.get("topic_id", "")
    if not topic_id.isdigit():
        return JsonResponse({"error": "topic_id must be a positive integer"}, status=400)

    if not Topic.objects.filter(topic_id=int(topic_id)).exists():
        return JsonResponse({"error": "topic not found"}, status=404)

    # неструктурированный ответ
    rows = list(
        Message.objects
        .filter(topic_id=int(topic_id))
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
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    user_id = token_service.get_user_id_from_request(request)
    if user_id is None:
        return JsonResponse({"error": "unauthorized"}, status=401)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)

    if not isinstance(body, dict):
        return JsonResponse({"error": "body must be a json object"}, status=400)

    for key in ("login", "email", "topic_id", "parent_message_id", "t"):
        if key not in body:
            return JsonResponse({"error": key + " is required"}, status=400)

    user_login = body["login"]
    user_email = body["email"]
    topic_id = body["topic_id"]
    parent_message_id = body["parent_message_id"]
    t = body["t"]

    if not isinstance(user_login, str) or user_login == "":
        return JsonResponse({"error": "login must be a non-empty string"}, status=400)

    if not isinstance(user_email, str) or user_email == "":
        return JsonResponse({"error": "email must be a non-empty string"}, status=400)

    # bool в Python - подвид int (True == 1), поэтому исключаем его явно
    if not isinstance(topic_id, int) or isinstance(topic_id, bool):
        return JsonResponse({"error": "topic_id must be an integer"}, status=400)

    if parent_message_id is not None:
        if not isinstance(parent_message_id, int) or isinstance(parent_message_id, bool):
            return JsonResponse({"error": "parent_message_id must be an integer or null"}, status=400)

    if not isinstance(t, str) or t == "":
        return JsonResponse({"error": "t must be a non-empty string"}, status=400)

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
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    user_id = token_service.get_user_id_from_request(request)
    if user_id is None:
        return JsonResponse({"error": "unauthorized"}, status=401)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)

    if not isinstance(body, dict) or "message_id" not in body:
        return JsonResponse({"error": "message_id is required"}, status=400)

    message_id = body["message_id"]

    # bool в Python - подвид int (True == 1), поэтому исключаем его явно
    if not isinstance(message_id, int) or isinstance(message_id, bool):
        return JsonResponse({"error": "message_id must be an integer"}, status=400)

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
