# Помощники для endpoint-ов сообщений (views/messages.py, класс MessagesApi):
#   - файл к сообщению: проверка, раскодирование из base64, уменьшение картинки;
#   - выдача файлов клиенту строкой base64;
#   - пейджер: разбор параметров from и to;
#   - дерево сообщений: раскладка по родителям, настоящая глубина, порядок вывода;
#   - проверка родительского сообщения при создании ответа.
#
# Функции, которые могут отклонить запрос, возвращают ошибку последним элементом, как в request_check_helper:
# всё в порядке - ошибка None, иначе JsonResponse с ошибкой, и view должна сразу вернуть его.
#
# Импортирует orm, поэтому импортировать можно только после django.setup().

import base64
import binascii
import io

from django.http import JsonResponse
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

from orm import Message
from request_check_helper import get_query_positive_int

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

# Максимальный размер картинки (по ТЗ: 320x240). Больше - уменьшается пропорционально
MAX_IMAGE_WIDTH = 320
MAX_IMAGE_HEIGHT = 240

# Качество JPEG при пересохранении уменьшенной картинки: 1-95, у Pillow по умолчанию 75
JPEG_QUALITY = 85


# Проверяет файл к сообщению и возвращает пару (байты файла, ошибка).
# attachment_base64 и attachment_name - оба строки или оба None.
# Без файла: (None, None). Картинка больше MAX_IMAGE_WIDTH x MAX_IMAGE_HEIGHT возвращается уже уменьшенной.
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

        attachment_bytes, error = shrink_image(attachment_bytes)
        if error is not None:
            return None, error

    return attachment_bytes, None


# Уменьшает картинку, если она больше MAX_IMAGE_WIDTH x MAX_IMAGE_HEIGHT, сохраняя пропорции.
# Возвращает пару (байты картинки, ошибка). Картинка, которая уже помещается, возвращается без изменений,
# байт в байт: маленькие картинки не увеличиваются и не пересохраняются.
# Формат остаётся прежним (PNG -> PNG, JPEG -> JPEG, GIF -> GIF) - берётся из самих байтов, а не из имени файла.
#
# Неявное, что здесь сделано явно:
#   - thumbnail() Pillow уменьшает так, чтобы картинка поместилась в рамку целиком, с сохранением пропорций,
#     и никогда не увеличивает. Например, 1000x500 -> 320x160, 300x600 -> 120x240.
#   - Фото с телефона часто хранится повёрнутым, а поворот записан в EXIF. При пересохранении EXIF теряется,
#     и картинка легла бы на бок. ImageOps.exif_transpose заранее поворачивает сами пиксели.
#   - Анимированный GIF уменьшается кадр за кадром. Задержка между кадрами берётся одна - из первого кадра.
#   - Image.open защищён от "картинки-бомбы": при слишком большом числе пикселей Pillow бросает
#     DecompressionBombError, это тоже ошибка 400.
def shrink_image(image_bytes):
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return None, JsonResponse({"error": "attachment image cannot be read"}, status=400)

    if image.width <= MAX_IMAGE_WIDTH and image.height <= MAX_IMAGE_HEIGHT:
        return image_bytes, None

    # "PNG", "JPEG" или "GIF" - определяется Pillow по содержимому
    image_format = image.format
    max_size = (MAX_IMAGE_WIDTH, MAX_IMAGE_HEIGHT)
    buffer = io.BytesIO()

    is_animated_gif = image_format == "GIF" and getattr(image, "is_animated", False)
    if is_animated_gif:
        frames = []
        for frame in ImageSequence.Iterator(image):
            frame_copy = frame.copy()
            frame_copy.thumbnail(max_size)
            frames.append(frame_copy)

        other_frames = []
        for index in range(1, len(frames)):
            other_frames.append(frames[index])

        frames[0].save(
            buffer,
            format="GIF",
            save_all=True,
            append_images=other_frames,
            loop=image.info.get("loop", 0),
            duration=image.info.get("duration", 100),
        )
    else:
        image = ImageOps.exif_transpose(image)
        image.thumbnail(max_size)
        if image_format == "JPEG":
            image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
        else:
            image.save(buffer, format=image_format)

    return buffer.getvalue(), None


