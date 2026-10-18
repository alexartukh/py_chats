# Список пользователей онлайн через WebSocket (Django Channels).
#
# Онлайн - это пользователь, у которого сейчас открыто хотя бы одно WebSocket-соединение с ws/online.
# Клиент ничего не опрашивает: он один раз подключается, а сервер сам присылает список
# сразу после подключения и при каждом изменении (кто-то подключился или отключился).
# Список один и тот же для всех: клиент сам убирает из него себя.
#
# Сообщение сервера: {"type": "online_users", "users": [{"user_id": 2, "login": "alex"}, ...]}
# users отсортирован по login.
#
# Где хранится список - в Redis (REDIS_URL), в двух хешах:
#   online:connections - user_id -> сколько у пользователя открыто соединений (вкладок)
#   online:logins      - user_id -> login (чтобы не ходить в БД при каждой рассылке)
# Пользователь онлайн, пока счётчик больше 0. Несколько вкладок одного пользователя - одно присутствие.
#
# Токен передаётся параметром адреса: ws://<сервер>/ws/online?token=<JWT>.
# Заголовок Authorization браузер для WebSocket задать не даёт. Минус: адрес с токеном попадает в логи сервера.
# Проверки Origin нет: доступ определяет только токен, cookies не используются,
# поэтому чужой сайт без токена подключиться не сможет.
#
# Импортирует orm и auth, поэтому импортировать можно только после django.setup().

import os
from urllib.parse import parse_qs

import jwt
import redis
import redis.asyncio
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from auth import token_service
from orm import User

REDIS_URL = os.environ["REDIS_URL"]

# Протокол общения с Redis: 2 - RESP2. Библиотека redis-py 8.x по умолчанию начинает соединение
# командой HELLO 3 (протокол RESP3), а её нет в Redis старше 6 (на виртуалке Ubuntu 20.04 - Redis 5.0.7).
# RESP2 понимают все версии Redis и Valkey (Render Key Value). То же значение - в CHANNEL_LAYERS в app.py
REDIS_PROTOCOL = 2

# Ключи в Redis
CONNECTIONS_KEY = "online:connections"
LOGINS_KEY = "online:logins"

# Имя группы рассылки Channels: в неё входят все открытые соединения ws/online
ONLINE_GROUP = "online"

# Один асинхронный клиент Redis на процесс. Соединения он открывает сам при первом запросе
redis_client = redis.asyncio.Redis.from_url(REDIS_URL, decode_responses=True, protocol=REDIS_PROTOCOL)

# Lua-скрипт, который Redis выполняет атомарно (целиком, без вмешательства других команд):
# уменьшить счётчик пользователя на 1 и, если стало 0 или меньше, удалить пользователя из обоих хешей.
# Без этого между "уменьшить" и "удалить" могло бы вклиниться новое подключение той же вкладки,
# и пользователь пропал бы из списка, хотя он онлайн.
# KEYS[1] - online:connections, KEYS[2] - online:logins, ARGV[1] - user_id
DECREMENT_SCRIPT = """
local count = redis.call('HINCRBY', KEYS[1], ARGV[1], -1)
if count <= 0 then
    redis.call('HDEL', KEYS[1], ARGV[1])
    redis.call('HDEL', KEYS[2], ARGV[1])
end
return count
"""


# Удаляет весь список онлайн. Вызывается один раз при старте сервера (см. app.py):
# если сервер прошлый раз упал аварийно, отключения не сработали, и в Redis остались бы
# "вечно онлайн" пользователи. После перезапуска все клиенты всё равно переподключаются.
# Синхронный клиент: при старте ещё нет цикла событий asyncio.
# Внимание: годится только пока сервер работает одним процессом - иначе каждый новый процесс
# стирал бы соединения остальных.
def reset_online_users():
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True, protocol=REDIS_PROTOCOL)
    client.delete(CONNECTIONS_KEY, LOGINS_KEY)
    client.close()


# user_id и login по токену или None, если токена нет, он недействителен или пользователя уже нет в БД.
# Синхронная функция (ходит в БД через ORM) - вызывается через database_sync_to_async
def get_user_by_token(token):
    if token is None or token == "":
        return None

    try:
        user_id = token_service.get_user_id(token)
    except jwt.InvalidTokenError:
        return None

    return (
        User.objects
        .filter(user_id=user_id)
        .values("user_id", "login")
        .first()
    )


# Текущий список онлайн из Redis: [{"user_id": 2, "login": "alex"}, ...], отсортированный по login
async def get_online_users():
    logins_by_user_id = await redis_client.hgetall(LOGINS_KEY)

    users = []
    for user_id in logins_by_user_id:
        users.append({
            "user_id": int(user_id),
            "login": logins_by_user_id[user_id],
        })

    def get_login(user):
        return user["login"]

    users.sort(key=get_login)
    return users


# Обработчик WebSocket-соединений ws/online. Channels создаёт отдельный объект на каждое соединение.
# AsyncJsonWebsocketConsumer сам переводит JSON в dict и обратно (send_json).
class OnlineConsumer(AsyncJsonWebsocketConsumer):

    # Подключение. Без действующего токена соединение отклоняется (браузер получит ошибку подключения)
    async def connect(self):
        # self.user_id = None означает "соединение не принято" - тогда disconnect ничего не делает
        self.user_id = None

        # query_string приходит байтами: b"token=..."
        query = parse_qs(self.scope["query_string"].decode("utf-8"))
        token = None
        if "token" in query:
            token = query["token"][0]

        user = await database_sync_to_async(get_user_by_token)(token)
        if user is None:
            await self.close()
            return

        await self.accept()
        self.user_id = user["user_id"]

        await redis_client.hincrby(CONNECTIONS_KEY, str(self.user_id), 1)
        await redis_client.hset(LOGINS_KEY, str(self.user_id), user["login"])

        # channel_name - уникальное имя этого соединения в Channels
        await self.channel_layer.group_add(ONLINE_GROUP, self.channel_name)
        await self.broadcast_online_users()

    # Отключение: закрыта вкладка, оборвалась связь или сервер закрыл соединение
    async def disconnect(self, code):
        if self.user_id is None:
            return

        await self.channel_layer.group_discard(ONLINE_GROUP, self.channel_name)
        await redis_client.eval(DECREMENT_SCRIPT, 2, CONNECTIONS_KEY, LOGINS_KEY, str(self.user_id))
        await self.broadcast_online_users()

    # Сообщения от клиента не ожидаются - игнорируются
    async def receive_json(self, content):
        return

    # Отправляет текущий список всем соединениям группы.
    # Channels вызовет у каждого соединения метод, имя которого получается из "type":
    # точка заменяется на подчёркивание, "online.users" -> online_users
    async def broadcast_online_users(self):
        users = await get_online_users()
        await self.channel_layer.group_send(ONLINE_GROUP, {
            "type": "online.users",
            "users": users,
        })

    # Получено сообщение группы - переслать его клиенту
    async def online_users(self, event):
        await self.send_json({
            "type": "online_users",
            "users": event["users"],
        })
