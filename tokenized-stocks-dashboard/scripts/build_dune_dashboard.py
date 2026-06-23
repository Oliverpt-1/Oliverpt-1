#!/usr/bin/env python3
"""Assemble the native Dune dashboard for "Tokenized Stocks: Retail vs. Bots".

Uses Dune's dashboard API to:
  1. ensure a one-row KPI query exists (for the counter widgets),
  2. create a visualization (chart / counter / table / pie) per panel,
  3. create a dashboard and lay every widget out on the 24-col grid.

Re-runnable: query IDs are kept in queries/manifest.json; the dashboard URL is
written to data/dune_dashboard.json. Requires DUNE_API_KEY.
"""
import json, os, sys, time, urllib.request, urllib.error, pathlib

KEY = os.environ["DUNE_API_KEY"]
BASE = "https://api.dune.com/api/v1"
ROOT = pathlib.Path(__file__).resolve().parent.parent
QDIR = ROOT / "queries"; DATA = ROOT / "data"
MANIFEST = QDIR / "manifest.json"

THROTTLE = float(os.environ.get("DUNE_THROTTLE", "4"))  # seconds between write calls
_last = [0.0]

def api(method, path, body=None):
    if method in ("POST", "PATCH"):
        dt = THROTTLE - (time.time() - _last[0])
        if dt > 0:
            time.sleep(dt)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method,
        headers={"X-Dune-API-Key": KEY, "Content-Type": "application/json"})
    for attempt in range(7):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                _last[0] = time.time()
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode()
            _last[0] = time.time()
            if e.code in (429, 500, 502, 503) and attempt < 6:
                wait = min(60, 5 * (attempt + 1))
                print(f"  {e.code} on {path}; retry in {wait}s", flush=True)
                time.sleep(wait); continue
            raise RuntimeError(f"{method} {path} -> {e.code} {msg}")
    raise RuntimeError("unreachable")

manifest = json.loads(MANIFEST.read_text())
WINDOW = "365"

# --- KPI query (single row) -------------------------------------------------
KPI_SQL = f"""
WITH xtrades AS (
  SELECT trader_id, block_slot, block_date, amount_usd,
    CASE WHEN token_bought_mint_address LIKE 'Xs%' AND token_bought_symbol LIKE '%x'
         THEN token_bought_symbol ELSE token_sold_symbol END AS sym,
    CASE WHEN token_bought_mint_address LIKE 'Xs%' AND token_bought_symbol LIKE '%x'
         THEN 'buy' ELSE 'sell' END AS side
  FROM dex_solana.trades
  WHERE block_time > now() - interval '{WINDOW}' day AND amount_usd IS NOT NULL
    AND ((token_bought_mint_address LIKE 'Xs%' AND token_bought_symbol LIKE '%x')
      OR (token_sold_mint_address LIKE 'Xs%' AND token_sold_symbol LIKE '%x'))
),
arb AS (SELECT trader_id, count(*) arb_slots FROM (
  SELECT trader_id, sym, block_slot FROM xtrades GROUP BY 1,2,3 HAVING count(distinct side)=2) GROUP BY 1),
w AS (
  SELECT x.trader_id, count(*) trades, count(distinct x.block_date) active_days,
         sum(x.amount_usd) vol, coalesce(a.arb_slots,0) arb_slots
  FROM xtrades x LEFT JOIN arb a ON x.trader_id=a.trader_id GROUP BY 1, a.arb_slots),
l AS (SELECT *, CASE WHEN arb_slots>=1 OR 1.0*trades/active_days>=50 OR trades>=1000
                     THEN 'Bot' ELSE 'Retail' END seg FROM w)
SELECT
  round(sum(vol)/1e6) AS total_volume_musd,
  sum(trades)        AS total_trades,
  count(*)           AS unique_wallets,
  round(100.0*sum(if(seg='Bot', vol, 0))/sum(vol), 1)        AS bot_volume_pct,
  round(100.0*sum(if(seg='Bot', trades, 0))/sum(trades), 1)  AS bot_trade_pct,
  round(100.0*sum(if(seg='Retail', 1, 0))/count(*), 1)       AS retail_wallet_pct
FROM l
"""

def ensure_kpi():
    qid = manifest.get("kpi")
    if qid:
        api("PATCH", f"/query/{qid}", {"query_sql": KPI_SQL})
    else:
        qid = api("POST", "/query", {"name": "Tokenized Stocks - Retail vs Bots - KPIs",
                                     "query_sql": KPI_SQL, "is_private": False})["query_id"]
        manifest["kpi"] = qid; MANIFEST.write_text(json.dumps(manifest, indent=2))
    # execute so results are cached for counters
    eid = api("POST", f"/query/{qid}/execute", {})["execution_id"]
    while api("GET", f"/execution/{eid}/results?limit=1")["state"] not in ("QUERY_STATE_COMPLETED", "QUERY_STATE_FAILED"):
        time.sleep(2)
    return qid

VIZ = manifest.setdefault("viz", {})

def viz(key, query_id, vtype, name, options):
    """Create (once) and remember a visualization; reuse its id on re-runs."""
    if key in VIZ:
        return VIZ[key]
    vid = api("POST", f"/queries/{query_id}/visualizations",
              {"type": vtype, "name": name, "options": options})["id"]
    VIZ[key] = vid
    MANIFEST.write_text(json.dumps(manifest, indent=2))
    print(f"  viz[{key}] = {vid}", flush=True)
    return vid

