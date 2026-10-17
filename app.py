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
