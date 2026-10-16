from django.http import JsonResponse

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
    pass