RETAIL, BOT = "#2dd4bf", "#f5a524"
def chart_opts(gtype, xcol, retail_col, bot_col, stacked=False,
               yfmt="0.00a", retail_name="Retail", bot_name="Bot"):
    """Build a Dune chart options blob in the canonical (wide-format) schema:
    one y-column per series, seriesOptions keyed by column name."""
    return {
        "globalSeriesType": gtype,
        "columnMapping": {xcol: "x", retail_col: "y", bot_col: "y"},
        "legend": {"enabled": True},
        "sortX": True, "reverseX": False,
        "xAxis": {"type": "-"},
        "yAxis": [{"type": "linear", "tickFormat": yfmt}],
        "series": {"stacking": "stack" if stacked else None},
        "stacking": "stack" if stacked else None,
        "seriesOptions": {
            retail_col: {"name": retail_name, "color": RETAIL, "type": gtype, "yAxis": 0, "zIndex": 1},
            bot_col:    {"name": bot_name,    "color": BOT,    "type": gtype, "yAxis": 0, "zIndex": 0},
        },
    }

def main():
    q = manifest
    kpi = ensure_kpi()

    # ---- counters (KPIs) ----
    counters = [
        ("Volume traded (USD, millions)", "total_volume_musd"),
        ("Total trades", "total_trades"),
        ("Unique wallets", "unique_wallets"),
        ("Bot share of volume (%)", "bot_volume_pct"),
        ("Bot share of trades (%)", "bot_trade_pct"),
        ("Retail share of wallets (%)", "retail_wallet_pct"),
    ]
    counter_ids = [viz(f"kpi{i}", kpi, "counter", nm, {"counterColName": col, "rowNumber": 1})
                   for i, (nm, col) in enumerate(counters)]

    # ---- charts (wide format: one y-column per series) ----
    daily = viz("daily2", q["daily"], "chart", "Daily volume - retail vs bots ($)",
                chart_opts("area", "day", "retail_volume", "bot_volume", stacked=True, yfmt="$0.0a"))

    token = viz("token2", q["token"], "chart", "Volume by stock - retail vs bots ($)",
                chart_opts("bar", "symbol", "retail_volume", "bot_volume", stacked=True, yfmt="$0.0a"))

    hourly = viz("hourly2", q["hourly"], "chart", "Volume by hour of day, UTC ($)",
                 chart_opts("line", "hour_utc", "retail_volume", "bot_volume", stacked=False, yfmt="$0.0a"))

    size = viz("size2", q["sizedist"], "chart", "Trades by ticket size",
               chart_opts("column", "bucket", "retail_trades", "bot_trades", stacked=False, yfmt="0a"))

    tax_pie = viz("taxpie2", q["taxonomy"], "chart", "Volume by wallet segment", {
        "globalSeriesType": "pie", "legend": {"enabled": True},
        "showDataLabels": True, "numberFormat": "$0.0a",
        "columnMapping": {"subtype": "x", "volume_usd": "y"},
        "seriesOptions": {"volume_usd": {"color": BOT}}})

    topbots = viz("topbots", q["topbots"], "table", "Top bot wallets", {})

    # ---- text ----
    title = ("# Tokenized Stocks: Retail vs. Bots\n"
             "On-chain trading of Backed **xStocks** (TSLAx, SPYx, CRCLx, NVDAx, AAPLx, …) on "
             "**Solana**, over the last 365 days. Wallets are split into **human retail** vs. "
             "**automated bots** (arbitrage / market-makers, high-frequency, high-volume traders). "
             "Source: `dex_solana.trades`.")
    method = ("## Methodology\n"
              "A wallet is a **bot** if it meets *any* of: (1) **arbitrage / MM** — bought and sold the "
              "same stock inside one Solana slot (~400 ms); (2) **high-frequency** — ≥ 50 trades per "
              "active day; (3) **high-volume** — ≥ 1,000 trades in the window. Everything else is "
              "**retail** (the median retail wallet makes ~2 trades total).\n\n"
              "*Heuristics, not ground truth: a sophisticated human can look like a slow bot, one person "
              "can run many wallets, and centralized-exchange flow that settles off-chain is not captured. "
              "Not investment advice.*")

    # ---- layout (24-col grid) ----
    def vw(vid, row, col, sx, sy): return {"visualization_id": vid, "position": {"row": row, "col": col, "size_x": sx, "size_y": sy}}
    def tw(text, row, col, sx, sy): return {"text": text, "position": {"row": row, "col": col, "size_x": sx, "size_y": sy}}

    text_widgets, viz_widgets = [], []
    text_widgets.append(tw(title, 0, 0, 24, 3))
    for i, cid in enumerate(counter_ids):
        viz_widgets.append(vw(cid, 3, i * 4, 4, 3))
    viz_widgets.append(vw(daily, 6, 0, 16, 7))
    viz_widgets.append(vw(tax_pie, 6, 16, 8, 7))
    viz_widgets.append(vw(token, 13, 0, 12, 8))
    viz_widgets.append(vw(size, 13, 12, 12, 8))
    viz_widgets.append(vw(hourly, 21, 0, 12, 7))
    viz_widgets.append(vw(topbots, 21, 12, 12, 7))
    text_widgets.append(tw(method, 28, 0, 24, 4))

    # ---- dashboard ----
    did = q.get("dashboard_id")
    if not did:
        d = api("POST", "/dashboards", {"name": "Tokenized Stocks: Retail vs. Bots"})
        did = d["dashboard_id"]; q["dashboard_id"] = did
        MANIFEST.write_text(json.dumps(q, indent=2))
    res = api("PATCH", f"/dashboards/{did}",
              {"visualization_widgets": viz_widgets, "text_widgets": text_widgets})
    url = res["dashboard_url"]
    (DATA / "dune_dashboard.json").write_text(json.dumps(
        {"dashboard_url": url, "dashboard_id": did, "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=2))
    print("DASHBOARD:", url)

if __name__ == "__main__":
    main()
