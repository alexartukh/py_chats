import json

from django.http import JsonResponse

from auth import token_service
from orm import Topic


def get_topics(request):
    data = list(
        Topic.objects
        .order_by("created_at", "topic_id")
        .values("topic_id", "title", "created_by_user__login", "created_at")
    )
    return JsonResponse(data, safe=False)

def create_new_topic(request):
    # Защищённый endpoint: нужен заголовок "Authorization: Bearer <token>"
    # Ожидает POST с JSON-телом: {"title": "..."}
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    user_id = token_service.get_user_id_from_request(request)
    if user_id is None:
        return JsonResponse({"error": "unauthorized"}, status=401)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)

    if not isinstance(body, dict) or not isinstance(body.get("title"), str) or body["title"] == "":
        return JsonResponse({"error": "title must be a non-empty string"}, status=400)

    topic = Topic.objects.create(title=body["title"], created_by_user_id=user_id)

    data = {
        "topic_id": topic.topic_id,
        "title": topic.title,
        "created_by_user_id": topic.created_by_user_id,
        "created_at": topic.created_at,
    }
    return JsonResponse(data, status=200)
