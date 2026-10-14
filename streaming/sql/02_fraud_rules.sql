-- Fraud detection rules.
--
-- These are changelog aggregations, not windowed ones: a Debezium stream is a
-- retract stream, and Flink's windowing TVFs require append-only input. Regular
-- GROUP BY works here and continuously corrects itself as rows change.
--
-- Date arithmetic runs on the raw epoch-day integers from the _cdc tables,
-- which is simpler than casting to DATE and back.

-- Bound the state these joins would otherwise hold forever. This is a
-- correctness trade-off: a claim whose policy has aged out of state will not
-- join.
SET 'table.exec.state.ttl' = '0';


-- ---------------------------------------------------------------------------
-- Shared base: claims enriched with their policy
-- ---------------------------------------------------------------------------

CREATE VIEW claim_context AS
SELECT
    c.claim_number,
    c.claim_id,
    c.provider_id,
    p.agent_id,
    p.product_class,
    c.incident_date - p.inception_date       AS days_from_inception,
    c.reported_date - c.incident_date        AS reporting_lag_days,
    CAST(c.claimed_amount AS DECIMAL(14, 2)) AS claimed_amount,
    CAST(p.sum_insured AS DECIMAL(14, 2))    AS sum_insured,
    c.status
FROM claims_cdc c
JOIN policies_cdc p ON c.policy_id = p.policy_id;


-- ---------------------------------------------------------------------------
-- Rule 1: PROVIDER_RING
--
-- Staged accidents cluster: several claims, one provider, all shortly after
-- policy inception. No single attribute is remarkable; the combination is.
-- ---------------------------------------------------------------------------

CREATE VIEW early_claims AS
SELECT *
FROM claim_context
WHERE days_from_inception BETWEEN 0 AND 45
  AND provider_id IS NOT NULL;

CREATE VIEW suspicious_providers AS
SELECT
    provider_id,
    COUNT(*)            AS early_claim_count,
    AVG(claimed_amount) AS mean_amount
FROM early_claims
GROUP BY provider_id
HAVING COUNT(*) >= 3;

CREATE VIEW provider_ring_alerts AS
SELECT
    e.claim_number,
    'PROVIDER_RING' AS rule_name,
    CAST(CASE WHEN s.early_claim_count >= 10 THEN 1.0
              ELSE s.early_claim_count / 10.0 END AS DECIMAL(6, 3)) AS score,
    CONCAT(
        'provider ', CAST(e.provider_id AS STRING),
        ' has ', CAST(s.early_claim_count AS STRING),
        ' early claims; this claim at day ',
        CAST(e.days_from_inception AS STRING)
    ) AS evidence
FROM early_claims e
JOIN suspicious_providers s ON e.provider_id = s.provider_id;


-- ---------------------------------------------------------------------------
-- Rule 2: SEVERITY_OUTLIER
--
-- An inflated claim is a genuine incident with the loss exaggerated. Only the
-- amount is anomalous, so detection needs a peer distribution to compare
-- against - here, the mean severity for the same product class.
-- ---------------------------------------------------------------------------

CREATE VIEW class_severity AS
SELECT
    product_class,
    AVG(claimed_amount) AS mean_claim,
    COUNT(*)            AS class_claim_count
FROM claim_context
GROUP BY product_class;

CREATE VIEW severity_outlier_alerts AS
SELECT
    c.claim_number,
    'SEVERITY_OUTLIER' AS rule_name,
    CAST(CASE WHEN c.claimed_amount > s.mean_claim * 10 THEN 1.0
              ELSE c.claimed_amount / (s.mean_claim * 10) END AS DECIMAL(6, 3)) AS score,
    CONCAT(
        'claimed ', CAST(c.claimed_amount AS STRING),
        ' vs class mean ', CAST(CAST(s.mean_claim AS DECIMAL(14, 2)) AS STRING)
    ) AS evidence
FROM claim_context c
JOIN class_severity s ON c.product_class = s.product_class
WHERE s.class_claim_count > 100
  AND c.claimed_amount > s.mean_claim * 4;


-- ---------------------------------------------------------------------------
-- Rule 3: AGENT_CONCENTRATION
--
-- Collusion is invisible per claim. It appears only when claims are aggregated
-- by the agent who wrote the policy.
-- ---------------------------------------------------------------------------

CREATE VIEW agent_early_claim_rate AS
SELECT
    agent_id,
    COUNT(*) AS early_claims
FROM claim_context
WHERE days_from_inception BETWEEN 0 AND 60
GROUP BY agent_id
HAVING COUNT(*) >= 8;

CREATE VIEW agent_concentration_alerts AS
SELECT
    c.claim_number,
    'AGENT_CONCENTRATION' AS rule_name,
    CAST(CASE WHEN a.early_claims >= 25 THEN 1.0
              ELSE a.early_claims / 25.0 END AS DECIMAL(6, 3)) AS score,
    CONCAT(
        'agent ', CAST(c.agent_id AS STRING),
        ' has ', CAST(a.early_claims AS STRING), ' early claims'
    ) AS evidence
FROM claim_context c
JOIN agent_early_claim_rate a ON c.agent_id = a.agent_id
WHERE c.days_from_inception BETWEEN 0 AND 60;


-- ---------------------------------------------------------------------------
-- Combined alert stream
-- ---------------------------------------------------------------------------

CREATE VIEW fraud_alerts AS
SELECT claim_number, rule_name, score, evidence FROM provider_ring_alerts
UNION ALL
SELECT claim_number, rule_name, score, evidence FROM severity_outlier_alerts
UNION ALL
SELECT claim_number, rule_name, score, evidence FROM agent_concentration_alerts;