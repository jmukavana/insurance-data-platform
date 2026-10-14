-- Persist the alert stream to Postgres.
--
-- Load after 01_sources.sql and 02_fraud_rules.sql:
--   docker exec -it insurance-flink-jobmanager ./bin/sql-client.sh \
--     -i /opt/sql/01_sources.sql -i /opt/sql/02_fraud_rules.sql \
--     -f /opt/sql/03_sink.sql
--
-- The declared PRIMARY KEY puts the JDBC connector in upsert mode, so a claim
-- re-flagged by the same rule updates its row instead of failing on the
-- constraint. Without it the sink appends and the first duplicate kills the job.

CREATE TABLE fraud_alerts_sink (
    claim_number STRING,
    rule_name    STRING,
    score        DECIMAL(6, 3),
    evidence     STRING,
    PRIMARY KEY (claim_number, rule_name) NOT ENFORCED
) WITH (
    'connector' = 'jdbc',
    'url' = 'jdbc:postgresql://postgres:5432/insurance',
    'table-name' = 'detection.fraud_alerts',
    'username' = 'insurance',
    'password' = 'insurance',
    -- Batch writes rather than one round trip per alert.
    'sink.buffer-flush.max-rows' = '500',
    'sink.buffer-flush.interval' = '2s',
    'sink.max-retries' = '3'
);

-- Detached job: it keeps running after the SQL client exits.
INSERT INTO fraud_alerts_sink
SELECT claim_number, rule_name, score, evidence
FROM fraud_alerts;