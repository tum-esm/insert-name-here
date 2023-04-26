CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "timescaledb";


CREATE TABLE users (
    user_identifier UUID PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    creation_timestamp TIMESTAMPTZ NOT NULL,
    password_hash TEXT NOT NULL
);


CREATE TABLE networks (
    network_identifier UUID PRIMARY KEY,
    network_name TEXT NOT NULL,
    creation_timestamp TIMESTAMPTZ NOT NULL
);


CREATE TABLE sensors (
    sensor_identifier UUID PRIMARY KEY,
    sensor_name TEXT NOT NULL,
    network_identifier UUID NOT NULL REFERENCES networks (network_identifier) ON DELETE CASCADE,
    creation_timestamp TIMESTAMPTZ NOT NULL,

    UNIQUE (network_identifier, sensor_name)
);


CREATE TABLE permissions (
    user_identifier UUID NOT NULL REFERENCES users (user_identifier) ON DELETE CASCADE,
    network_identifier UUID NOT NULL REFERENCES networks (network_identifier) ON DELETE CASCADE,
    creation_timestamp TIMESTAMPTZ NOT NULL,
    -- Add permission levels here (e.g. admin, user, read-only)

    PRIMARY KEY (user_identifier, network_identifier)
);


CREATE TABLE sessions (
    access_token_hash TEXT PRIMARY KEY,
    user_identifier UUID NOT NULL REFERENCES users (user_identifier) ON DELETE CASCADE,
    creation_timestamp TIMESTAMPTZ NOT NULL
);


CREATE TABLE configurations (
    sensor_identifier UUID NOT NULL REFERENCES sensors (sensor_identifier) ON DELETE CASCADE,
    revision INT NOT NULL,
    creation_timestamp TIMESTAMPTZ NOT NULL,
    publication_timestamp TIMESTAMPTZ,
    acknowledgement_timestamp TIMESTAMPTZ,
    receipt_timestamp TIMESTAMPTZ,
    success BOOLEAN,

    -- Add more pre-defined values here (needed if we want to visualize them in the dashboard)
    -- Something like: lat/long, notes, version commit hash -> most should still be nullable
    -- lat/long and notes should be in the sensors table though, the configurations table should
    -- only contain things that are actually sent to the sensor
    -- or user-configurable "metadata" that is not sent to the sensor -> better: extra tags table?

    configuration JSONB NOT NULL
);

-- Defining the primary key like this (setting the sort order) makes the query to get the latest revision faster
CREATE UNIQUE INDEX ON configurations (sensor_identifier ASC, revision DESC);


CREATE TABLE measurements (
    sensor_identifier UUID NOT NULL REFERENCES sensors (sensor_identifier) ON DELETE CASCADE,
    revision INT NOT NULL,
    creation_timestamp TIMESTAMPTZ NOT NULL,
    receipt_timestamp TIMESTAMPTZ NOT NULL,
    position_in_transmission INT NOT NULL,
    measurement JSONB NOT NULL
);

CREATE UNIQUE INDEX ON measurements (sensor_identifier ASC, creation_timestamp DESC);

SELECT create_hypertable('measurements', 'creation_timestamp');


CREATE MATERIALIZED VIEW measurements_aggregation_4_hours
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
    SELECT
        sensor_identifier,
        time_bucket('4 hours', creation_timestamp) AS bucket_timestamp,
        COUNT(*) AS measurements_count
    FROM measurements
    GROUP BY sensor_identifier, bucket_timestamp
WITH DATA;


SELECT add_continuous_aggregate_policy(
    continuous_aggregate => 'measurements_aggregation_4_hours',
    start_offset => '10 days',
    end_offset => '4 hours',
    schedule_interval => '2 hours'
);


CREATE TABLE logs (
    sensor_identifier UUID NOT NULL REFERENCES sensors (sensor_identifier) ON DELETE CASCADE,
    revision INT NOT NULL,
    creation_timestamp TIMESTAMPTZ NOT NULL,
    receipt_timestamp TIMESTAMPTZ NOT NULL,
    position_in_transmission INT NOT NULL,
    severity TEXT NOT NULL,
    subject TEXT NOT NULL,
    details TEXT
);

CREATE UNIQUE INDEX ON logs (sensor_identifier ASC, creation_timestamp DESC);

SELECT create_hypertable('logs', 'creation_timestamp');

SELECT add_retention_policy(
    relation => 'logs',
    drop_after => INTERVAL '8 weeks'
);
