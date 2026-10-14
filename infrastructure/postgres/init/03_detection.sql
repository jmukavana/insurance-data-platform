-- Alert store. Detection output is a case-management queue, not a block:
-- nothing here stops a claim being paid, it puts it in front of an investigator.
--
-- This schema sits outside the insurance_cdc publication, so alerts do not
-- loop back into the feature pipeline that produced them.

CREATE SCHEMA IF NOT EXISTS detection;

CREATE TABLE IF NOT EXISTS detection.fraud_alerts (
    claim_number    TEXT           NOT NULL,
    rule_name       TEXT           NOT NULL,
    score           NUMERIC(6, 3)  NOT NULL,
    evidence        TEXT,
    detected_at     TIMESTAMPTZ    NOT NULL DEFAULT now(),
    PRIMARY KEY (claim_number, rule_name)
);

CREATE INDEX IF NOT EXISTS idx_fraud_alerts_rule
    ON detection.fraud_alerts (rule_name);