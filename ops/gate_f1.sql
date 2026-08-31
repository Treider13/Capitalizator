-- PHASE-BUILD «Гейт Ф1». Closed demo bounces only. Do not invent rows.
-- Window: first demo-fill or infra/phase.yaml f1_started_at (not set).
SELECT
  count(*) AS n_bounce,
  avg(r) AS avg_r,
  count(*) FILTER (WHERE r > 0) AS wins
FROM episode
WHERE mode = 'demo'
  AND setup_tag = 'bounce'
  AND status = 'closed'
  AND fill_qty > 0
  AND r IS NOT NULL
  AND opened_at >= :f1_started_at;

SELECT count(*) AS average_attempts
FROM risk_reject
WHERE reason IN ('average_in','add_to_position','pyramid')
   OR raw_json::text ILIKE '%average_in%';
