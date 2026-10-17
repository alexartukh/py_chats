from django.db import models
from django.db.models.functions import Now


class User(models.Model):
    # fields
    user_id = models.AutoField(primary_key=True, db_column="user_id")
    login = models.CharField(max_length=255, unique=True, db_column="login")
    email = models.CharField(max_length=255, unique=True, db_column="email")
    password = models.CharField(max_length=255, db_column="password")
    created_at = models.DateTimeField(db_default=Now(), db_column="created_at")
    last_login_at = models.DateTimeField(null=True, default=None, db_column="last_login_at")
    last_message_at = models.DateTimeField(null=True, default=None, db_column="last_message_at")
    # objects: none

    class Meta:
        db_table = "users"
        managed = False
        app_label = "orm"

class Topic(models.Model):
    # fields
    topic_id = models.AutoField(primary_key=True, db_column="topic_id")
    title = models.CharField(max_length=255, db_column="title")
    created_at = models.DateTimeField(db_default=Now(), db_column="created_at")
    last_update_at = models.DateTimeField(null=True, default=None, db_column="last_update_at")
    # objects
    created_by_user = models.ForeignKey(User, to_field="user_id", on_delete=models.PROTECT, db_column="created_by_user_id")

    class Meta:
        db_table = "topics"
        managed = False
        app_label = "orm"

class Message(models.Model):
    # fields
    message_id = models.AutoField(primary_key=True, db_column="message_id")
    t = models.TextField(db_column="t")
    # Файл к сообщению и его имя. Без файла оба NULL, с файлом оба заполнены
    attachment = models.BinaryField(null=True, default=None, db_column="attachment")
    attachment_name = models.CharField(max_length=255, null=True, default=None, db_column="attachment_name")
    # Кто прислал сообщение: IP и User-Agent берёт сервер из запроса, site - Home page из формы. Все могут быть NULL
    ip = models.GenericIPAddressField(null=True, default=None, db_column="ip")
    user_agent = models.TextField(null=True, default=None, db_column="user_agent")
    site = models.CharField(max_length=2048, null=True, default=None, db_column="site")
    created_at = models.DateTimeField(db_default=Now(), db_column="created_at")
    # objects
    parent_message = models.ForeignKey("self", to_field="message_id", null=True, default=None, on_delete=models.CASCADE, db_column="parent_message_id")
    topic = models.ForeignKey(Topic, to_field="topic_id", on_delete=models.CASCADE, db_column="topic_id")
    user = models.ForeignKey(User, to_field="user_id", on_delete=models.PROTECT, db_column="user_id")

    class Meta:
        db_table = "messages"
        managed = False
        app_label = "orm"

# Выданные CAPTCHA: запись на каждый GET /api/captcha, удаляется при первой проверке (см. CAPTCHA.py)
class Captcha(models.Model):
    # fields
    captcha_id = models.UUIDField(primary_key=True, db_column="captcha_id")
    answer = models.CharField(max_length=3, db_column="answer")
    expires_at = models.DateTimeField(db_column="expires_at")
    # objects: none

    class Meta:
        db_table = "captchas"
        managed = False
        app_label = "orm"
