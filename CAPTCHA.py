# CAPTCHA: картинка PNG со случайным 3-значным числом.
#
# Рисует библиотека Pillow (пакет Pillow, импортируется как PIL).
# Чтобы число было труднее распознать программой, поверх рисуются случайные линии и точки,
# а каждая цифра немного сдвинута по высоте и окрашена в свой цвет.
#
# Как работает проверка:
#   1. GET /api/captcha рисует новое число, сохраняет в таблицу captchas запись
#      (captcha_id, ответ, срок жизни) и отдаёт клиенту captcha_id и картинку.
#   2. Пользователь может перезагружать картинку сколько угодно: каждая - отдельная запись,
#      клиент просто хранит captcha_id последней.
#   3. При отправке формы клиент присылает captcha_id и введённое число, сервер вызывает check_captcha.
#      Запись удаляется при первой же проверке - правильной или нет. Поэтому каждую CAPTCHA
#      можно проверить только один раз, и подобрать число перебором нельзя.

import base64
import hmac
import io
import secrets
import uuid
from datetime import timedelta

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont

from orm import Captcha
from request_check_helper import check_method

# Сколько живёт CAPTCHA после выдачи
CAPTCHA_LIFETIME = timedelta(minutes=5)

# Размер картинки в пикселях
CAPTCHA_WIDTH = 120
CAPTCHA_HEIGHT = 40

# Размер шрифта цифр в пикселях
CAPTCHA_FONT_SIZE = 28

# Сколько линий и точек-помех рисовать поверх
CAPTCHA_NOISE_LINES = 5
CAPTCHA_NOISE_DOTS = 120


# Случайное целое от low до high включительно.
# secrets, а не random: random предсказуем, если знать его предыдущие значения
def random_int(low, high):
    return low + secrets.randbelow(high - low + 1)


# Случайный тёмный цвет (R, G, B) - для цифр, чтобы они были видны на светлом фоне
def random_dark_color():
    return (random_int(0, 120), random_int(0, 120), random_int(0, 120))


# Случайный средний цвет (R, G, B) - для помех
def random_noise_color():
    return (random_int(100, 200), random_int(100, 200), random_int(100, 200))


# Возвращает пару (число строкой, байты PNG-картинки с этим числом)
def generate_captcha_image():
    # 3-значное число: от 100 до 999, без ведущего нуля
    text = str(random_int(100, 999))

    image = Image.new("RGB", (CAPTCHA_WIDTH, CAPTCHA_HEIGHT), (245, 245, 245))
    draw = ImageDraw.Draw(image)

    # Встроенный шрифт Pillow. С параметром size он масштабируемый (Pillow 10.1+, нужна FreeType)
    font = ImageFont.load_default(size=CAPTCHA_FONT_SIZE)

    # Цифры по очереди слева направо, каждая со своим сдвигом по высоте и своим цветом
    x = 18
    for digit in text:
        y = random_int(0, CAPTCHA_HEIGHT - CAPTCHA_FONT_SIZE - 4)
        draw.text((x, y), digit, font=font, fill=random_dark_color())
        x = x + 30

    for line_number in range(CAPTCHA_NOISE_LINES):
        start = (random_int(0, CAPTCHA_WIDTH), random_int(0, CAPTCHA_HEIGHT))
        end = (random_int(0, CAPTCHA_WIDTH), random_int(0, CAPTCHA_HEIGHT))
        draw.line([start, end], fill=random_noise_color(), width=1)

    for dot_number in range(CAPTCHA_NOISE_DOTS):
        point = (random_int(0, CAPTCHA_WIDTH - 1), random_int(0, CAPTCHA_HEIGHT - 1))
        draw.point(point, fill=random_noise_color())

    # Картинка сохраняется не в файл, а в память (BytesIO), и оттуда берутся байты
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return text, buffer.getvalue()


# Открытый endpoint: GET /api/captcha
# Отвечает JSON: {"captcha_id": "<uuid>", "image": "<PNG в base64>"}.
# Клиент показывает картинку как <img src="data:image/png;base64,..."> и запоминает captcha_id.
# Заодно удаляет просроченные CAPTCHA, чтобы таблица не росла.
# Cache-Control: no-store - браузер не должен кэшировать ответ, иначе при обновлении покажет старое число
def get_captcha(request):
    error = check_method(request, "GET")
    if error is not None:
        return error

    now = timezone.now()
    Captcha.objects.filter(expires_at__lte=now).delete()

    text, png_bytes = generate_captcha_image()

    captcha_id = uuid.uuid4()
    Captcha.objects.create(
        captcha_id=captcha_id,
        answer=text,
        expires_at=now + CAPTCHA_LIFETIME,
    )

    data = {
        "captcha_id": str(captcha_id),
        "image": base64.b64encode(png_bytes).decode("ascii"),
    }
    response = JsonResponse(data, status=200)
    response["Cache-Control"] = "no-store"
    return response


# Проверяет ответ пользователя на CAPTCHA. Возвращает None, если ответ правильный, иначе JsonResponse с ошибкой 400.
# captcha_id - строка из формы, answer - введённое число строкой.
# Запись удаляется в любом случае, даже при неправильном ответе: повторно эту CAPTCHA проверить нельзя.
# select_for_update блокирует строку до конца транзакции: два одновременных запроса с одним captcha_id
# не смогут оба прочитать запись до её удаления.
def check_captcha(captcha_id, answer):
    try:
        parsed_captcha_id = uuid.UUID(captcha_id)
    except ValueError:
        return JsonResponse({"error": "captcha_id must be a uuid"}, status=400)

    with transaction.atomic():
        captcha = (
            Captcha.objects
            .select_for_update()
            .filter(captcha_id=parsed_captcha_id)
            .values("answer", "expires_at")
            .first()
        )
        if captcha is None:
            return JsonResponse({"error": "captcha not found or already used, request a new one"}, status=400)

        Captcha.objects.filter(captcha_id=parsed_captcha_id).delete()

    if captcha["expires_at"] <= timezone.now():
        return JsonResponse({"error": "captcha expired, request a new one"}, status=400)

    # compare_digest сравнивает за одинаковое время независимо от того, где первое отличие.
    # Сравниваются байты UTF-8: со строками compare_digest падает, если в них есть не-ASCII символы
    if not hmac.compare_digest(captcha["answer"].encode("utf-8"), answer.encode("utf-8")):
        return JsonResponse({"error": "captcha answer is wrong, request a new one"}, status=400)

    return None
