import base64
import binascii

from django.http import JsonResponse

from orm import Message, Topic, User
from request_check_helper import (
    check_method,
    get_authorized_user_id,
    get_query_positive_int,
    get_required_int,
    get_required_int_or_null,
    get_required_non_empty_string,
    get_required_message_text,
    get_required_non_empty_string_or_null,
    read_json_object,
)

# Разрешённые расширения файла к сообщению (по ТЗ: JPG, GIF, PNG, TXT)
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".gif", ".png")
TEXT_EXTENSIONS = (".txt",)

# Максимальный размер текстового файла (по ТЗ: 100 КБ)
MAX_TEXT_FILE_SIZE = 100 * 1024

# Первые байты файлов-картинок. По ним проверяется, что содержимое действительно картинка,
# а не что-то другое с расширением .png
IMAGE_SIGNATURES = (
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"GIF87a",             # GIF
    b"GIF89a",             # GIF
    b"\xff\xd8\xff",       # JPEG
)

# Максимальная длина имени файла - как у колонки messages.attachment_name VARCHAR(255)
MAX_ATTACHMENT_NAME_LENGTH = 255

# Проверяет файл к сообщению и возвращает пару (байты файла, ошибка), как функции из request_check_helper.
# attachment_base64 и attachment_name - оба строки или оба None.
# Без файла: (None, None).
def decode_attachment(attachment_base64, attachment_name):
    if attachment_base64 is None and attachment_name is None:
        return None, None

    if attachment_base64 is None or attachment_name is None:
        return None, JsonResponse({"error": "attachment and attachment_name must be both set or both null"}, status=400)

    if len(attachment_name) > MAX_ATTACHMENT_NAME_LENGTH:
        return None, JsonResponse({"error": "attachment_name is too long"}, status=400)

    lower_name = attachment_name.lower()
    is_image = lower_name.endswith(IMAGE_EXTENSIONS)
    is_text = lower_name.endswith(TEXT_EXTENSIONS)
    if not is_image and not is_text:
        return None, JsonResponse({"error": "attachment must be .jpg, .jpeg, .gif, .png or .txt"}, status=400)

    # validate=True: символы вне алфавита base64 - ошибка, а не молча пропускаются
    try:
        attachment_bytes = base64.b64decode(attachment_base64, validate=True)
    except binascii.Error:
        return None, JsonResponse({"error": "attachment must be a base64 string"}, status=400)

    if is_text:
        if len(attachment_bytes) > MAX_TEXT_FILE_SIZE:
            return None, JsonResponse({"error": "text attachment must be at most 100 KB"}, status=400)

    if is_image:
        has_image_signature = False
        for signature in IMAGE_SIGNATURES:
            if attachment_bytes.startswith(signature):
                has_image_signature = True
        if not has_image_signature:
            return None, JsonResponse({"error": "attachment is not a JPG, GIF or PNG image"}, status=400)

    return attachment_bytes, None


