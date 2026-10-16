CREATE TABLE users (
    user_id         INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    login      VARCHAR(255) NOT NULL UNIQUE,
    password   VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ NULL DEFAULT NULL,
    last_message_at TIMESTAMPTZ NULL DEFAULT NULL
);
INSERT INTO users (login, password) VALUES ('test', '123');
INSERT INTO users (login, password) VALUES ('alex', '123');
INSERT INTO users (login, password) VALUES ('denis', '123');

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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON topics (created_by_user_id);
CREATE INDEX ON messages (topic_id);
CREATE INDEX ON messages (user_id);
CREATE INDEX ON messages (parent_message_id);
