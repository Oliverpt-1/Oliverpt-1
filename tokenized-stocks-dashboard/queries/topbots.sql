-- Tokenized Stocks - Retail vs Bots - Top bot wallets
-- Dune query · dataset: dex_solana.trades · window: last 365 days
WITH xtrades AS (
  SELECT trader_id, block_slot, block_date, amount_usd,
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
         count(distinct x.sym) tokens, round(sum(x.amount_usd)) volume_usd,
         coalesce(a.arb_slots,0) arb_slots
  FROM xtrades x LEFT JOIN arb a ON x.trader_id = a.trader_id
  GROUP BY 1, a.arb_slots
)
SELECT trader_id AS wallet,
  CASE WHEN arb_slots >= 1 THEN 'Arbitrage / MM'
       WHEN 1.0*trades/active_days >= 50 THEN 'High-frequency'
       ELSE 'High-volume' END AS subtype,
  trades, active_days, tokens, volume_usd, arb_slots
FROM wstats
WHERE arb_slots >= 1 OR 1.0*trades/active_days >= 50 OR trades >= 1000
ORDER BY volume_usd DESC LIMIT 25
