/* Tokenized Stocks: Retail vs. Bots — dashboard logic
   Loads cached Dune query results from /data and renders the charts. */

const C = {
  retail: '#2dd4bf', retailDim: 'rgba(45,212,191,.18)',
  bot: '#f5a524',   botDim: 'rgba(245,165,36,.18)',
  accent: '#ff7847',
  grid: 'rgba(255,255,255,.05)', tick: '#7d8a9c',
  sub: { 'Arbitrage / MM': '#f5a524', 'High-frequency': '#ff7847', 'High-volume': '#9aa6b8', 'Retail': '#2dd4bf' },
};
const DUNE_Q = {};

const $ = (s, r = document) => r.querySelector(s);
const fmtUSD = n => {
  n = +n || 0; const a = Math.abs(n);
  if (a >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B';
  if (a >= 1e6) return '$' + (n / 1e6).toFixed(1) + 'M';
  if (a >= 1e3) return '$' + (n / 1e3).toFixed(1) + 'k';
  return '$' + Math.round(n);
};
const fmtNum = n => {
  n = +n || 0; const a = Math.abs(n);
  if (a >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (a >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return String(Math.round(n));
};
const pct = (x, t) => t ? Math.round((x / t) * 100) : 0;
const pct1 = (x, t) => t ? (x / t * 100).toFixed(1) : '0';

async function loadJSON(name) {
  const r = await fetch(`data/${name}.json?v=${Date.now()}`);
  if (!r.ok) throw new Error(`failed to load ${name}`);
  return r.json();
}

function chartDefaults() {
  Chart.defaults.color = C.tick;
  Chart.defaults.font.family = "'Inter',sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.plugins.legend.display = false;
  Chart.defaults.maintainAspectRatio = false;
}

const tooltip = (extra = {}) => ({
  backgroundColor: '#0a0f17', borderColor: '#26303f', borderWidth: 1,
  titleColor: '#e8eef6', bodyColor: '#c0ccdb', padding: 11, cornerRadius: 9,
  boxPadding: 5, usePointStyle: true, ...extra,
});

/* ---------------- KPIs + split ---------------- */
function renderKPIs(tax) {
  const tot = tax.reduce((a, r) => ({ wallets: a.wallets + r.wallets, trades: a.trades + r.trades, vol: a.vol + r.volume_usd }), { wallets: 0, trades: 0, vol: 0 });
  const bot = tax.filter(r => r.segment === 'Bot').reduce((a, r) => ({ wallets: a.wallets + r.wallets, trades: a.trades + r.trades, vol: a.vol + r.volume_usd }), { wallets: 0, trades: 0, vol: 0 });
  const retailVol = tot.vol - bot.vol;

  const cards = [
    { label: 'Volume traded', value: fmtUSD(tot.vol), sub: 'all xStocks, window', cls: '' },
    { label: 'Total trades', value: fmtNum(tot.trades), sub: 'DEX swaps', cls: '' },
    { label: 'Unique wallets', value: fmtNum(tot.wallets), sub: 'distinct traders', cls: '' },
    { label: 'Bot volume share', value: pct(bot.vol, tot.vol) + '%', sub: fmtUSD(bot.vol) + ' of volume', cls: 'bot' },
    { label: 'Bot trade share', value: pct(bot.trades, tot.trades) + '%', sub: fmtNum(bot.trades) + ' trades', cls: 'bot' },
    { label: 'Retail wallets', value: pct(tot.wallets - bot.wallets, tot.wallets) + '%', sub: 'of all wallets', cls: 'retail' },
  ];
  $('#kpis').innerHTML = cards.map(c => `
    <div class="kpi ${c.cls}">
      <div class="k-label">${c.label}</div>
      <div class="k-value">${c.value}</div>
      <div class="k-sub">${c.sub}</div>
    </div>`).join('');

  // split bars
  const rows = [
    { label: 'Wallets', r: tot.wallets - bot.wallets, b: bot.wallets },
    { label: 'Trades', r: tot.trades - bot.trades, b: bot.trades },
    { label: 'Volume', r: retailVol, b: bot.vol },
  ];
  $('#splitBars').innerHTML = rows.map(row => {
    const t = row.r + row.b, rp = pct1(row.r, t), bp = pct1(row.b, t);
    return `<div class="sb-row">
      <div class="sb-label">${row.label}</div>
      <div class="sb-track">
        <div class="sb-seg retail" style="width:${rp}%">${rp >= 7 ? rp + '%' : ''}</div>
        <div class="sb-seg bot" style="width:${bp}%">${bp >= 7 ? bp + '%' : ''}</div>
      </div></div>`;
  }).join('');
  $('#splitTakeaway').innerHTML =
    `<b>${pct(tot.wallets - bot.wallets, tot.wallets)}%</b> of wallets are retail, yet bots account for ` +
    `<b>${pct(bot.trades, tot.trades)}%</b> of all trades and <b>${pct(bot.vol, tot.vol)}%</b> of USD volume. ` +
    `Tokenized-stock liquidity on-chain is overwhelmingly machine-driven.`;
}

/* ---------------- Daily stacked ---------------- */
let dailyChart, dailyRaw, dailyMetric = 'volume', dailyRange = 180;
function buildDaily() {
  let rows = [...dailyRaw].sort((a, b) => a.day < b.day ? -1 : 1);
  if (dailyRange < 9999) rows = rows.slice(-dailyRange);
  const retail = rows.map(d => +d['retail_' + dailyMetric] || 0);
  const bot = rows.map(d => +d['bot_' + dailyMetric] || 0);
  const labels = rows.map(d => d.day.slice(5));
  const isUSD = dailyMetric === 'volume';
  const fmt = isUSD ? fmtUSD : fmtNum;

  const mk = (ctx, color) => { const g = ctx.createLinearGradient(0, 0, 0, 300); g.addColorStop(0, color + '55'); g.addColorStop(1, color + '08'); return g; };
  const data = {
    labels,
    datasets: [
      { label: 'Retail', data: retail, borderColor: C.retail, backgroundColor: c => mk(c.chart.ctx, '#2dd4bf'), fill: true, tension: .3, pointRadius: 0, borderWidth: 1.5, order: 2 },
      { label: 'Bots', data: bot, borderColor: C.bot, backgroundColor: c => mk(c.chart.ctx, '#f5a524'), fill: true, tension: .3, pointRadius: 0, borderWidth: 1.5, order: 1 },
    ],
  };
  const opts = {
    interaction: { mode: 'index', intersect: false },
    scales: {
      x: { stacked: true, grid: { display: false }, ticks: { maxTicksLimit: 9, color: C.tick }, border: { color: C.grid } },
      y: { stacked: true, grid: { color: C.grid }, border: { display: false }, ticks: { callback: v => fmt(v), color: C.tick } },
    },
    plugins: { tooltip: tooltip({ callbacks: { label: c => `${c.dataset.label}: ${fmt(c.parsed.y)}` } }) },
  };
  if (dailyChart) { dailyChart.data = data; dailyChart.options = opts; dailyChart.update(); }
  else dailyChart = new Chart($('#dailyChart'), { type: 'line', data, options: opts });
}

/* ---------------- Taxonomy donut ---------------- */
let taxChart, taxRaw, taxMetric = 'volume_usd';
function buildTax() {
  const rows = [...taxRaw].sort((a, b) => b[taxMetric] - a[taxMetric]);
  const labels = rows.map(r => r.subtype);
  const vals = rows.map(r => r[taxMetric]);
  const colors = labels.map(l => C.sub[l] || '#888');
  const tot = vals.reduce((a, b) => a + b, 0);
  const botTot = rows.filter(r => r.segment === 'Bot').reduce((a, r) => a + r[taxMetric], 0);

  const data = { labels, datasets: [{ data: vals, backgroundColor: colors, borderColor: '#10151f', borderWidth: 3, hoverOffset: 6 }] };
  const fmt = taxMetric === 'volume_usd' ? fmtUSD : fmtNum;
  const opts = {
    cutout: '68%',
    plugins: { tooltip: tooltip({ callbacks: { label: c => `${c.label}: ${fmt(c.raw)} (${pct1(c.raw, tot)}%)` } }) },
  };
  if (taxChart) { taxChart.data = data; taxChart.options = opts; taxChart.update(); }
  else taxChart = new Chart($('#taxChart'), { type: 'doughnut', data, options: opts });

  $('#donutCenter').innerHTML = `<div class="dc-top">Bots</div><div class="dc-val">${pct(botTot, tot)}%</div><div class="dc-sub">of ${taxMetric === 'volume_usd' ? 'volume' : 'wallets'}</div>`;
  $('#taxLegend').innerHTML = rows.map(r =>
    `<div class="li"><span class="sw" style="background:${C.sub[r.subtype]}"></span>${r.subtype} · <b>${fmt(r[taxMetric])}</b></div>`).join('');
}

/* ---------------- Token dominance ---------------- */
function buildToken(tokenRaw) {
  let arr = tokenRaw.map(r => ({ sym: r.symbol, Retail: +r.retail_volume || 0, Bot: +r.bot_volume || 0, tot: +r.total_volume || 0 }))
    .filter(x => x.tot > 50000);
  arr.sort((a, b) => b.tot - a.tot);
  arr = arr.slice(0, 16).sort((a, b) => (b.Bot / b.tot) - (a.Bot / a.tot));
  const labels = arr.map(x => x.sym);
  const retail = arr.map(x => +(x.Retail / x.tot * 100).toFixed(1));
  const bot = arr.map(x => +(x.Bot / x.tot * 100).toFixed(1));
  const vol = arr.map(x => x.tot);

  new Chart($('#tokenChart'), {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'Bots', data: bot, backgroundColor: C.bot, borderRadius: 3, stack: 's' },
        { label: 'Retail', data: retail, backgroundColor: C.retail, borderRadius: 3, stack: 's' },
      ],
    },
    options: {
      indexAxis: 'y',
      scales: {
        x: { stacked: true, max: 100, grid: { color: C.grid }, border: { display: false }, ticks: { callback: v => v + '%', color: C.tick } },
        y: { stacked: true, grid: { display: false }, ticks: { color: '#c4d0e0', font: { weight: '600' } } },
      },
      plugins: {
        tooltip: tooltip({
          callbacks: {
            label: c => `${c.dataset.label}: ${c.parsed.x}% of volume`,
            afterBody: items => 'Total volume: ' + fmtUSD(vol[items[0].dataIndex]),
          },
        }),
      },
    },
  });
}

