-- PHASE-BUILD «Гейт Ф3». Closed demo bounce+breakout only. Do not invent rows.
-- failed_break is not in n_break or n_sum.
SELECT
  count(*) FILTER (WHERE setup_tag = 'breakout') AS n_break,
  count(*) FILTER (WHERE setup_tag = 'bounce') AS n_bounce,
  count(*) FILTER (WHERE setup_tag IN ('bounce','breakout')) AS n_sum,
  avg(r) FILTER (WHERE setup_tag IN ('bounce','breakout')) AS avg_r_sum,
  avg(r) FILTER (WHERE setup_tag = 'bounce') AS avg_r_bounce
FROM episode
WHERE mode = 'demo' AND status = 'closed' AND fill_qty > 0 AND r IS NOT NULL;

SELECT count(*) AS whale_entries
FROM episode e
JOIN card c ON c.card_id = e.card_id
WHERE e.fill_qty > 0 AND c.entry_reason = 'whale';
