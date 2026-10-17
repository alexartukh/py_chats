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
import re

from django.http import JsonResponse

from auth import token_service


def check_method(request, method):
    # Возвращает None, если метод запроса совпадает с method ("GET", "POST"), иначе ответ 405
    if request.method != method:
        return JsonResponse({"error": "method not allowed"}, status=405)
    return None


def get_authorized_user_id(request):
    # Берёт user_id из заголовка "Authorization: Bearer <token>". Ошибка - 401
    user_id = token_service.get_user_id_from_request(request)
    if user_id is None:
        return None, JsonResponse({"error": "unauthorized"}, status=401)
    return user_id, None


def read_json_object(request):
    # Разбирает тело запроса как JSON-объект ({...}). Ошибка - 400
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return None, JsonResponse({"error": "invalid json"}, status=400)

    if not isinstance(body, dict):
        return None, JsonResponse({"error": "body must be a json object"}, status=400)

    return body, None


def get_required_non_empty_string(body, key):
    # Значение body[key]: поле должно быть, и это должна быть непустая строка. Ошибка - 400
    if key not in body:
        return None, JsonResponse({"error": key + " is required"}, status=400)

    value = body[key]
    if not isinstance(value, str) or value == "":
        return None, JsonResponse({"error": key + " must be a non-empty string"}, status=400)

    return value, None


def get_required_int(body, key):
    # Значение body[key]: поле должно быть, и это должно быть целое число. Ошибка - 400
    if key not in body:
        return None, JsonResponse({"error": key + " is required"}, status=400)

    value = body[key]
    # bool в Python - подвид int (True == 1), поэтому исключаем его явно
    if not isinstance(value, int) or isinstance(value, bool):
        return None, JsonResponse({"error": key + " must be an integer"}, status=400)

    return value, None


def get_required_int_or_null(body, key):
    # Значение body[key]: поле должно быть, и это целое число или null (вернётся None). Ошибка - 400
    if key not in body:
        return None, JsonResponse({"error": key + " is required"}, status=400)

    value = body[key]
    if value is None:
        return None, None

    # bool в Python - подвид int (True == 1), поэтому исключаем его явно
    if not isinstance(value, int) or isinstance(value, bool):
        return None, JsonResponse({"error": key + " must be an integer or null"}, status=400)

    return value, None


def get_required_non_empty_string_or_null(body, key):
    # Значение body[key]: поле должно быть, и это непустая строка или null (вернётся None). Ошибка - 400
    if key not in body:
        return None, JsonResponse({"error": key + " is required"}, status=400)

    value = body[key]
    if value is None:
        return None, None

    if not isinstance(value, str) or value == "":
        return None, JsonResponse({"error": key + " must be a non-empty string or null"}, status=400)

    return value, None


def get_query_positive_int(request, key):
    # Значение параметра из адреса (?key=123): должно быть положительным целым числом. Ошибка - 400
    value = request.GET.get(key, "")
    if not value.isdigit():
        return None, JsonResponse({"error": key + " must be a positive integer"}, status=400)

    return int(value), None


def is_message_markup_correct(text):
    # Копия isMessageCorrect из клиента (Django-React-Client/src/messageMarkup.js), правила те же.
    # True - в тексте только разрешённые теги (<i>, <strong>, <code>, <a href="" title="">),
    # все закрыты и правильно вложены. <a> внутри <a> быть не может.
    #
    # Отличие от JS: в Python "$" в регулярном выражении пропускает "\n" в конце строки,
    # а в JS - нет. Поэтому вместо "^...$" используется re.fullmatch - он, как и JS, требует
    # совпадения всей строки целиком.
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


def get_required_message_text(body, key):
    # Значение body[key]: непустая строка, в которой разметка проходит is_message_markup_correct. Ошибка - 400
    value, error = get_required_non_empty_string(body, key)
    if error is not None:
        return None, error

    if not is_message_markup_correct(value):
        return None, JsonResponse(
            {"error": key + " contains forbidden or unclosed tags (allowed: <i>, <strong>, <code>, <a href=\"\" title=\"\">)"},
            status=400,
        )

    return value, None
