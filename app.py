import os
import sys
from urllib.parse import urlparse

import django
from channels.routing import ProtocolTypeRouter, URLRouter
from django.apps import AppConfig
from django.core.asgi import get_asgi_application
from django.conf import settings
from django.core.management import execute_from_command_line
from django.urls import path
from dotenv import load_dotenv

class OrmConfig(AppConfig):
    # Модели из orm.py регистрируются под этой меткой (app_label = "orm")
    name = "__main__"
    label = "orm"

load_dotenv()
db_url = urlparse(os.environ["DATABASE_URL"])

# DJANGO_DEBUG в .env: строго "true" или "false", любое другое значение - ошибка запуска
debug_value = os.environ["DJANGO_DEBUG"]
if debug_value == "true":
    debug = True
elif debug_value == "false":
    debug = False
else:
    raise ValueError('DJANGO_DEBUG must be "true" or "false", got: ' + debug_value)

# DJANGO_ALLOWED_HOSTS в .env: адреса через запятую, например "localhost,127.0.0.1".
# Django проверяет этот список при вызове request.get_host(), его вызывает CommonMiddleware (см. MIDDLEWARE).
# Запрос к адресу не из списка получает 400.
allowed_hosts = []
for host in os.environ["DJANGO_ALLOWED_HOSTS"].split(","):
    if host.strip() != "":
        allowed_hosts.append(host.strip())

settings.configure(
    DEBUG=debug,
    ALLOWED_HOSTS=allowed_hosts,
    ROOT_URLCONF=__name__,
    SECRET_KEY=os.environ["DJANGO_SECRET_KEY"],
    # daphne должен стоять первым: он ПОДМЕНЯЕТ команду runserver.
    #   С ним "python app.py runserver" запускает ASGI-сервер Daphne, который обслуживает
    #   и обычные HTTP-запросы, и WebSocket. Без него runserver умеет только HTTP.
    # channels - Django Channels, WebSocket-обработчики (см. online.py)
    INSTALLED_APPS=["daphne", "__main__.OrmConfig", "corsheaders", "channels"],
    # Точка входа ASGI для Daphne: объект application ниже в этом файле
    ASGI_APPLICATION="__main__.application",
    # Слой каналов Channels - через него соединения получают групповые рассылки (group_send).
    # Хранится в Redis, поэтому работает и при нескольких процессах сервера.
    # protocol=2 - протокол RESP2, см. REDIS_PROTOCOL в online.py
    CHANNEL_LAYERS={
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [
                    {"address": os.environ["REDIS_URL"], "protocol": 2},
                ],
            },
        },
    },
    # Порядок важен: middleware выполняются сверху вниз для запроса и снизу вверх для ответа.
    # CorsMiddleware - пакет django-cors-headers. Сама добавляет заголовки Access-Control-*
    #   ко всем ответам и сама отвечает на предварительные запросы OPTIONS от браузера.
    #   По документации пакета должна стоять выше CommonMiddleware.
    # CommonMiddleware - проверяет Host запроса по ALLOWED_HOSTS (иначе 400).
    #   Её остальные действия выключены явно ниже: APPEND_SLASH и PREPEND_WWW.
    MIDDLEWARE=[
        "corsheaders.middleware.CorsMiddleware",
        "django.middleware.common.CommonMiddleware",
    ],
    # Не дописывать "/" в конец адреса и не перенаправлять на него (у нас адреса без "/")
    APPEND_SLASH=False,
    # Не перенаправлять на адрес с "www."
    PREPEND_WWW=False,
    CORS_ALLOW_ALL_ORIGINS=True,
    CORS_ALLOW_METHODS=["GET", "POST", "OPTIONS"],
    CORS_ALLOW_HEADERS=["authorization", "content-type"],
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

# View-функции импортируются только после django.setup()
from views.users import get_users, create_new_user, login, logout
from views.topics import get_topics, create_new_topic, get_topic
from views.messages import messages, create_new_message, delete_existing_message, get_all_root_messages
from CAPTCHA import get_captcha
from online import OnlineConsumer, reset_online_users

urlpatterns = [
    # users    
    path("api/users", get_users),
    path("api/create_new_user", create_new_user),
    path("api/login", login),
    path("api/logout", logout),
    # topics
    path("api/topics", get_topics),
    path("api/create_new_topic", create_new_topic),
    path("api/topic", get_topic),
    # messages
    path("api/messages", messages),
    path("api/create_new_message", create_new_message),
    path("api/delete_existing_message", delete_existing_message),
    path("api/get_all_root_messages", get_all_root_messages),
    # captcha
    path("api/captcha", get_captcha),
]

# WebSocket-адреса. Отдельно от urlpatterns: те обслуживают только HTTP
websocket_urlpatterns = [
    path("ws/online", OnlineConsumer.as_asgi()),
]

# ASGI-приложение: HTTP-запросы идут в обычный Django (urlpatterns выше), WebSocket - в websocket_urlpatterns
application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": URLRouter(websocket_urlpatterns),
})

# Список онлайн сбрасывается только при запуске сервера, а не при других командах (check, shell и т.д.):
# иначе, например, "python app.py shell" стёр бы список у уже работающего сервера.
# Подробности - у reset_online_users в online.py
if len(sys.argv) > 1 and sys.argv[1] == "runserver":
    reset_online_users()


execute_from_command_line(sys.argv)
