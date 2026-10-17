# Функции для работы с паролями.
#
# Пароль в БД хранится не открытым текстом, а в виде хеша. Хеш нельзя превратить обратно в пароль,
# можно только проверить, подходит ли к нему введённый пароль.
#
# Используются функции Django make_password / check_password.
# Алгоритм указан явно: PBKDF2 + SHA256. Хеш выглядит так:
#   pbkdf2_sha256$<число итераций>$<соль>$<хеш>
# Соль - случайная строка, своя для каждого вызова, поэтому один и тот же пароль
# каждый раз даёт разный хеш. Это нормально: check_password берёт соль из самого хеша.
#
# Django читает настройки при вызове, поэтому функции можно вызывать только после settings.configure().

from django.contrib.auth.hashers import check_password, make_password

PASSWORD_HASHER = "pbkdf2_sha256"

# Возвращает хеш пароля для сохранения в users.password
def hash_password(password):
    return make_password(password, hasher=PASSWORD_HASHER)

# True, если password подходит к хешу из users.password, иначе False.
# Если в БД лежит не хеш, а старый открытый пароль (например, "123"), вернётся False.
def is_password_correct(password, password_hash):
    return check_password(password, password_hash)
