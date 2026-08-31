-- 3.13.5 — bounce R and breakout R are separate. failed_break is in neither.
SELECT
  count(*) FILTER (WHERE setup_tag = 'bounce') AS n_bounce,
  avg(r) FILTER (WHERE setup_tag = 'bounce') AS avg_r_bounce,
  count(*) FILTER (WHERE setup_tag = 'breakout') AS n_breakout,
  avg(r) FILTER (WHERE setup_tag = 'breakout') AS avg_r_breakout,
  count(*) FILTER (WHERE setup_tag = 'failed_break') AS n_failed_break
FROM episode
WHERE mode = 'demo'
  AND status = 'closed'
  AND fill_qty > 0
  AND r IS NOT NULL;