/* ---------------- Hourly retail share ---------------- */
function buildHourly(hourlyRaw) {
  const hv = Array.from({ length: 24 }, () => ({ Retail: 0, Bot: 0 }));
  for (const r of hourlyRaw) hv[r.hour_utc] = { Retail: +r.retail_volume || 0, Bot: +r.bot_volume || 0 };
  const share = hv.map(h => { const t = h.Retail + h.Bot; return t ? +(h.Retail / t * 100).toFixed(1) : 0; });
  const avg = share.reduce((a, b) => a + b, 0) / 24;
  const labels = hv.map((_, i) => String(i).padStart(2, '0'));

  const band = {
    id: 'mktBand',
    beforeDraw(chart) {
      const { ctx, chartArea: a, scales: { x } } = chart;
      if (!a) return;
      const x1 = x.getPixelForValue(13), x2 = x.getPixelForValue(20);
      ctx.save(); ctx.fillStyle = 'rgba(45,212,191,.07)';
      ctx.fillRect(x1, a.top, x2 - x1, a.bottom - a.top);
      ctx.fillStyle = 'rgba(45,212,191,.5)'; ctx.font = '600 10px Inter';
      ctx.fillText('US market hrs', x1 + 6, a.top + 13); ctx.restore();
    },
  };
  new Chart($('#hourlyChart'), {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'Retail share', data: share, borderColor: C.retail, borderWidth: 2.5,
        pointRadius: 0, tension: .35, fill: true,
        backgroundColor: c => { const g = c.chart.ctx.createLinearGradient(0, 0, 0, 280); g.addColorStop(0, '#2dd4bf45'); g.addColorStop(1, '#2dd4bf05'); return g; },
      }],
    },
    options: {
      scales: {
        x: { grid: { display: false }, ticks: { color: C.tick, callback: (v, i) => i % 3 === 0 ? labels[i] + 'h' : '' } },
        y: { grid: { color: C.grid }, border: { display: false }, ticks: { callback: v => v + '%', color: C.tick }, suggestedMax: Math.max(...share) * 1.25 },
      },
      plugins: {
        tooltip: tooltip({ callbacks: { label: c => `Retail: ${c.parsed.y}% of volume · Bots: ${(100 - c.parsed.y).toFixed(1)}%` } }),
        annLine: true,
      },
    },
    plugins: [band, {
      id: 'avgLine',
      afterDatasetsDraw(chart) {
        const { ctx, chartArea: a, scales: { y } } = chart; if (!a) return;
        const yy = y.getPixelForValue(avg);
        ctx.save(); ctx.setLineDash([4, 4]); ctx.strokeStyle = 'rgba(255,255,255,.22)';
        ctx.beginPath(); ctx.moveTo(a.left, yy); ctx.lineTo(a.right, yy); ctx.stroke();
        ctx.setLineDash([]); ctx.fillStyle = 'rgba(255,255,255,.45)'; ctx.font = '10px Inter';
        ctx.fillText('avg ' + avg.toFixed(1) + '%', a.right - 56, yy - 5); ctx.restore();
      },
    }],
  });
}

