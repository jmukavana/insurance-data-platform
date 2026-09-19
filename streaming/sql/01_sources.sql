-- Source tables over the Debezium changelog topics.
--
-- 'debezium-json' tells Flink to interpret the envelope and emit a retract
-- stream (INSERT / UPDATE_BEFORE / UPDATE_AFTER / DELETE) rather than treating
-- every message as a new fact. Aggregations over these tables therefore stay
-- correct as rows change, with no deduplication logic.
--
-- Two Debezium encodings drive the column types below:
--   DATE    -> int32, days since 1970-01-01 (io.debezium.time.Date).
--              Declared INT here and converted with DATE_FROM_UNIX_DATE.
--   NUMERIC -> string, because decimal.handling.mode = 'string'.
--              Declared STRING here and cast to DECIMAL in the views.
--
-- The _cdc tables mirror the wire format exactly; the views below present the
-- typed model everything downstream should use.
--
-- Note: default_catalog is generic_in_memory and therefore session-scoped.
-- These definitions vanish when the SQL client exits, which is why this file
-- is loaded as an init script (-i). Step 5 replaces it with a persistent
-- Iceberg REST catalog.

SET 'execution.runtime-mode' = 'streaming';
SET 'sql-client.execution.result-mode' = 'tableau';


CREATE TABLE claims_cdc (
    claim_id        BIGINT,
    claim_number    STRING,
    policy_id       BIGINT,
    provider_id     BIGINT,
    incident_date   INT,
    reported_date   INT,
    claimed_amount  STRING,
    settled_amount  STRING,
    status          STRING,
    PRIMARY KEY (claim_id) NOT ENFORCED
) WITH (
    'connector' = 'kafka',
    'topic' = 'insurance.insurance.claims',
    'properties.bootstrap.servers' = 'kafka:9092',
    'properties.group.id' = 'flink-claims-v2',
    'scan.startup.mode' = 'earliest-offset',
    'format' = 'debezium-json',
    'debezium-json.schema-include' = 'false',
    -- A single malformed record should not crash-loop the job.
    'debezium-json.ignore-parse-errors' = 'true'
);


CREATE TABLE policies_cdc (
    policy_id       BIGINT,
    policy_number   STRING,
    customer_id     BIGINT,
    agent_id        BIGINT,
    product_class   STRING,
    sum_insured     STRING,
    annual_premium  STRING,
    inception_date  INT,
    expiry_date     INT,
    status          STRING,
    PRIMARY KEY (policy_id) NOT ENFORCED
) WITH (
    'connector' = 'kafka',
    'topic' = 'insurance.insurance.policies',
    'properties.bootstrap.servers' = 'kafka:9092',
    'properties.group.id' = 'flink-policies-v2',
    'scan.startup.mode' = 'earliest-offset',
    'format' = 'debezium-json',
    'debezium-json.schema-include' = 'false',
    'debezium-json.ignore-parse-errors' = 'true'
);


CREATE TABLE premium_payments_cdc (
    payment_id      BIGINT,
    policy_id       BIGINT,
    due_date        INT,
    paid_date       INT,
    amount_due      STRING,
    amount_paid     STRING,
    payment_channel STRING,
    status          STRING,
    PRIMARY KEY (payment_id) NOT ENFORCED
) WITH (
    'connector' = 'kafka',
    'topic' = 'insurance.insurance.premium_payments',
    'properties.bootstrap.servers' = 'kafka:9092',
    'properties.group.id' = 'flink-payments-v2',
    'scan.startup.mode' = 'earliest-offset',
    'format' = 'debezium-json',
    'debezium-json.schema-include' = 'false',
    'debezium-json.ignore-parse-errors' = 'true'
);


-- Typed views. Query these, not the _cdc tables, so the wire-format quirks
-- are handled in exactly one place.

CREATE VIEW claims AS
SELECT
    claim_id,
    claim_number,
    policy_id,
    provider_id,
    TIMESTAMPADD(DAY, incident_date, DATE '1970-01-01') AS incident_date,
    TIMESTAMPADD(DAY, reported_date, DATE '1970-01-01') AS reported_date,
    reported_date - incident_date      AS reporting_lag_days,
    CAST(claimed_amount AS DECIMAL(14, 2)) AS claimed_amount,
    CAST(settled_amount AS DECIMAL(14, 2)) AS settled_amount,
    status
FROM claims_cdc;


CREATE VIEW policies AS
SELECT
    policy_id,
    policy_number,
    customer_id,
    agent_id,
    product_class,
    CAST(sum_insured AS DECIMAL(14, 2))    AS sum_insured,
    CAST(annual_premium AS DECIMAL(14, 2)) AS annual_premium,
    TIMESTAMPADD(DAY, inception_date, DATE '1970-01-01')    AS inception_date,
    TIMESTAMPADD(DAY, expiry_date, DATE '1970-01-01')       AS expiry_date,
    status
FROM policies_cdc;


CREATE VIEW premium_payments AS
SELECT
    payment_id,
    policy_id,
    TIMESTAMPADD(DAY, due_date, DATE '1970-01-01')  AS due_date,
    TIMESTAMPADD(DAY, paid_date, DATE '1970-01-01') AS paid_date,
    CAST(amount_due AS DECIMAL(14, 2)) AS amount_due,
    CAST(amount_paid AS DECIMAL(14, 2)) AS amount_paid,
    payment_channel,
    status
FROM premium_payments_cdc;