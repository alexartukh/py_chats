from django.db import models
from django.db.models.functions import Now


class User(models.Model):
    # fields
    user_id = models.AutoField(primary_key=True, db_column="user_id")
    login = models.CharField(max_length=255, unique=True, db_column="login")
    password = models.CharField(max_length=255, db_column="password")
    created_at = models.DateTimeField(db_default=Now(), db_column="created_at")
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
    # objects
    created_by_user = models.ForeignKey(User, to_field="user_id", on_delete=models.PROTECT, db_column="created_by_user_id")
    
    class Meta:
        db_table = "topics"
        managed = False
        app_label = "orm"


class Message(models.Model):
    # fields
    message_id = models.AutoField(primary_key=True, db_column="message_id")
    text = models.TextField(db_column="text")
    created_at = models.DateTimeField(db_default=Now(), db_column="created_at")
    # objects
    topic = models.ForeignKey(Topic, to_field="topic_id", on_delete=models.CASCADE, db_column="topic_id")
    user = models.ForeignKey(User, to_field="user_id", on_delete=models.PROTECT, db_column="user_id")

    class Meta:
        db_table = "messages"
        managed = False
        app_label = "orm"
