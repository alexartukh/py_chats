import os
import sys
from urllib.parse import urlparse

import django
from django.apps import AppConfig
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
    INSTALLED_APPS=["__main__.OrmConfig", "corsheaders"],
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
from views.topics import get_topics, create_new_topic
from views.messages import messages, create_new_message, delete_existing_message

urlpatterns = [
    # users    
    path("api/users", get_users),
    path("api/create_new_user", create_new_user),
    path("api/login", login),
    path("api/logout", logout),
    # topics
    path("api/topics", get_topics),
    path("api/create_new_topic", create_new_topic),
    # messages
    path("api/messages", messages),
    path("api/create_new_message", create_new_message),
    path("api/delete_existing_message", delete_existing_message),
]

execute_from_command_line(sys.argv)
