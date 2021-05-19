CREATE TABLE IF NOT EXISTS commands (
    index BIGSERIAL PRIMARY KEY,
    server_id BIGINT,
    channel_id BIGINT,
    author_id BIGINT,
    timestamp TIMESTAMP,
    prefix TEXT,
    command TEXT,
    failed BOOLEAN
);

CREATE TABLE IF NOT EXISTS botstats (
    bot_id BIGINT PRIMARY KEY,
    runtime REAL DEFAULT 0 NOT NULL,
    online REAL DEFAULT 0 NOT NULL,
    idle REAL DEFAULT 0 NOT NULL,
    dnd REAL DEFAULT 0 NOT NULL,
    offline REAL DEFAULT 0 NOT NULL,
    startdate timestamp without time zone default (now() at time zone 'utc')
);