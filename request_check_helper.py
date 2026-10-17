# Помощники для проверки входных данных запроса во view-функциях.
#
# Все функции, кроме check_method, возвращают пару (значение, ошибка):
#   - если всё в порядке: (значение, None)
#   - если нет:           (None, JsonResponse с ошибкой), и view должна сразу вернуть эту ошибку
#
# Пример:
#   body, error = read_json_object(request)
#   if error is not None:
#       return error
#
# Импортирует auth (а через него orm), поэтому импортировать можно только после django.setup().

import json
import os
import re

from django.http import JsonResponse

from auth import token_service


# Возвращает None, если метод запроса совпадает с method ("GET", "POST"), иначе ответ 405
def check_method(request, method):
    if request.method != method:
        return JsonResponse({"error": "method not allowed"}, status=405)
    return None


# Берёт user_id из заголовка "Authorization: Bearer <token>". Ошибка - 401
def get_authorized_user_id(request):
    user_id = token_service.get_user_id_from_request(request)
    if user_id is None:
        return None, JsonResponse({"error": "unauthorized"}, status=401)
    return user_id, None


# Разбирает тело запроса как JSON-объект ({...}). Ошибка - 400
def read_json_object(request):
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return None, JsonResponse({"error": "invalid json"}, status=400)

    if not isinstance(body, dict):
        return None, JsonResponse({"error": "body must be a json object"}, status=400)

    return body, None


# Значение body[key]: поле должно быть, и это должна быть непустая строка. Ошибка - 400
def get_required_non_empty_string(body, key):
    if key not in body:
        return None, JsonResponse({"error": key + " is required"}, status=400)

    value = body[key]
    if not isinstance(value, str) or value == "":
        return None, JsonResponse({"error": key + " must be a non-empty string"}, status=400)

    return value, None


# Значение body[key]: поле должно быть, и это должно быть целое число. Ошибка - 400
def get_required_int(body, key):
    if key not in body:
        return None, JsonResponse({"error": key + " is required"}, status=400)

    value = body[key]
    # bool в Python - подвид int (True == 1), поэтому исключаем его явно
    if not isinstance(value, int) or isinstance(value, bool):
        return None, JsonResponse({"error": key + " must be an integer"}, status=400)

    return value, None


# Значение body[key]: поле должно быть, и это целое число или null (вернётся None). Ошибка - 400
def get_required_int_or_null(body, key):
    if key not in body:
        return None, JsonResponse({"error": key + " is required"}, status=400)

    value = body[key]
    if value is None:
        return None, None

    # bool в Python - подвид int (True == 1), поэтому исключаем его явно
    if not isinstance(value, int) or isinstance(value, bool):
        return None, JsonResponse({"error": key + " must be an integer or null"}, status=400)

    return value, None


# Значение body[key]: поле должно быть, и это непустая строка или null (вернётся None). Ошибка - 400
def get_required_non_empty_string_or_null(body, key):
    if key not in body:
        return None, JsonResponse({"error": key + " is required"}, status=400)

    value = body[key]
    if value is None:
        return None, None

    if not isinstance(value, str) or value == "":
        return None, JsonResponse({"error": key + " must be a non-empty string or null"}, status=400)

    return value, None


# Значение параметра из адреса (?key=123): должно быть положительным целым числом. Ошибка - 400
def get_query_positive_int(request, key):
    value = request.GET.get(key, "")
    if not value.isdigit():
        return None, JsonResponse({"error": key + " must be a positive integer"}, status=400)

    return int(value), None


# Копия isMessageCorrect из клиента (Django-React-Client/src/messageMarkup.js), правила те же.
# True - в тексте только разрешённые теги (<i>, <strong>, <code>, <a href="" title="">),
# все закрыты и правильно вложены. <a> внутри <a> быть не может.
#
# Отличие от JS: в Python "$" в регулярном выражении пропускает "\n" в конце строки,
# а в JS - нет. Поэтому вместо "^...$" используется re.fullmatch - он, как и JS, требует
# совпадения всей строки целиком.
def is_message_markup_correct(text):
    tags = []
    is_inside_a = False

    for match in re.finditer(r"<([^>]+?)>", text):
        content = match.group(1)

        if content == "i":
            tags.append("OPEN_I")
        elif content == "/i":
            if len(tags) == 0 or tags.pop() != "OPEN_I":
                return False
        elif content == "strong":
            tags.append("OPEN_S")
        elif content == "/strong":
            if len(tags) == 0 or tags.pop() != "OPEN_S":
                return False
        elif content == "code":
            tags.append("OPEN_C")
        elif content == "/code":
            if len(tags) == 0 or tags.pop() != "OPEN_C":
                return False
        elif re.fullmatch(r'a href="([^"<>]*?)"( title="[^"<>]*?")?', content) is not None:
            if is_inside_a:
                return False

            href = re.fullmatch(r'a href="([^"<>]*?)"( title="[^"<>]*?")?', content).group(1)
            # re.match, как и JS-шаблон с "^", проверяет только начало строки
            if href == "" or re.match(r"https?://.{3,}", href) is not None:
                tags.append("OPEN_A")
                is_inside_a = True
            else:
                return False
        elif content == "/a":
            if len(tags) == 0 or tags.pop() != "OPEN_A":
                return False
            else:
                is_inside_a = False
        else:
            return False

    if len(tags) > 0:
        return False

    return True


