-- Схема БД проекта на диалекте MySQL - для просмотра в MySQL Workbench.
--
-- Настоящая база проекта - PostgreSQL, она создаётся скриптом init.sql. Этот файл повторяет те же
-- таблицы, колонки, ключи и индексы, но с типами MySQL, потому что Workbench понимает только MySQL.
-- Тестовых данных (INSERT) здесь нет - только структура.
--
-- Как открыть в Workbench:
--   File -> Import -> Reverse Engineer MySQL Create Script... -> выбрать этот файл -> Execute.
--   Workbench построит модель; диаграмма: Model -> Create Diagram from Catalog Objects.
--   Сохранить как schema.mwb (File -> Save Model As...).
--
-- Соответствие типов PostgreSQL (init.sql) -> MySQL (этот файл):
--   INT GENERATED ALWAYS AS IDENTITY -> INT AUTO_INCREMENT
--   TIMESTAMPTZ                      -> DATETIME(6)   в MySQL нет типа "время с часовым поясом";
--                                                     (6) - микросекунды, как в PostgreSQL;
--                                                     время хранится в UTC, так его пишет Django
--   DEFAULT now()                    -> DEFAULT CURRENT_TIMESTAMP(6)
--   BYTEA                            -> LONGBLOB      двоичные данные (файл к сообщению)
--   INET                             -> VARCHAR(45)   IP строкой; 45 - длина самой длинной записи IPv6
--   UUID                             -> CHAR(36)      UUID строкой вида xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
--   TEXT, VARCHAR(n)                 -> те же
--
-- Внешние ключи и индексы здесь названы явно (fk_..., idx_...). В init.sql имена не заданы,
-- там их придумывает PostgreSQL - на структуру это не влияет.

CREATE DATABASE IF NOT EXISTS tops
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE tops;

-- Пользователи форума
CREATE TABLE users (
    user_id         INT NOT NULL AUTO_INCREMENT,
    login           VARCHAR(255) NOT NULL,
    email           VARCHAR(255) NOT NULL,
    -- Хеш пароля (pbkdf2_sha256$...), не сам пароль
    password        VARCHAR(255) NOT NULL,
    created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    last_login_at   DATETIME(6) NULL DEFAULT NULL,
    last_message_at DATETIME(6) NULL DEFAULT NULL,
    PRIMARY KEY (user_id),
    UNIQUE KEY uq_users_login (login),
    UNIQUE KEY uq_users_email (email)
) ENGINE = InnoDB;

-- Темы. У каждой темы - автор
CREATE TABLE topics (
    topic_id           INT NOT NULL AUTO_INCREMENT,
    title              VARCHAR(255) NOT NULL,
    created_by_user_id INT NOT NULL,
    created_at         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    last_update_at     DATETIME(6) NULL DEFAULT NULL,
    PRIMARY KEY (topic_id),
    KEY idx_topics_created_by_user_id (created_by_user_id),
    CONSTRAINT fk_topics_created_by_user
        FOREIGN KEY (created_by_user_id) REFERENCES users (user_id)
) ENGINE = InnoDB;

-- Сообщения. Дерево: parent_message_id = NULL - корневое сообщение, иначе - ответ на parent_message_id.
-- Удаление темы удаляет её сообщения, удаление сообщения - все ответы на него (ON DELETE CASCADE)
CREATE TABLE messages (
    message_id        INT NOT NULL AUTO_INCREMENT,
    parent_message_id INT NULL DEFAULT NULL,
    topic_id          INT NOT NULL,
    user_id           INT NOT NULL,
    -- Текст сообщения; разрешены только теги <i>, <strong>, <code>, <a href="" title="">
    t                 TEXT NOT NULL,
    -- Файл к сообщению и его имя: оба NULL или оба заполнены. Картинка - не больше 320x240
    attachment        LONGBLOB NULL DEFAULT NULL,
    attachment_name   VARCHAR(255) NULL DEFAULT NULL,
    -- Кто прислал: IP и User-Agent берёт сервер, site - Home page из формы
    ip                VARCHAR(45) NULL DEFAULT NULL,
    user_agent        TEXT NULL DEFAULT NULL,
    site              VARCHAR(2048) NULL DEFAULT NULL,
    created_at        DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (message_id),
    KEY idx_messages_topic_id (topic_id),
    KEY idx_messages_user_id (user_id),
    KEY idx_messages_parent_message_id (parent_message_id),
    CONSTRAINT fk_messages_parent_message
        FOREIGN KEY (parent_message_id) REFERENCES messages (message_id) ON DELETE CASCADE,
    CONSTRAINT fk_messages_topic
        FOREIGN KEY (topic_id) REFERENCES topics (topic_id) ON DELETE CASCADE,
    CONSTRAINT fk_messages_user
        FOREIGN KEY (user_id) REFERENCES users (user_id)
) ENGINE = InnoDB;

-- Выданные CAPTCHA. Запись создаётся на каждый GET /api/captcha и удаляется при первой же проверке
-- (правильной или нет), поэтому каждую CAPTCHA можно проверить только один раз.
-- Просроченные записи (expires_at в прошлом) удаляются при выдаче новых.
-- captcha_id генерирует сервер (uuid4), у колонки нет значения по умолчанию.
-- Связей с другими таблицами нет.
CREATE TABLE captchas (
    captcha_id CHAR(36) NOT NULL,
    answer     VARCHAR(3) NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    PRIMARY KEY (captcha_id),
    KEY idx_captchas_expires_at (expires_at)
) ENGINE = InnoDB;
