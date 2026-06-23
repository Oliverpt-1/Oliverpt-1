-- Tokenized Stocks - Retail vs Bots - Trade size distribution
-- Dune query · dataset: dex_solana.trades · window: last 365 days
WITH xtrades AS (
  SELECT trader_id, block_slot, block_time, block_date, amount_usd, project,
    CASE WHEN token_bought_mint_address LIKE 'Xs%' AND token_bought_symbol LIKE '%x'
         THEN token_bought_symbol ELSE token_sold_symbol END AS sym,
    CASE WHEN token_bought_mint_address LIKE 'Xs%' AND token_bought_symbol LIKE '%x'
         THEN 'buy' ELSE 'sell' END AS side
  FROM dex_solana.trades
  WHERE block_time > now() - interval '365' day
    AND amount_usd IS NOT NULL
    AND ((token_bought_mint_address LIKE 'Xs%' AND token_bought_symbol LIKE '%x')
      OR (token_sold_mint_address LIKE 'Xs%' AND token_sold_symbol LIKE '%x'))
),
arb AS (
  SELECT trader_id, count(*) arb_slots FROM (
    SELECT trader_id, sym, block_slot FROM xtrades
    GROUP BY 1,2,3 HAVING count(distinct side) = 2
  ) GROUP BY 1
),
wstats AS (
  SELECT x.trader_id, count(*) trades, count(distinct x.block_date) active_days,
         sum(x.amount_usd) vol, coalesce(a.arb_slots,0) arb_slots
  FROM xtrades x LEFT JOIN arb a ON x.trader_id = a.trader_id
  GROUP BY 1, a.arb_slots
),
labeled AS (
  SELECT trader_id,
    CASE WHEN arb_slots >= 1 OR 1.0*trades/active_days >= 50 OR trades >= 1000
         THEN 'Bot' ELSE 'Retail' END AS segment,
    CASE WHEN arb_slots >= 1 THEN 'Arbitrage / MM'
         WHEN 1.0*trades/active_days >= 50 THEN 'High-frequency'
         WHEN trades >= 1000 THEN 'High-volume'
         ELSE 'Retail' END AS subtype
  FROM wstats
)

SELECT bucket, bucket_order, l.segment,
  count(*) AS trades,
  round(sum(x.amount_usd)) AS volume_usd
FROM xtrades x
JOIN labeled l ON x.trader_id = l.trader_id
CROSS JOIN LATERAL (
  SELECT CASE
    WHEN x.amount_usd < 10 THEN '<$10'
    WHEN x.amount_usd < 100 THEN '$10-100'
    WHEN x.amount_usd < 1000 THEN '$100-1k'
    WHEN x.amount_usd < 10000 THEN '$1k-10k'
    WHEN x.amount_usd < 100000 THEN '$10k-100k'
    ELSE '>$100k' END AS bucket,
    CASE
    WHEN x.amount_usd < 10 THEN 1
    WHEN x.amount_usd < 100 THEN 2
    WHEN x.amount_usd < 1000 THEN 3
    WHEN x.amount_usd < 10000 THEN 4
    WHEN x.amount_usd < 100000 THEN 5
    ELSE 6 END AS bucket_order
) b
GROUP BY 1,2,3 ORDER BY bucket_order, segment