# Открытый endpoint: GET /api/messages?topic_id=<id>[&from=<n>&to=<m>]
# У каждого сообщения: attachment - файл строкой base64 или null, attachment_name - имя файла или null.
# Возвращает сообщения темы в порядке дерева:
# сообщение, сразу за ним все его ответы (рекурсивно), затем следующее сообщение того же уровня.
# Сообщения одного уровня идут от старых к новым.
#
# Пейджер: from и to - номера сообщений (с 1, включительно) среди ВСЕХ сообщений темы,
# упорядоченных по created_at, затем message_id. Без from и to - все сообщения.
# Ответ, у которого родитель не попал в диапазон, становится корнем страницы:
# его parent_message_id остаётся прежним, а depth - настоящая глубина в дереве темы.
def messages(request):
    error = check_method(request, "GET")
    if error is not None:
        return error

    topic_id, error = get_query_positive_int(request, "topic_id")
    if error is not None:
        return error

    # from и to передаются оба или ни одного
    has_from = "from" in request.GET
    has_to = "to" in request.GET
    if has_from != has_to:
        return JsonResponse({"error": "from and to must be both set or both absent"}, status=400)

    range_from = None
    range_to = None
    if has_from:
        range_from, error = get_query_positive_int(request, "from")
        if error is not None:
            return error

        range_to, error = get_query_positive_int(request, "to")
        if error is not None:
            return error

        if range_from < 1:
            return JsonResponse({"error": "from must be at least 1"}, status=400)

        if range_from > range_to:
            return JsonResponse({"error": "from must not be greater than to"}, status=400)

    if not Topic.objects.filter(topic_id=topic_id).exists():
        return JsonResponse({"error": "topic not found"}, status=404)

    # Родитель каждого сообщения темы - для подсчёта настоящей глубины.
    # Берутся только два числа на сообщение, без текста и файлов.
    parent_id_by_message_id = {}
    for message_id, parent_id in Message.objects.filter(topic_id=topic_id).values_list("message_id", "parent_message_id"):
        parent_id_by_message_id[message_id] = parent_id

    # неструктурированный ответ
    queryset = (
        Message.objects
        .filter(topic_id=topic_id)
        .order_by("created_at", "message_id")
    )

    # Срез Django превращается в SQL: OFFSET (from - 1) LIMIT (to - from + 1)
    if has_from:
        queryset = queryset[range_from - 1:range_to]

    rows = list(
        queryset
        .values(
            "message_id",
            "parent_message_id",
            "t",
            "attachment",
            "attachment_name",
            "user_id",
            "user__login",
            "created_at",
        )
    )

    # JSON не умеет передавать байты, поэтому файл отдаётся строкой base64 - в том же виде,
    # в каком приходит в create_new_message. Без файла остаётся null.
    # psycopg возвращает BYTEA как memoryview, bytes() превращает его в обычные байты.
    for row in rows:
        if row["attachment"] is not None:
            row["attachment"] = base64.b64encode(bytes(row["attachment"])).decode("ascii")

    # Сообщения, попавшие на страницу
    message_ids_on_page = set()
    for row in rows:
        message_ids_on_page.add(row["message_id"])

    # Раскладываем записи по дереву: корни страницы отдельно,
    # ответы - в списки по message_id родителя.
    # Корень страницы - сообщение без родителя или с родителем, который не попал на страницу.
    # Списки сохраняют порядок из запроса (от старых к новым).
    roots = []
    children_by_parent_id = {}
    for row in rows:
        parent_id = row["parent_message_id"]
        if parent_id is None or parent_id not in message_ids_on_page:
            roots.append(row)
        else:
            if parent_id not in children_by_parent_id:
                children_by_parent_id[parent_id] = []
            children_by_parent_id[parent_id].append(row)

    # Настоящая глубина сообщения в дереве темы: сколько шагов вверх до корневого сообщения.
    # Подъём останавливается, если сообщения нет в parent_id_by_message_id: так бывает,
    # если родитель лежит в другой теме (база это не запрещает) или сообщение добавили
    # между запросом родителей и запросом страницы.
    def depth_in_topic(message_id):
        depth = 0
        current_id = message_id
        while current_id in parent_id_by_message_id:
            parent_id = parent_id_by_message_id[current_id]
            if parent_id is None:
                break
            depth = depth + 1
            current_id = parent_id
        return depth

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
        place_with_depth(root, depth_in_topic(root["message_id"]))

    return JsonResponse(data, safe=False, status=200)

