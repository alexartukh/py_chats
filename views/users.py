import json

from django.db import IntegrityError, transaction
from django.http import JsonResponse

from auth import token_service
from orm import User

def get_users(request):
    data = list(
        User.objects
        .order_by("created_at", "user_id")
        .values("user_id", "login", "email", "created_at")
    )
    return JsonResponse(data, safe=False)

def create_new_user(request):
    # Ожидает POST с JSON-телом: {"login": "...", "email": "...", "password": "..."}
    # Создаёт пользователя и возвращает токен, login и email
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)

    if not isinstance(body, dict) or "login" not in body or "email" not in body or "password" not in body:
        return JsonResponse({"error": "login, email and password are required"}, status=400)

    # Префикс user_ - чтобы переменная не перекрывала функцию login из этого же файла
    user_login = body["login"]
    user_email = body["email"]
    user_password = body["password"]

    if not isinstance(user_login, str) or user_login == "":
        return JsonResponse({"error": "login must be a non-empty string"}, status=400)

    if not isinstance(user_email, str) or user_email == "":
        return JsonResponse({"error": "email must be a non-empty string"}, status=400)

    if not isinstance(user_password, str) or user_password == "":
        return JsonResponse({"error": "password must be a non-empty string"}, status=400)

    # Отдельные проверки, чтобы клиент знал, что именно занято
    if User.objects.filter(login=user_login).exists():
        return JsonResponse({"error": "login already exists"}, status=409)

    if User.objects.filter(email=user_email).exists():
        return JsonResponse({"error": "email already exists"}, status=409)

    # Пароль сохраняется открытым текстом, как и у существующих пользователей
    try:
        with transaction.atomic():
            user = User.objects.create(login=user_login, email=user_email, password=user_password)
    except IntegrityError:
        # Сработало ограничение UNIQUE на users.login или users.email:
        # кто-то занял логин или email между проверками выше и вставкой
        return JsonResponse({"error": "login or email already exists"}, status=409)

    token = token_service.create_token(user_id=user.user_id)
    data = {
        "token": token,
        "login": user_login,
        "email": user_email,
    }
    return JsonResponse(data, status=200)

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
        .values("user_id", "login", "email")
        .first()
    )
    if user is None:
        return JsonResponse({"error": "invalid login or password"}, status=401)

    # Ответ такой же, как после регистрации (create_new_user)
    token = token_service.create_token(user_id=user["user_id"])
    data = {
        "token": token,
        "login": user["login"],
        "email": user["email"],
    }
    return JsonResponse(data, status=200)

def logout(request):
    pass