# Значение body[key]: непустая строка, в которой разметка проходит is_message_markup_correct. Ошибка - 400
def get_required_message_text(body, key):
    value, error = get_required_non_empty_string(body, key)
    if error is not None:
        return None, error

    if not is_message_markup_correct(value):
        return None, JsonResponse(
            {"error": key + " contains forbidden or unclosed tags (allowed: <i>, <strong>, <code>, <a href=\"\" title=\"\">)"},
            status=400,
        )

    return value, None


# Максимальная длина login и email - как у колонок users.login и users.email VARCHAR(255)
MAX_LOGIN_LENGTH = 255
MAX_EMAIL_LENGTH = 255


# Значение body[key]: поле User Name из ТЗ - только латинские буквы и цифры, не длиннее 255. Ошибка - 400.
# Набор символов задан явно [A-Za-z0-9], а не через \w: \w в Python пропускает ещё "_"
# и буквы любых алфавитов (кириллицу и т.д.).
def get_required_login(body, key):
    value, error = get_required_non_empty_string(body, key)
    if error is not None:
        return None, error

    if len(value) > MAX_LOGIN_LENGTH:
        return None, JsonResponse({"error": key + " is too long"}, status=400)

    if re.fullmatch(r"[A-Za-z0-9]+", value) is None:
        return None, JsonResponse({"error": key + " must contain only latin letters and digits"}, status=400)

    return value, None


# Значение body[key]: адрес вида "что-то@домен.зона", не длиннее 255. Ошибка - 400.
# Проверка простая и явная: ровно один "@", до него хотя бы один символ, после - домен с точкой,
# без пробелов. Существует ли такой адрес на самом деле, не проверяется.
def get_required_email(body, key):
    value, error = get_required_non_empty_string(body, key)
    if error is not None:
        return None, error

    if len(value) > MAX_EMAIL_LENGTH:
        return None, JsonResponse({"error": key + " is too long"}, status=400)

    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) is None:
        return None, JsonResponse({"error": key + " must be an email address like name@example.com"}, status=400)

    return value, None


# Максимальная длина адреса сайта - как у колонки messages.site VARCHAR(2048)
MAX_SITE_LENGTH = 2048


# Значение body[key]: поле Home page из ТЗ - необязательное.
# Нет поля, null или пустая строка - вернётся None (сайт не указан).
# Иначе это адрес, начинающийся с http:// или https://, без пробелов, кавычек и <>, не длиннее 2048. Ошибка - 400.
# Схема ограничена http/https, чтобы адрес нельзя было превратить в ссылку вида javascript:...
def get_optional_site(body, key):
    if key not in body:
        return None, None

    value = body[key]
    if value is None:
        return None, None

    if not isinstance(value, str):
        return None, JsonResponse({"error": key + " must be a string or null"}, status=400)

    if value == "":
        return None, None

    if len(value) > MAX_SITE_LENGTH:
        return None, JsonResponse({"error": key + " is too long"}, status=400)

    if re.fullmatch(r"https?://[^\s<>\"']+", value) is None:
        return None, JsonResponse({"error": key + " must be a url starting with http:// or https://"}, status=400)

    return value, None


# CLIENT_IP_FROM_X_FORWARDED_FOR в .env: строго "true" или "false", любое другое значение - ошибка запуска.
#   false - сервер работает без прокси (локально): IP клиента - адрес соединения, REMOTE_ADDR.
#   true  - сервер стоит за одним прокси (например, Render): REMOTE_ADDR - это адрес прокси,
#           а настоящий IP прокси дописывает последним в заголовок X-Forwarded-For.
#           Брать нужно именно последний: всё, что левее, мог прислать сам клиент.
client_ip_from_x_forwarded_for_value = os.environ["CLIENT_IP_FROM_X_FORWARDED_FOR"]
if client_ip_from_x_forwarded_for_value == "true":
    CLIENT_IP_FROM_X_FORWARDED_FOR = True
elif client_ip_from_x_forwarded_for_value == "false":
    CLIENT_IP_FROM_X_FORWARDED_FOR = False
else:
    raise ValueError('CLIENT_IP_FROM_X_FORWARDED_FOR must be "true" or "false", got: ' + client_ip_from_x_forwarded_for_value)


# IP клиента строкой или None, если его не удалось определить. Режим - см. CLIENT_IP_FROM_X_FORWARDED_FOR
def get_client_ip(request):
    if CLIENT_IP_FROM_X_FORWARDED_FOR:
        header = request.headers.get("X-Forwarded-For", "")
        parts = []
        for part in header.split(","):
            if part.strip() != "":
                parts.append(part.strip())
        if len(parts) == 0:
            return None
        return parts[len(parts) - 1]

    remote_addr = request.META.get("REMOTE_ADDR", "")
    if remote_addr == "":
        return None
    return remote_addr


# Заголовок User-Agent строкой или None, если браузер его не прислал. Браузер добавляет его сам
def get_user_agent(request):
    user_agent = request.headers.get("User-Agent", "")
    if user_agent == "":
        return None
    return user_agent

