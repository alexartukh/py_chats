import os
from datetime import datetime, timedelta, timezone

import jwt

# Импорт orm требует, чтобы django.setup() уже был вызван,
# поэтому auth.py можно импортировать только после него
from orm import User


class TokenService:
    # Создаёт и проверяет JWT-токены вида {"sub": "<user_id>", "exp": <unix time>}

    def __init__(self, secret_key: str, algorithm: str, lifetime_seconds: int):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.lifetime_seconds = lifetime_seconds

    def create_token(self, user_id: int) -> str:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.lifetime_seconds)
        payload = {
            # PyJWT требует, чтобы sub был строкой, поэтому user_id переводится в str
            "sub": str(user_id),
            "exp": int(expires_at.timestamp()),
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    # Выбрасывает jwt.ExpiredSignatureError, если срок истёк,
    # и jwt.InvalidTokenError, если токен подделан или повреждён
    def get_user_id(self, token: str) -> int:
        payload = jwt.decode(
            token,
            self.secret_key,
            algorithms=[self.algorithm],
            options={"require": ["sub", "exp"]},
        )
        return int(payload["sub"])

    # Берёт токен из заголовка "Authorization: Bearer <token>"
    # Возвращает user_id или None, если токена нет, он недействителен или пользователя уже нет в БД
    def get_user_id_from_request(self, request) -> int | None:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None

        token = header.removeprefix("Bearer ")
        try:
            user_id = self.get_user_id(token)
        except jwt.InvalidTokenError:
            return None

        if not User.objects.filter(user_id=user_id).exists():
            return None

        return user_id


# Общий объект для всех view-функций: from auth import token_service
# JWT_SECRET читается из окружения, поэтому load_dotenv() должен быть вызван до импорта auth.py
token_service = TokenService(
    secret_key=os.environ["JWT_SECRET"],
    algorithm="HS256",
    lifetime_seconds=3600,
)