# Защищённый endpoint: нужен заголовок "Authorization: Bearer <token>", автор берётся из токена
# Ожидает POST с JSON-телом:
# {"login": "...", "email": "...", "topic_id": 1, "parent_message_id": null, "t": "...",
#  "attachment": "<base64>" | null, "attachment_name": "photo.png" | null}
# parent_message_id: null - корневое сообщение, число - ответ на это сообщение
# attachment и attachment_name: оба null - без файла, обе строки - файл (проверки в decode_attachment)
def create_new_message(request):
    error = check_method(request, "POST")
    if error is not None:
        return error

    user_id, error = get_authorized_user_id(request)
    if error is not None:
        return error

    body, error = read_json_object(request)
    if error is not None:
        return error

    user_login, error = get_required_non_empty_string(body, "login")
    if error is not None:
        return error

    user_email, error = get_required_non_empty_string(body, "email")
    if error is not None:
        return error

    topic_id, error = get_required_int(body, "topic_id")
    if error is not None:
        return error

    parent_message_id, error = get_required_int_or_null(body, "parent_message_id")
    if error is not None:
        return error

    # Текст может содержать только разрешённые теги - те же правила, что на клиенте (messageMarkup.js)
    t, error = get_required_message_text(body, "t")
    if error is not None:
        return error

    attachment_base64, error = get_required_non_empty_string_or_null(body, "attachment")
    if error is not None:
        return error

    attachment_name, error = get_required_non_empty_string_or_null(body, "attachment_name")
    if error is not None:
        return error

    attachment_bytes, error = decode_attachment(attachment_base64, attachment_name)
    if error is not None:
        return error

    # login и email из формы должны принадлежать тому же пользователю, что и токен
    if not User.objects.filter(user_id=user_id, login=user_login, email=user_email).exists():
        return JsonResponse({"error": "login and email do not match the token"}, status=403)

    if not Topic.objects.filter(topic_id=topic_id).exists():
        return JsonResponse({"error": "topic not found"}, status=404)

    # Родитель должен существовать и лежать в той же теме - база это не проверяет
    if parent_message_id is not None:
        parent = (
            Message.objects
            .filter(message_id=parent_message_id)
            .values("topic_id")
            .first()
        )
        if parent is None:
            return JsonResponse({"error": "parent message not found"}, status=404)
        if parent["topic_id"] != topic_id:
            return JsonResponse({"error": "parent message belongs to another topic"}, status=400)

    message = Message.objects.create(
        topic_id=topic_id,
        parent_message_id=parent_message_id,
        user_id=user_id,
        t=t,
        attachment=attachment_bytes,
        attachment_name=attachment_name,
    )

    # Сам файл в ответ не кладётся, только его имя
    data = {
        "message_id": message.message_id,
        "parent_message_id": message.parent_message_id,
        "topic_id": message.topic_id,
        "user_id": message.user_id,
        "t": message.t,
        "attachment_name": message.attachment_name,
        "created_at": message.created_at,
    }
    return JsonResponse(data, status=200)

# Защищённый endpoint: нужен заголовок "Authorization: Bearer <token>"
# Ожидает POST с JSON-телом: {"message_id": 1}
# Удалить можно только своё сообщение. Вместе с ним удаляются все ответы на него на любую глубину,
# в том числе ответы других пользователей (on_delete=CASCADE у Message.parent_message).
def delete_existing_message(request):
    error = check_method(request, "POST")
    if error is not None:
        return error

    user_id, error = get_authorized_user_id(request)
    if error is not None:
        return error

    body, error = read_json_object(request)
    if error is not None:
        return error

    message_id, error = get_required_int(body, "message_id")
    if error is not None:
        return error

    message = (
        Message.objects
        .filter(message_id=message_id)
        .values("user_id")
        .first()
    )
    if message is None:
        return JsonResponse({"error": "message not found"}, status=404)

    if message["user_id"] != user_id:
        return JsonResponse({"error": "only the author can delete the message"}, status=403)

    # delete() возвращает (сколько строк удалено всего, {модель: сколько удалено})
    deleted_count, deleted_by_model = Message.objects.filter(message_id=message_id).delete()

    data = {
        "message_id": message_id,
        "deleted_count": deleted_count,
    }
    return JsonResponse(data, status=200)

# Открытый endpoint: GET /api/get_all_root_messages?topic_id=<id>
# Возвращает только корневые сообщения темы (parent_message_id = NULL), без ответов и без пейджера.
# Порядок - как в /api/messages: от старых к новым (created_at, затем message_id).
# Поля - те же, что у сообщений в /api/messages; parent_message_id у всех null, depth у всех 0.
def get_all_root_messages(request):
    error = check_method(request, "GET")
    if error is not None:
        return error

    topic_id, error = get_query_positive_int(request, "topic_id")
    if error is not None:
        return error

    if not Topic.objects.filter(topic_id=topic_id).exists():
        return JsonResponse({"error": "topic not found"}, status=404)

    rows = list(
        Message.objects
        .filter(topic_id=topic_id, parent_message_id=None)
        .order_by("created_at", "message_id")
        .values(
            "message_id",
            "parent_message_id",
            "t",
            "attachment",
            "attachment_name",
            "user_id",
            "user__login",
            "created_at",
        )
    )

    # Файл отдаётся строкой base64, как в /api/messages
    for row in rows:
        if row["attachment"] is not None:
            row["attachment"] = base64.b64encode(bytes(row["attachment"])).decode("ascii")
        row["depth"] = 0

    return JsonResponse(rows, safe=False, status=200)