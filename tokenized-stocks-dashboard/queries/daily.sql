-- Tokenized Stocks - Retail vs Bots - Daily volume & wallets
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

SELECT x.block_date AS day,
  round(sum(if(l.segment='Retail', x.amount_usd, 0))) AS retail_volume,
  round(sum(if(l.segment='Bot',    x.amount_usd, 0))) AS bot_volume,
  count_if(l.segment='Retail') AS retail_trades,
  count_if(l.segment='Bot')    AS bot_trades,
  count(distinct if(l.segment='Retail', x.trader_id, null)) AS retail_wallets,
  count(distinct if(l.segment='Bot',    x.trader_id, null)) AS bot_wallets
FROM xtrades x JOIN labeled l ON x.trader_id = l.trader_id
GROUP BY 1 ORDER BY 1