/* ---------------- Size distribution ---------------- */
function buildSize(sizeRaw) {
  const rows = [...sizeRaw].sort((a, b) => a.bucket_order - b.bucket_order);
  const order = rows.map(r => r.bucket);
  const totR = rows.reduce((a, r) => a + (+r.retail_trades || 0), 0);
  const totB = rows.reduce((a, r) => a + (+r.bot_trades || 0), 0);
  const retail = rows.map(r => +((+r.retail_trades || 0) / totR * 100).toFixed(1));
  const bot = rows.map(r => +((+r.bot_trades || 0) / totB * 100).toFixed(1));

  new Chart($('#sizeChart'), {
    type: 'bar',
    data: {
      labels: order,
      datasets: [
        { label: 'Retail', data: retail, backgroundColor: C.retail, borderRadius: 4 },
        { label: 'Bots', data: bot, backgroundColor: C.bot, borderRadius: 4 },
      ],
    },
    options: {
      scales: {
        x: { grid: { display: false }, ticks: { color: '#c4d0e0', font: { weight: '600' } } },
        y: { grid: { color: C.grid }, border: { display: false }, ticks: { callback: v => v + '%', color: C.tick } },
      },
      plugins: {
        legend: { display: true, labels: { usePointStyle: true, boxWidth: 8, color: C.tick, padding: 16 } },
        tooltip: tooltip({ callbacks: { label: c => `${c.dataset.label}: ${c.parsed.y}% of its trades` } }),
      },
    },
  });
}

