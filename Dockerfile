# Образ сервера MyForum (Django + Channels + Daphne).
#
# Сборка:  docker build -t myforum-server .
# Запуск:  docker run --rm -p 8000:8000 --env-file .env myforum-server
#
# Файл .env в образ НЕ копируется (он в .dockerignore): секреты не должны попадать в образ.
# Переменные окружения передаются при запуске (--env-file .env или -e ИМЯ=значение).
# PostgreSQL и Redis в этот образ не входят - адреса к ним задаются в DATABASE_URL и REDIS_URL.
# Подробности - в README.md, раздел "Запуск в Docker".

# Python 3.13: для него есть готовые сборки всех зависимостей под Linux.
# slim - уменьшенный образ Debian без компиляторов и лишних пакетов
FROM python:3.13-slim

# PYTHONUNBUFFERED=1 - вывод print и логов сразу попадает в "docker logs", без буферизации
# PYTHONDONTWRITEBYTECODE=1 - не создавать файлы .pyc внутри контейнера
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Сначала только requirements.txt и установка пакетов: Docker кэширует этот слой,
# и при изменении кода пакеты не переустанавливаются - пересборка быстрее.
# AUTOBAHN_USE_NVX=0 - если для autobahn (зависимость daphne) не найдётся готовой сборки,
# собрать его без C-ускорения: компилятора в slim-образе нет
COPY requirements.txt .
RUN AUTOBAHN_USE_NVX=0 pip install --no-cache-dir -r requirements.txt

# Код приложения. Что не копируется - см. .dockerignore
COPY . .

# Сервер работает не от root: если его взломают, у процесса будет меньше прав внутри контейнера
RUN useradd --create-home appuser
USER appuser

# Порт по умолчанию. Хостинг (например, Render) может задать свой через переменную PORT
EXPOSE 8000

# Запуск: "runserver" с daphne в INSTALLED_APPS запускает ASGI-сервер Daphne (HTTP + WebSocket).
# 0.0.0.0 - слушать все сетевые интерфейсы контейнера, иначе снаружи сервер недоступен.
# ${PORT:-8000} - порт из переменной PORT, а если её нет - 8000.
# --noreload - без автоперезапуска при изменении файлов: в контейнере код не меняется.
# sh -c нужен, чтобы подставилась переменная PORT; exec - чтобы python стал главным процессом
# и получал сигнал остановки от "docker stop" напрямую.
CMD ["sh", "-c", "exec python app.py runserver 0.0.0.0:${PORT:-8000} --noreload"]
