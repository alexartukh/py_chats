import json

from django.db import IntegrityError, transaction
from django.http import JsonResponse

from auth import token_service
from orm import User

def get_users(request):
    data = list(
        User.objects
        .order_by("created_at", "user_id")
        .values("user_id", "login", "created_at")
    )
    return JsonResponse(data, safe=False)

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
