import os
import sys
from urllib.parse import urlparse

import django
from django.apps import AppConfig
from django.conf import settings
from django.core.management import execute_from_command_line
from django.http import JsonResponse
from django.urls import path
from dotenv import load_dotenv

class OrmConfig(AppConfig):
    # Модели из orm.py регистрируются под этой меткой (app_label = "orm")
    name = "__main__"
    label = "orm"

load_dotenv()
db_url = urlparse(os.environ["DATABASE_URL"])

settings.configure(
    DEBUG=True,
    ROOT_URLCONF=__name__,
    SECRET_KEY="dev",
    INSTALLED_APPS=["__main__.OrmConfig"],
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

from orm import Topic, User

def get_topics(request):
    data = list(Topic.objects.values("topic_id", "title", "created_by_user__login", "created_at"))
    return JsonResponse(data, safe=False)

def get_users(request):
    data = list(User.objects.values("user_id", "login", "created_at"))
    return JsonResponse(data, safe=False)

def create_new_topic(request):
    pass

def create_new_user(request):
    pass

urlpatterns = [
    path("topics", get_topics),
    path("users", get_users),

    path("create_new_topic", create_new_topic),
    path("create_new_user", create_new_user),
]

execute_from_command_line(sys.argv)
