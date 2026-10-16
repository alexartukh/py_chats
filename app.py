import json
import os
import sys
from urllib.parse import urlparse

import django
from django.apps import AppConfig
from django.conf import settings
from django.core.management import execute_from_command_line
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.urls import path
from dotenv import load_dotenv

class OrmConfig(AppConfig):
    # Модели из orm.py регистрируются под этой меткой (app_label = "orm")
    name = "__main__"
    label = "orm"

load_dotenv()
db_url = urlparse(os.environ["DATABASE_URL"])

settings.configure(
    DEBUG=True,
    ROOT_URLCONF=__name__,
    SECRET_KEY="dev",
    INSTALLED_APPS=["__main__.OrmConfig"],
    DATABASES={
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": db_url.path.lstrip("/"),
            "USER": db_url.username,
            "PASSWORD": db_url.password,
            "HOST": db_url.hostname,
            "PORT": db_url.port or 5432,
        }
    },
)
django.setup()

from orm import Message, Topic, User
from auth import TokenService

token_service = TokenService(
    secret_key=os.environ["JWT_SECRET"],
    algorithm="HS256",
    lifetime_seconds=3600,
)

def get_topics(request):
    data = list(
        Topic.objects
        .order_by("created_at", "topic_id")
        .values("topic_id", "title", "created_by_user__login", "created_at")
    )
    return JsonResponse(data, safe=False)

def get_users(request):
    data = list(
        User.objects
        .order_by("created_at", "user_id")
        .values("user_id", "login", "created_at")
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

def create_new_user(request):
    # Ожидает POST с JSON-телом: {"login": "...", "password": "..."}
    # Создаёт пользователя и сразу возвращает токен, как login
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)

    if not isinstance(body, dict) or "login" not in body or "password" not in body:
        return JsonResponse({"error": "login and password are required"}, status=400)

    if not isinstance(body["login"], str) or not isinstance(body["password"], str) \
            or body["login"] == "" or body["password"] == "":
        return JsonResponse({"error": "login and password must be non-empty strings"}, status=400)

    # Пароль сохраняется открытым текстом, как и у существующих пользователей
    try:
        with transaction.atomic():
            user = User.objects.create(login=body["login"], password=body["password"])
    except IntegrityError:
        # Сработало ограничение UNIQUE на users.login
        return JsonResponse({"error": "login already exists"}, status=409)

    token = token_service.create_token(user_id=user.user_id)
    return JsonResponse({"token": token}, status=200)

def login(request):
    # Ожидает POST с JSON-телом: {"login": "...", "password": "..."}
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)

    if not isinstance(body, dict) or "login" not in body or "password" not in body:
        return JsonResponse({"error": "login and password are required"}, status=400)

    # Пароли в БД хранятся открытым текстом, поэтому сравниваются напрямую
    user = (
        User.objects
        .filter(login=body["login"], password=body["password"])
        .values("user_id")
        .first()
    )
    if user is None:
        return JsonResponse({"error": "invalid login or password"}, status=401)

    token = token_service.create_token(user_id=user["user_id"])
    return JsonResponse({"token": token}, status=200)

def logout(request):
    pass

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

urlpatterns = [
    path("api/topics", get_topics),
    path("api/users", get_users),
    path("api/login", login),
    path("api/logout", logout),
    path("api/create_new_topic", create_new_topic),
    path("api/create_new_user", create_new_user),
    path("api/messages", messages),
]

execute_from_command_line(sys.argv)
