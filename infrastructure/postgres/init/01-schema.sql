-- Operational schema. Every table here is captured by the insurance_cdc
-- publication and flows into Kafka via Debezium.
CREATE SCHEMA IF NOT EXISTS insurance;

-- Evaluation schema. Deliberately NOT part of the publication so that fraud
-- labels can never reach the feature pipeline. See 02_replication.sql.
CREATE SCHEMA IF NOT EXISTS evaluation;


-- ---------------------------------------------------------------------------
-- Parties
-- ---------------------------------------------------------------------------

CREATE TABLE insurance.customers (
    customer_id     BIGSERIAL PRIMARY KEY,
    national_id     TEXT           NOT NULL UNIQUE,
    full_name       TEXT           NOT NULL,
    date_of_birth   DATE           NOT NULL,
    county          TEXT           NOT NULL,
    msisdn          TEXT           NOT NULL,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT now()
);

CREATE TABLE insurance.agents (
    agent_id        BIGSERIAL PRIMARY KEY,
    agent_code      TEXT           NOT NULL UNIQUE,
    full_name       TEXT           NOT NULL,
    branch          TEXT           NOT NULL,
    appointed_on    DATE           NOT NULL
);

-- Garages, hospitals and assessors. Fraud rings cluster around these.
CREATE TABLE insurance.service_providers (
    provider_id     BIGSERIAL PRIMARY KEY,
    provider_code   TEXT           NOT NULL UNIQUE,
    provider_name   TEXT           NOT NULL,
    provider_type   TEXT           NOT NULL,
    county          TEXT           NOT NULL
);


-- ---------------------------------------------------------------------------
-- Policies
-- ---------------------------------------------------------------------------

CREATE TABLE insurance.policies (
    policy_id       BIGSERIAL PRIMARY KEY,
    policy_number   TEXT           NOT NULL UNIQUE,
    customer_id     BIGINT         NOT NULL REFERENCES insurance.customers (customer_id),
    agent_id        BIGINT         NOT NULL REFERENCES insurance.agents (agent_id),
    product_class   TEXT           NOT NULL,
    sum_insured     NUMERIC(14, 2) NOT NULL,
    annual_premium  NUMERIC(14, 2) NOT NULL,
    inception_date  DATE           NOT NULL,
    expiry_date     DATE           NOT NULL,
    status          TEXT           NOT NULL,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ    NOT NULL DEFAULT now()
);

-- Mid-term changes to sum insured or premium. A policy's value is therefore
-- a function of time, not a single column read.
CREATE TABLE insurance.endorsements (
    endorsement_id    BIGSERIAL PRIMARY KEY,
    policy_id         BIGINT         NOT NULL REFERENCES insurance.policies (policy_id),
    effective_date    DATE           NOT NULL,
    endorsement_type  TEXT           NOT NULL,
    premium_delta     NUMERIC(14, 2) NOT NULL,
    sum_insured_delta NUMERIC(14, 2) NOT NULL,
    created_at        TIMESTAMPTZ    NOT NULL DEFAULT now()
);

CREATE TABLE insurance.premium_payments (
    payment_id      BIGSERIAL PRIMARY KEY,
    policy_id       BIGINT         NOT NULL REFERENCES insurance.policies (policy_id),
    due_date        DATE           NOT NULL,
    paid_date       DATE,
    amount_due      NUMERIC(14, 2) NOT NULL,
    amount_paid     NUMERIC(14, 2),
    payment_channel TEXT,
    status          TEXT           NOT NULL,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ    NOT NULL DEFAULT now()
);


-- ---------------------------------------------------------------------------
-- Claims
-- ---------------------------------------------------------------------------

CREATE TABLE insurance.claims (
    claim_id        BIGSERIAL PRIMARY KEY,
    claim_number    TEXT           NOT NULL UNIQUE,
    policy_id       BIGINT         NOT NULL REFERENCES insurance.policies (policy_id),
    provider_id     BIGINT         REFERENCES insurance.service_providers (provider_id),
    -- incident_date is when it happened; reported_date is when we learned of it.
    -- The gap drives IBNR reserving and late-arriving stream events.
    incident_date   DATE           NOT NULL,
    reported_date   DATE           NOT NULL,
    claimed_amount  NUMERIC(14, 2) NOT NULL,
    settled_amount  NUMERIC(14, 2),
    status          TEXT           NOT NULL,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ    NOT NULL DEFAULT now()
);

CREATE TABLE insurance.claim_assessments (
    assessment_id   BIGSERIAL PRIMARY KEY,
    claim_id        BIGINT         NOT NULL REFERENCES insurance.claims (claim_id),
    assessor_id     BIGINT         NOT NULL REFERENCES insurance.service_providers (provider_id),
    assessed_on     DATE           NOT NULL,
    assessed_amount NUMERIC(14, 2) NOT NULL,
    recommendation  TEXT           NOT NULL,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT now()
);


-- ---------------------------------------------------------------------------
-- Ground truth. Never published, never joined into features.
-- ---------------------------------------------------------------------------

CREATE TABLE evaluation.fraud_labels (
    label_id        BIGSERIAL PRIMARY KEY,
    claim_number    TEXT           NOT NULL,
    is_fraudulent   BOOLEAN        NOT NULL,
    fraud_pattern   TEXT,
    ring_id         TEXT,
    generated_at    TIMESTAMPTZ    NOT NULL DEFAULT now()
);

CREATE INDEX idx_fraud_labels_claim ON evaluation.fraud_labels (claim_number);


-- ---------------------------------------------------------------------------
-- Access paths for the query patterns the platform actually uses
-- ---------------------------------------------------------------------------

CREATE INDEX idx_policies_customer ON insurance.policies (customer_id);
CREATE INDEX idx_policies_agent ON insurance.policies (agent_id);
CREATE INDEX idx_policies_inception ON insurance.policies (inception_date);
CREATE INDEX idx_endorsements_policy ON insurance.endorsements (policy_id);
CREATE INDEX idx_payments_policy ON insurance.premium_payments (policy_id);
CREATE INDEX idx_payments_due_date ON insurance.premium_payments (due_date);
CREATE INDEX idx_claims_policy ON insurance.claims (policy_id);
CREATE INDEX idx_claims_provider ON insurance.claims (provider_id);
CREATE INDEX idx_claims_reported_date ON insurance.claims (reported_date);
CREATE INDEX idx_claims_incident_date ON insurance.claims (incident_date);
CREATE INDEX idx_assessments_claim ON insurance.claim_assessments (claim_id);