# Заменяет в каждой строке row["attachment"] байты файла на строку base64 (меняет rows на месте).
# JSON не умеет передавать байты, поэтому файл отдаётся строкой base64 - в том же виде,
# в каком приходит в create_new_message. Без файла остаётся None (в JSON - null).
# psycopg возвращает BYTEA как memoryview, bytes() превращает его в обычные байты.
def encode_attachments_to_base64(rows):
    for row in rows:
        if row["attachment"] is not None:
            row["attachment"] = base64.b64encode(bytes(row["attachment"])).decode("ascii")


# Параметры пейджера from и to из адреса (?from=1&to=25). Возвращает тройку (from, to, ошибка).
# Оба передаются вместе или ни одного. Без них - (None, None, None): значит, нужны все сообщения.
# Ошибка 400: передан только один, не положительное целое, from меньше 1 или from больше to.
def get_query_range(request):
    has_from = "from" in request.GET
    has_to = "to" in request.GET
    if has_from != has_to:
        return None, None, JsonResponse({"error": "from and to must be both set or both absent"}, status=400)

    if not has_from:
        return None, None, None

    range_from, error = get_query_positive_int(request, "from")
    if error is not None:
        return None, None, error

    range_to, error = get_query_positive_int(request, "to")
    if error is not None:
        return None, None, error

    if range_from < 1:
        return None, None, JsonResponse({"error": "from must be at least 1"}, status=400)

    if range_from > range_to:
        return None, None, JsonResponse({"error": "from must not be greater than to"}, status=400)

    return range_from, range_to, None


# Родитель каждого сообщения темы: {message_id: parent_message_id или None} - для подсчёта настоящей глубины.
# Берутся только два числа на сообщение, без текста и файлов.
def get_parent_id_by_message_id(topic_id):
    parent_id_by_message_id = {}
    for message_id, parent_id in Message.objects.filter(topic_id=topic_id).values_list("message_id", "parent_message_id"):
        parent_id_by_message_id[message_id] = parent_id
    return parent_id_by_message_id


# Настоящая глубина сообщения в дереве темы: сколько шагов вверх до корневого сообщения.
# parent_id_by_message_id - результат get_parent_id_by_message_id.
# Подъём останавливается, если сообщения нет в parent_id_by_message_id: так бывает,
# если родитель лежит в другой теме (база это не запрещает) или сообщение добавили
# между запросом родителей и запросом страницы.
def get_depth_in_topic(message_id, parent_id_by_message_id):
    depth = 0
    current_id = message_id
    while current_id in parent_id_by_message_id:
        parent_id = parent_id_by_message_id[current_id]
        if parent_id is None:
            break
        depth = depth + 1
        current_id = parent_id
    return depth


# Раскладывает сообщения страницы деревом и возвращает новый список в порядке вывода:
# сообщение, сразу за ним все его ответы (рекурсивно), затем следующее сообщение того же уровня.
# Каждой строке проставляется row["depth"] - настоящая глубина в дереве темы.
#
# rows - строки сообщений в нужном порядке соседей (порядок внутри каждого уровня сохраняется),
#        у каждой есть message_id и parent_message_id.
# parent_id_by_message_id - родители всех сообщений темы (get_parent_id_by_message_id).
#
# Корень страницы - сообщение без родителя или с родителем, который не попал в rows (на другой странице).
def arrange_messages_as_tree(rows, parent_id_by_message_id):
    # Сообщения, попавшие на страницу
    message_ids_on_page = set()
    for row in rows:
        message_ids_on_page.add(row["message_id"])

    # Раскладываем записи по дереву: корни страницы отдельно,
    # ответы - в списки по message_id родителя.
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
        place_with_depth(root, get_depth_in_topic(root["message_id"], parent_id_by_message_id))

    return data


# Проверяет родителя нового ответа. Возвращает None, если всё в порядке, иначе JsonResponse с ошибкой.
# parent_message_id = None (корневое сообщение) - проверять нечего.
# Родитель должен существовать (иначе 404) и лежать в той же теме (иначе 400) - база это не проверяет.
def check_parent_message(parent_message_id, topic_id):
    if parent_message_id is None:
        return None

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

    return None
