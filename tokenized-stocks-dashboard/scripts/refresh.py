#!/usr/bin/env python3
"""Create/refresh the Dune queries powering the Tokenized Stocks: Retail vs Bots
dashboard, execute them, and cache results as JSON into the repo `data/` dir."""
import json, os, sys, time, urllib.request, urllib.error, pathlib

KEY = os.environ["DUNE_API_KEY"]
BASE = "https://api.dune.com/api/v1"
# Project root = parent of this script's directory (the dashboard folder).
ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"; QDIR = ROOT / "queries"
DATA.mkdir(parents=True, exist_ok=True); QDIR.mkdir(parents=True, exist_ok=True)
MANIFEST = QDIR / "manifest.json"

def api(method, path, body=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
        headers={"X-Dune-API-Key": KEY, "Content-Type": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode()
            if e.code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(2 ** attempt); continue
            raise RuntimeError(f"{e.code} {msg}")
    raise RuntimeError("unreachable")

# ---- Shared classification logic (Trino / DuneSQL) -------------------------
WINDOW = "365"
CLASSIFY = f"""
WITH xtrades AS (
  SELECT trader_id, block_slot, block_time, block_date, amount_usd, project,
    CASE WHEN token_bought_mint_address LIKE 'Xs%' AND token_bought_symbol LIKE '%x'
         THEN token_bought_symbol ELSE token_sold_symbol END AS sym,
    CASE WHEN token_bought_mint_address LIKE 'Xs%' AND token_bought_symbol LIKE '%x'
         THEN 'buy' ELSE 'sell' END AS side
  FROM dex_solana.trades
  WHERE block_time > now() - interval '{WINDOW}' day
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
"""

QUERIES = {
"daily": ("Tokenized Stocks - Retail vs Bots - Daily volume & wallets", CLASSIFY + """
SELECT x.block_date AS day,
  round(sum(if(l.segment='Retail', x.amount_usd, 0))) AS retail_volume,
  round(sum(if(l.segment='Bot',    x.amount_usd, 0))) AS bot_volume,
  count_if(l.segment='Retail') AS retail_trades,
  count_if(l.segment='Bot')    AS bot_trades,
  count(distinct if(l.segment='Retail', x.trader_id, null)) AS retail_wallets,
  count(distinct if(l.segment='Bot',    x.trader_id, null)) AS bot_wallets
FROM xtrades x JOIN labeled l ON x.trader_id = l.trader_id
GROUP BY 1 ORDER BY 1
"""),

"taxonomy": ("Tokenized Stocks - Retail vs Bots - Segment taxonomy", CLASSIFY + """
SELECT l.subtype,
  CASE WHEN l.subtype='Retail' THEN 'Retail' ELSE 'Bot' END AS segment,
  count(distinct x.trader_id) AS wallets,
  count(*) AS trades,
  round(sum(x.amount_usd)) AS volume_usd
FROM xtrades x JOIN labeled l ON x.trader_id = l.trader_id
GROUP BY 1,2 ORDER BY volume_usd DESC
"""),

"token": ("Tokenized Stocks - Retail vs Bots - Per-stock breakdown", CLASSIFY + """
SELECT x.sym AS symbol,
  round(sum(if(l.segment='Retail', x.amount_usd, 0))) AS retail_volume,
  round(sum(if(l.segment='Bot',    x.amount_usd, 0))) AS bot_volume,
  count_if(l.segment='Retail') AS retail_trades,
  count_if(l.segment='Bot')    AS bot_trades,
  count(distinct if(l.segment='Retail', x.trader_id, null)) AS retail_wallets,
  count(distinct if(l.segment='Bot',    x.trader_id, null)) AS bot_wallets,
  round(sum(x.amount_usd)) AS total_volume
FROM xtrades x JOIN labeled l ON x.trader_id = l.trader_id
GROUP BY 1 ORDER BY total_volume DESC
"""),

"hourly": ("Tokenized Stocks - Retail vs Bots - Hour-of-day pattern", CLASSIFY + """
SELECT hour(x.block_time) AS hour_utc,
  round(sum(if(l.segment='Retail', x.amount_usd, 0))) AS retail_volume,
  round(sum(if(l.segment='Bot',    x.amount_usd, 0))) AS bot_volume,
  count_if(l.segment='Retail') AS retail_trades,
  count_if(l.segment='Bot')    AS bot_trades
FROM xtrades x JOIN labeled l ON x.trader_id = l.trader_id
GROUP BY 1 ORDER BY 1
"""),

"sizedist": ("Tokenized Stocks - Retail vs Bots - Trade size distribution", CLASSIFY + """
SELECT bucket, bucket_order,
  count_if(l.segment='Retail') AS retail_trades,
  count_if(l.segment='Bot')    AS bot_trades,
  round(sum(if(l.segment='Retail', x.amount_usd, 0))) AS retail_volume,
  round(sum(if(l.segment='Bot',    x.amount_usd, 0))) AS bot_volume
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
GROUP BY 1,2 ORDER BY bucket_order
"""),

"topbots": ("Tokenized Stocks - Retail vs Bots - Top bot wallets", f"""
WITH xtrades AS (
  SELECT trader_id, block_slot, block_date, amount_usd,
    CASE WHEN token_bought_mint_address LIKE 'Xs%' AND token_bought_symbol LIKE '%x'
         THEN token_bought_symbol ELSE token_sold_symbol END AS sym,
    CASE WHEN token_bought_mint_address LIKE 'Xs%' AND token_bought_symbol LIKE '%x'
         THEN 'buy' ELSE 'sell' END AS side
  FROM dex_solana.trades
  WHERE block_time > now() - interval '{WINDOW}' day
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
"""),
}

manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}

def run(key, name, sql):
    qid = manifest.get(key)
    if qid:
        api("PATCH", f"/query/{qid}", {"name": name, "query_sql": sql})
    else:
        qid = api("POST", "/query", {"name": name, "query_sql": sql, "is_private": False})["query_id"]
        manifest[key] = qid
        MANIFEST.write_text(json.dumps(manifest, indent=2))
    ex = api("POST", f"/query/{qid}/execute", {})
    eid = ex["execution_id"]
    print(f"  [{key}] query {qid} exec {eid} ...", flush=True)
    while True:
        r = api("GET", f"/execution/{eid}/results?limit=1000")
        st = r.get("state")
        if st == "QUERY_STATE_COMPLETED":
            rows = r["result"]["rows"]
            (DATA / f"{key}.json").write_text(json.dumps(rows))
            print(f"  [{key}] {len(rows)} rows -> data/{key}.json", flush=True)
            return qid
        if st == "QUERY_STATE_FAILED":
            raise RuntimeError(f"{key} failed: {r}")
        time.sleep(3)

def main():
    # Optional CLI args = subset of query keys to refresh; default = all.
    only = [a for a in sys.argv[1:] if a in QUERIES] or list(QUERIES)
    ids = {}
    for key in only:
        name, sql = QUERIES[key]
        ids[key] = run(key, name, sql)
    meta = {
        "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "window_days": int(WINDOW),
        "query_ids": manifest,
        "source": "dex_solana.trades (Dune)",
    }
    (DATA / "meta.json").write_text(json.dumps(meta, indent=2))
    print("DONE", json.dumps(manifest))

if __name__ == "__main__":
    main()
