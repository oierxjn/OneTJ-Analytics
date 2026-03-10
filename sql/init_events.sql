CREATE TABLE IF NOT EXISTS events_raw (
    id BIGSERIAL NOT NULL,
    request_id UUID NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    client_ip INET NOT NULL,
    hash_id TEXT NOT NULL,
    userid TEXT NULL,
    username TEXT NULL,
    client_version TEXT NULL,
    device_brand TEXT NULL,
    device_model TEXT NULL,
    dept_name TEXT NULL,
    school_name TEXT NULL,
    gender TEXT NULL,
    platform TEXT NULL,
    payload_json JSONB NOT NULL,
    PRIMARY KEY (id, received_at)
);

CREATE INDEX IF NOT EXISTS idx_events_raw_received_at_brin ON events_raw USING BRIN (received_at);
CREATE INDEX IF NOT EXISTS idx_events_raw_received_platform ON events_raw (received_at DESC, platform);
CREATE INDEX IF NOT EXISTS idx_events_raw_request_id ON events_raw (request_id);
CREATE INDEX IF NOT EXISTS idx_events_raw_hash_id ON events_raw (hash_id);
