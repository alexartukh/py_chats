from django.http import JsonResponse

from orm import Topic
from request_check_helper import (
    check_method,
    get_authorized_user_id,
    get_query_positive_int,
    get_required_non_empty_string,
    read_json_object,
)


# Endpoint-ы тем: список, создание, одна тема.
# Каждый endpoint - метод. В app.py создаётся один объект topics_api = TopicsApi(),
# и маршруты указывают на его методы: path("api/topics", topics_api.get_topics).
class TopicsApi:

    # Открытый endpoint: GET /api/topics - все темы, от старых к новым
    def get_topics(self, request):
        data = list(
            Topic.objects
            .order_by("created_at", "topic_id")
            .values("topic_id", "title", "created_by_user__login", "created_at")
        )
        return JsonResponse(data, safe=False)

    # Защищённый endpoint: нужен заголовок "Authorization: Bearer <token>"
    # Ожидает POST с JSON-телом: {"title": "..."}
    def create_new_topic(self, request):
        error = check_method(request, "POST")
        if error is not None:
            return error

        user_id, error = get_authorized_user_id(request)
        if error is not None:
            return error

        body, error = read_json_object(request)
        if error is not None:
            return error

        title, error = get_required_non_empty_string(body, "title")
        if error is not None:
            return error

        topic = Topic.objects.create(title=title, created_by_user_id=user_id)

        data = {
            "topic_id": topic.topic_id,
            "title": topic.title,
            "created_by_user_id": topic.created_by_user_id,
            "created_at": topic.created_at,
        }
        return JsonResponse(data, status=200)

    # Открытый endpoint: GET /api/topic?topic_id=<id>
    # Возвращает одну тему: {"topic_id", "title", "created_by_user__login", "created_at"}
    def get_topic(self, request):
        error = check_method(request, "GET")
        if error is not None:
            return error

        topic_id, error = get_query_positive_int(request, "topic_id")
        if error is not None:
            return error

        topic = (
            Topic.objects
            .filter(topic_id=topic_id)
            .values("topic_id", "title", "created_by_user__login", "created_at")
            .first()
        )
        if topic is None:
            return JsonResponse({"error": "topic not found"}, status=404)

        return JsonResponse(topic, status=200)
