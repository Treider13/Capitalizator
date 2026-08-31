-- 3.16.1 — gesture × touch outcome × BTC regime. Empty cell is not an edge.
-- Do not invent n. Do not trade a cell where n is 0.
SELECT
  z.gesture,
  t.outcome,
  b.regime,
  count(*) AS n
FROM zlg_label z
JOIN touch t
  ON t.zone_id = z.zone_id
 AND t.known_at >= z.known_at
LEFT JOIN btc_regime b
  ON b.as_of <= t.ts
WHERE z.known_at <= t.ts
GROUP BY z.gesture, t.outcome, b.regime;
