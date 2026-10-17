from django.http import JsonResponse

from orm import Topic
from request_check_helper import check_method, get_authorized_user_id, get_required_non_empty_string, read_json_object


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