/* ---------------- Top bots table ---------------- */
function buildTable(rows) {
  const tag = s => s === 'Arbitrage / MM' ? '<span class="tag">Arbitrage / MM</span>'
    : s === 'High-frequency' ? '<span class="tag hf">High-frequency</span>'
      : '<span class="tag hv">High-volume</span>';
  $('#botTable tbody').innerHTML = rows.map((r, i) => {
    const w = r.wallet, short = w.slice(0, 4) + '…' + w.slice(-4);
    return `<tr>
      <td class="rank">${i + 1}</td>
      <td><a class="wallet-link" href="https://solscan.io/account/${w}" target="_blank" rel="noopener" title="${w}">${short}</a></td>
      <td>${tag(r.subtype)}</td>
      <td class="num">${fmtNum(r.trades)}</td>
      <td class="num">${r.active_days}</td>
      <td class="num">${r.tokens}</td>
      <td class="num">${fmtNum(r.arb_slots)}</td>
      <td class="num vol">${fmtUSD(r.volume_usd)}</td>
    </tr>`;
  }).join('');
}

/* ---------------- wiring ---------------- */
function wireToggles() {
  $('#metricToggle').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    $('#metricToggle .active').classList.remove('active'); b.classList.add('active');
    dailyMetric = b.dataset.metric; buildDaily();
  });
  $('#rangeToggle').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    $('#rangeToggle .active').classList.remove('active'); b.classList.add('active');
    dailyRange = +b.dataset.range; buildDaily();
  });
  $('#taxToggle').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    $('#taxToggle .active').classList.remove('active'); b.classList.add('active');
    taxMetric = b.dataset.metric; buildTax();
  });
}

function setMeta(meta, dash) {
  if (meta.last_updated) $('#lastUpdated').textContent = meta.last_updated.slice(0, 10);
  if (meta.window_days) { $('#windowDays').textContent = meta.window_days; $('#windowDays2').textContent = meta.window_days; }
  const ids = meta.query_ids || {};
  const names = { taxonomy: 'Segment taxonomy', daily: 'Daily activity', token: 'Per-stock', hourly: 'Hour-of-day', sizedist: 'Trade size', topbots: 'Top bots' };
  const dashUrl = dash && dash.dashboard_url;
  const first = Object.values(ids)[0];
  const headerUrl = dashUrl || (first && `https://dune.com/queries/${first}`);
  if (headerUrl) { $('#duneLink').href = headerUrl; $('#footDune').href = headerUrl; }
  if (dashUrl) $('#duneLink').textContent = 'Open on Dune ↗';
  $('#queryLinks').innerHTML = '<span style="color:var(--faint);font-size:12px;align-self:center;margin-right:4px">Live Dune queries:</span>' +
    Object.entries(ids).map(([k, id]) => `<a href="https://dune.com/queries/${id}" target="_blank" rel="noopener">${names[k] || k} ↗</a>`).join('');
}

async function main() {
  chartDefaults();
  try {
    const [meta, tax, daily, token, hourly, size, bots] = await Promise.all(
      ['meta', 'taxonomy', 'daily', 'token', 'hourly', 'sizedist', 'topbots'].map(loadJSON));
    const dash = await loadJSON('dune_dashboard').catch(() => null);
    setMeta(meta, dash);
    renderKPIs(tax);
    taxRaw = tax; buildTax();
    dailyRaw = daily; buildDaily();
    buildToken(token);
    buildHourly(hourly);
    buildSize(size);
    buildTable(bots);
    wireToggles();
  } catch (e) {
    document.querySelector('main').insertAdjacentHTML('afterbegin',
      `<div class="card" style="border-color:#5a2530"><b>Could not load data.</b><br><span style="color:var(--muted)">${e.message}. Serve this folder over HTTP (e.g. <code>python3 -m http.server</code>) so the JSON files in <code>/data</code> can be fetched.</span></div>`);
    console.error(e);
  }
}
main();
