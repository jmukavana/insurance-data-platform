-- Replication configuration, kept separate from the schema so the CDC contract
-- is reviewable on its own.

-- Default replica identity emits only the primary key plus new values on UPDATE.
-- Fraud rules need the prior values ("sum insured jumped from X to Y"), so emit
-- the full old row. Cost: larger WAL volume. Acceptable at this scale.
ALTER TABLE insurance.customers         REPLICA IDENTITY FULL;
ALTER TABLE insurance.agents            REPLICA IDENTITY FULL;
ALTER TABLE insurance.service_providers REPLICA IDENTITY FULL;
ALTER TABLE insurance.policies          REPLICA IDENTITY FULL;
ALTER TABLE insurance.endorsements      REPLICA IDENTITY FULL;
ALTER TABLE insurance.premium_payments  REPLICA IDENTITY FULL;
ALTER TABLE insurance.claims            REPLICA IDENTITY FULL;
ALTER TABLE insurance.claim_assessments REPLICA IDENTITY FULL;

-- Scoped to the insurance schema only. evaluation.fraud_labels is therefore
-- structurally unable to reach Kafka, the lakehouse, or any feature pipeline.
CREATE PUBLICATION insurance_cdc FOR TABLES IN SCHEMA insurance;