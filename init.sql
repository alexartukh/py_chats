CREATE TABLE users (
    user_id         INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    login      VARCHAR(255) NOT NULL UNIQUE,
    email      VARCHAR(255) NOT NULL UNIQUE,
    password   VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ NULL DEFAULT NULL,
    last_message_at TIMESTAMPTZ NULL DEFAULT NULL
);
INSERT INTO users (login, email, password) VALUES ('test',  'test@example.com',  'pbkdf2_sha256$1500000$6fPt5amOHa7gBtGATltxYQ$tiQkYEZSS2dspFETSFESKZGL2OEXyAUsobtRo78e8/I=');
INSERT INTO users (login, email, password) VALUES ('alex',  'alex@example.com',  'pbkdf2_sha256$1500000$6fPt5amOHa7gBtGATltxYQ$tiQkYEZSS2dspFETSFESKZGL2OEXyAUsobtRo78e8/I=');
INSERT INTO users (login, email, password) VALUES ('denis', 'denis@example.com', 'pbkdf2_sha256$1500000$6fPt5amOHa7gBtGATltxYQ$tiQkYEZSS2dspFETSFESKZGL2OEXyAUsobtRo78e8/I=');

CREATE TABLE topics (
    topic_id         INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title      VARCHAR(255) NOT NULL,
    created_by_user_id    INT NOT NULL REFERENCES users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_update_at TIMESTAMPTZ NULL DEFAULT NULL
);
INSERT INTO topics (title, created_by_user_id) VALUES ('About planes', 1);
INSERT INTO topics (title, created_by_user_id) VALUES ('About love', 1);
INSERT INTO topics (title, created_by_user_id) VALUES ('About movies', 2);

CREATE TABLE messages (
    message_id         INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parent_message_id INT NULL REFERENCES messages(message_id) ON DELETE CASCADE, 
    topic_id   INT NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
    user_id    INT NOT NULL REFERENCES users(user_id),
    t       TEXT NOT NULL,
    attachment BYTEA NULL DEFAULT NULL,
    attachment_name VARCHAR(255) NULL DEFAULT NULL,
    ip         INET NULL DEFAULT NULL,
    user_agent TEXT NULL DEFAULT NULL,
    site       VARCHAR(2048) NULL DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Выданные CAPTCHA. Запись создаётся на каждый GET /api/captcha и удаляется при первой же проверке
-- (правильной или нет), поэтому каждую CAPTCHA можно проверить только один раз.
-- Просроченные записи (expires_at в прошлом) удаляются при выдаче новых.
-- captcha_id генерирует сервер (uuid4), у колонки нет значения по умолчанию.
CREATE TABLE captchas (
    captcha_id UUID PRIMARY KEY,
    answer     VARCHAR(3) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX ON topics (created_by_user_id);
CREATE INDEX ON messages (topic_id);
CREATE INDEX ON messages (user_id);
CREATE INDEX ON messages (parent_message_id);
CREATE INDEX ON captchas (expires_at);
