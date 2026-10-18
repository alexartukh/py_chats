from django.http import JsonResponse

from CAPTCHA import check_captcha
from messages_helper import (
    arrange_messages_as_tree,
    check_parent_message,
    decode_attachment,
    encode_attachments_to_base64,
    get_parent_id_by_message_id,
    get_query_range,
)
from orm import Message, Topic, User
from request_check_helper import (
    check_method,
    get_authorized_user_id,
    get_client_ip,
    get_optional_site,
    get_query_positive_int,
    get_user_agent,
    get_required_email,
    get_required_int,
    get_required_int_or_null,
    get_required_login,
    get_required_non_empty_string,
    get_required_message_text,
    get_required_non_empty_string_or_null,
    read_json_object,
)


# Endpoint-ы сообщений: дерево сообщений темы, корневые сообщения, создание, удаление.
# Проверка и уменьшение файла, пейджер и раскладка деревом - в messages_helper.py.
# Каждый endpoint - метод. В app.py создаётся один объект messages_api = MessagesApi(),
# и маршруты указывают на его методы: path("api/messages", messages_api.messages).
class MessagesApi:

    # Открытый endpoint: GET /api/messages?topic_id=<id>[&from=<n>&to=<m>]
    # У каждого сообщения: attachment - файл строкой base64 или null, attachment_name - имя файла или null.
    # Возвращает сообщения темы в порядке дерева:
    # сообщение, сразу за ним все его ответы (рекурсивно), затем следующее сообщение того же уровня.
    # Сообщения одного уровня идут от новых к старым (LIFO, по ТЗ).
    #
    # Пейджер: from и to - номера сообщений (с 1, включительно) среди ВСЕХ сообщений темы,
    # упорядоченных от новых к старым: по created_at по убыванию, затем message_id по убыванию.
    # from=1 - самое новое сообщение темы. Без from и to - все сообщения.
    # Ответ, у которого родитель не попал в диапазон, становится корнем страницы:
    # его parent_message_id остаётся прежним, а depth - настоящая глубина в дереве темы.
    def messages(self, request):
        error = check_method(request, "GET")
        if error is not None:
            return error

        topic_id, error = get_query_positive_int(request, "topic_id")
        if error is not None:
            return error

        range_from, range_to, error = get_query_range(request)
        if error is not None:
            return error

        if not Topic.objects.filter(topic_id=topic_id).exists():
            return JsonResponse({"error": "topic not found"}, status=404)

        parent_id_by_message_id = get_parent_id_by_message_id(topic_id)

        # неструктурированный ответ
        queryset = (
            Message.objects
            .filter(topic_id=topic_id)
            # "-" перед именем поля - сортировка по убыванию (ORDER BY ... DESC): новые первыми
            .order_by("-created_at", "-message_id")
        )

        # Срез Django превращается в SQL: OFFSET (from - 1) LIMIT (to - from + 1)
        if range_from is not None:
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

        encode_attachments_to_base64(rows)
        data = arrange_messages_as_tree(rows, parent_id_by_message_id)

        return JsonResponse(data, safe=False, status=200)

    # Защищённый endpoint: нужен заголовок "Authorization: Bearer <token>", автор берётся из токена
    # Ожидает POST с JSON-телом:
    # {"login": "...", "email": "...", "topic_id": 1, "parent_message_id": null, "t": "...",
    #  "attachment": "<base64>" | null, "attachment_name": "photo.png" | null,
    #  "site": "https://..." | null, "captcha_id": "<uuid из GET /api/captcha>", "captcha": "123"}
    # parent_message_id: null - корневое сообщение, число - ответ на это сообщение
    # captcha_id и captcha обязательны. CAPTCHA проверяется после проверки формата всех полей и сразу
    # становится использованной, даже если дальше запрос отклонится (403, 404 и т.д.) - тогда клиенту
    # нужно запросить новую CAPTCHA.
    # attachment и attachment_name: оба null - без файла, обе строки - файл (проверки в decode_attachment).
    # Картинка больше 320x240 сохраняется уже уменьшенной (shrink_image).
    # site - Home page из формы, необязательное: поля может не быть, null или "" - сайт не указан
    # IP и User-Agent клиент не присылает: сервер берёт их из самого запроса (get_client_ip, get_user_agent)
    def create_new_message(self, request):
        error = check_method(request, "POST")
        if error is not None:
            return error

        user_id, error = get_authorized_user_id(request)
        if error is not None:
            return error

        body, error = read_json_object(request)
        if error is not None:
            return error

        # login - только латинские буквы и цифры, email - формат адреса (правила в request_check_helper)
        user_login, error = get_required_login(body, "login")
        if error is not None:
            return error

        user_email, error = get_required_email(body, "email")
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

        site, error = get_optional_site(body, "site")
        if error is not None:
            return error

        captcha_id, error = get_required_non_empty_string(body, "captcha_id")
        if error is not None:
            return error

        captcha_answer, error = get_required_non_empty_string(body, "captcha")
        if error is not None:
            return error

        error = check_captcha(captcha_id, captcha_answer)
        if error is not None:
            return error

        ip = get_client_ip(request)
        user_agent = get_user_agent(request)

        # login и email из формы должны принадлежать тому же пользователю, что и токен
        if not User.objects.filter(user_id=user_id, login=user_login, email=user_email).exists():
            return JsonResponse({"error": "login and email do not match the token"}, status=403)

        if not Topic.objects.filter(topic_id=topic_id).exists():
            return JsonResponse({"error": "topic not found"}, status=404)

        error = check_parent_message(parent_message_id, topic_id)
        if error is not None:
            return error

        message = Message.objects.create(
            topic_id=topic_id,
            parent_message_id=parent_message_id,
            user_id=user_id,
            t=t,
            attachment=attachment_bytes,
            attachment_name=attachment_name,
            ip=ip,
            user_agent=user_agent,
            site=site,
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
    def delete_existing_message(self, request):
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
    # Порядок - от старых к новым (created_at, затем message_id); клиент сортирует таблицу сам.
    # Поля - те же, что у сообщений в /api/messages, плюс user__email; parent_message_id у всех null, depth у всех 0.
    def get_all_root_messages(self, request):
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
                "user__email",
                "created_at",
            )
        )

        encode_attachments_to_base64(rows)
        for row in rows:
            row["depth"] = 0

        return JsonResponse(rows, safe=False, status=200)
