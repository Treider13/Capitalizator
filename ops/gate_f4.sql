-- PHASE-BUILD «Гейт Ф4». live = mode micro. 100 AND 8 weeks, not OR.
-- Do not invent micro rows.
SELECT
  count(*) AS n_live,
  min(opened_at) AS first_micro,
  date_diff('week', min(opened_at), max(opened_at)) + 1 AS weeks_spanned,
  avg(CASE WHEN r > 0 THEN 1.0 ELSE 0.0 END) AS wr,
  avg(r) FILTER (WHERE r > 0) AS avg_win,
  avg(r) FILTER (WHERE r < 0) AS avg_loss,
  count(*) FILTER (WHERE r > 0) AS n_win,
  count(*) FILTER (WHERE r < 0) AS n_loss
FROM episode
WHERE mode = 'micro' AND status = 'closed' AND fill_qty > 0 AND r IS NOT NULL;

SELECT count(*) AS liq FROM episode WHERE mode = 'micro' AND liquidated = true;
SELECT count(*) AS against_btc FROM episode
 WHERE mode = 'micro' AND fill_qty > 0 AND veto_btc_would_reject = true;
