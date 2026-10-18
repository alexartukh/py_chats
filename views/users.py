from django.db import IntegrityError, transaction
from django.http import JsonResponse

from auth import token_service
from orm import User
from password_helper import hash_password, is_password_correct
from request_check_helper import (
    check_method,
    get_required_email,
    get_required_login,
    get_required_non_empty_string,
    read_json_object,
)


# Endpoint-ы пользователей: список, регистрация, вход, выход.
# Каждый endpoint - метод. В app.py создаётся один объект users_api = UsersApi(),
# и маршруты указывают на его методы: path("api/users", users_api.get_users).
# Django вызывает метод как обычную view-функцию: users_api.get_users(request).
class UsersApi:

    # Открытый endpoint: GET /api/users - все пользователи (публичная таблица форума)
    def get_users(self, request):
        data = list(
            User.objects
            .order_by("created_at", "user_id")
            .values("user_id", "login", "email", "created_at")
        )
        return JsonResponse(data, safe=False)

    # Ожидает POST с JSON-телом: {"login": "...", "email": "...", "password": "..."}
    # Создаёт пользователя и возвращает токен, login и email
    def create_new_user(self, request):
        error = check_method(request, "POST")
        if error is not None:
            return error

        body, error = read_json_object(request)
        if error is not None:
            return error

        # Префикс user_ - чтобы переменная не путалась с методом login этого класса
        # login - только латинские буквы и цифры, email - формат адреса (правила в request_check_helper)
        user_login, error = get_required_login(body, "login")
        if error is not None:
            return error

        user_email, error = get_required_email(body, "email")
        if error is not None:
            return error

        user_password, error = get_required_non_empty_string(body, "password")
        if error is not None:
            return error

        # Отдельные проверки, чтобы клиент знал, что именно занято
        if User.objects.filter(login=user_login).exists():
            return JsonResponse({"error": "login already exists"}, status=409)

        if User.objects.filter(email=user_email).exists():
            return JsonResponse({"error": "email already exists"}, status=409)

        # В БД сохраняется не пароль, а его хеш
        password_hash = hash_password(user_password)
        try:
            with transaction.atomic():
                user = User.objects.create(login=user_login, email=user_email, password=password_hash)
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

    # Ожидает POST с JSON-телом: {"login": "...", "password": "..."}
    def login(self, request):
        error = check_method(request, "POST")
        if error is not None:
            return error

        body, error = read_json_object(request)
        if error is not None:
            return error

        user_login, error = get_required_non_empty_string(body, "login")
        if error is not None:
            return error

        user_password, error = get_required_non_empty_string(body, "password")
        if error is not None:
            return error

        # Ищем пользователя только по логину: в БД лежит хеш, сравнить его с паролем в SQL нельзя
        user = (
            User.objects
            .filter(login=user_login)
            .values("user_id", "login", "email", "password")
            .first()
        )
        if user is None:
            return JsonResponse({"error": "invalid login or password"}, status=401)

        # Одинаковый текст ошибки для "нет такого логина" и "неверный пароль",
        # чтобы по ответу нельзя было узнать, существует ли логин
        if not is_password_correct(user_password, user["password"]):
            return JsonResponse({"error": "invalid login or password"}, status=401)

        # Ответ такой же, как после регистрации (create_new_user)
        token = token_service.create_token(user_id=user["user_id"])
        data = {
            "token": token,
            "login": user["login"],
            "email": user["email"],
        }
        return JsonResponse(data, status=200)

    # Ожидает POST без тела. Всегда отвечает 200.
    # Сервер токены не хранит и отозвать их не может: клиент сам удаляет токен у себя,
    # а сам токен перестанет действовать, когда истечёт его exp.
    def logout(self, request):
        error = check_method(request, "POST")
        if error is not None:
            return error

        return JsonResponse({"status": "ok"}, status=200)
