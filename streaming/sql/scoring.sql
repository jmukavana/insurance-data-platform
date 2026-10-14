-- Scoring the detection rules against ground truth.
--
--   docker exec -i insurance-postgres psql -U insurance -d insurance \
--     < evaluation/sql/scoring.sql
--
-- This is the only place the two schemas meet. detection.fraud_alerts is
-- produced without any access to evaluation.fraud_labels, which is what makes
-- these numbers mean something.


\echo '=== Precision by rule ==='
-- Of the claims each rule flagged, how many were actually fraudulent?
-- Low precision means investigators waste time on false alarms.
SELECT
    a.rule_name,
    count(*)                                             AS flagged,
    count(*) FILTER (WHERE l.is_fraudulent)              AS true_positives,
    round(100.0 * count(*) FILTER (WHERE l.is_fraudulent)
          / nullif(count(*), 0), 1)                      AS precision_pct
FROM detection.fraud_alerts a
JOIN evaluation.fraud_labels l ON l.claim_number = a.claim_number
GROUP BY a.rule_name
ORDER BY precision_pct DESC NULLS LAST;


\echo ''
\echo '=== Recall by fraud pattern ==='
-- Of the fraud that exists, how much did the system catch at all?
-- The diagonal matters: each rule was designed for one pattern.
SELECT
    l.fraud_pattern,
    count(*)                                                     AS actual_fraud,
    count(*) FILTER (WHERE a.claim_number IS NOT NULL)           AS caught,
    round(100.0 * count(*) FILTER (WHERE a.claim_number IS NOT NULL)
          / nullif(count(*), 0), 1)                              AS recall_pct
FROM evaluation.fraud_labels l
LEFT JOIN (
    SELECT DISTINCT claim_number FROM detection.fraud_alerts
) a ON a.claim_number = l.claim_number
WHERE l.is_fraudulent
GROUP BY l.fraud_pattern
ORDER BY recall_pct DESC NULLS LAST;


\echo ''
\echo '=== Which rule catches which pattern ==='
-- Confirms each rule fires on the pattern it was written for. Off-diagonal
-- hits are not necessarily wrong, but they should be explainable.
SELECT
    l.fraud_pattern,
    a.rule_name,
    count(*) AS hits
FROM evaluation.fraud_labels l
JOIN detection.fraud_alerts a ON a.claim_number = l.claim_number
WHERE l.is_fraudulent
GROUP BY l.fraud_pattern, a.rule_name
ORDER BY l.fraud_pattern, hits DESC;


\echo ''
\echo '=== Overall confusion matrix ==='
WITH flagged AS (
    SELECT DISTINCT claim_number FROM detection.fraud_alerts
)
SELECT
    count(*) FILTER (WHERE l.is_fraudulent AND f.claim_number IS NOT NULL)
        AS true_positives,
    count(*) FILTER (WHERE NOT l.is_fraudulent AND f.claim_number IS NOT NULL)
        AS false_positives,
    count(*) FILTER (WHERE l.is_fraudulent AND f.claim_number IS NULL)
        AS false_negatives,
    count(*) FILTER (WHERE NOT l.is_fraudulent AND f.claim_number IS NULL)
        AS true_negatives
FROM evaluation.fraud_labels l
LEFT JOIN flagged f ON f.claim_number = l.claim_number;


\echo ''
\echo '=== Investigator workload ==='
-- The number that decides whether this ships. A fraud team can review a fixed
-- number of cases per day; alert volume is a capacity constraint, not a detail.
SELECT
    count(DISTINCT claim_number)                                AS claims_flagged,
    (SELECT count(*) FROM insurance.claims)                     AS total_claims,
    round(100.0 * count(DISTINCT claim_number)
          / nullif((SELECT count(*) FROM insurance.claims), 0), 2) AS flagged_pct
FROM detection.fraud_alerts;