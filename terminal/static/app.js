/* Terminal front end — single clean build.
 *
 * Rewritten 2026-08-05. The previous version grew by appending three blocks
 * that monkey-patched selectSymbol/loadWatchlist on top of one another, and the
 * strategies panel silently stopped refreshing as a result. Wrapping functions
 * you already own is never worth it — this file defines each thing once.
 *
 * Design rule: no price renders without its freshness.
 */

const $ = (s) => document.querySelector(s);
const fmt = (v, d = 2) =>
  v === null || v === undefined || Number.isNaN(v)
    ? "—"
    : v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const badge = (f) => `<span class="b b-${f}">${f}</span>`;

let market = "us";
let active = new Set(["ema", "ttm"]);      // indicators — no cap
let tf = { i: "1d", l: "6mo" };
let rows = [];
let ws = null, armed = false;
let layout = 1;                            // 1 | 2 | 4 charts
let panels = [];
let focus = 0;
let tool = "none";

/* ------------------------------------------------------------------ clock */
function clock() {
  const o = { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false };
  $("#clock").textContent =
    `CET ${new Date().toLocaleTimeString("en-GB", { ...o, timeZone: "Europe/Stockholm" })}` +
    `   ET ${new Date().toLocaleTimeString("en-GB", { ...o, timeZone: "America/New_York" })}`;
}
setInterval(clock, 1000); clock();

/* ------------------------------------------------------------ chart panels */
function makePanel(idx) {
  const wrap = document.createElement("div");
  wrap.className = "cpanel";
  wrap.innerHTML =
    `<div class="cphead"><span class="cpsym">—</span><span class="cpmeta meta"></span>
       <span class="spacer"></span><span class="cpidx">${idx + 1}</span></div>
     <div class="cpchart"><canvas class="cpdraw"></canvas></div>
     <div class="cppanes"></div>`;
  $("#grid").appendChild(wrap);

  const host = wrap.querySelector(".cpchart");
  const chart = LightweightCharts.createChart(host, {
    layout: { background: { color: "#0b0e11" }, textColor: "#7b8794", fontSize: 11 },
    grid: { vertLines: { color: "#151a20" }, horzLines: { color: "#151a20" } },
    rightPriceScale: { borderColor: "#1e242c" },
    timeScale: { borderColor: "#1e242c", timeVisible: true },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  });
  const series = chart.addCandlestickSeries({
    upColor: "#26a69a", downColor: "#ef5350", borderUpColor: "#26a69a",
    borderDownColor: "#ef5350", wickUpColor: "#26a69a", wickDownColor: "#ef5350",
  });

  const p = { idx, wrap, host, chart, series, symbol: null, overlays: [],
              priceLines: [], subs: {}, shapes: [], pending: null,
              canvas: wrap.querySelector(".cpdraw") };

  new ResizeObserver(() => {
    chart.applyOptions({ width: host.clientWidth, height: host.clientHeight });
    redraw(p);
  }).observe(host);

  chart.timeScale().subscribeVisibleLogicalRangeChange((r) => {
    Object.values(p.subs).forEach((s) => {
      try { s.chart.timeScale().setVisibleLogicalRange(r); } catch (e) {}
    });
    redraw(p);
  });

  wrap.addEventListener("mousedown", () => setFocus(idx), true);
  initDraw(p);
  return p;
}

function setLayout(n) {
  const keep = panels.map((p) => p.symbol);
  panels.forEach((p) => { try { p.chart.remove(); } catch (e) {} p.wrap.remove(); });
  layout = n; panels = [];
  $("#grid").innerHTML = "";
  $("#grid").className = `grid g${n}`;
  for (let i = 0; i < n; i++) panels.push(makePanel(i));
  setFocus(0);
  panels.forEach((p, i) => {
    const sym = keep[i] || keep[0] || (rows[i] && rows[i].symbol) || (rows[0] && rows[0].symbol);
    if (sym) loadPanel(p, sym);
  });
  syncWs();
}

function setFocus(i) {
  focus = i;
  panels.forEach((p, k) => p.wrap.classList.toggle("focus", k === i));
  const p = panels[i];
  if (p && p.symbol) loadStrategies(p.symbol);
}

/* --------------------------------------------------------------- watchlist */
async function loadMarkets() {
  const { markets } = await (await fetch("/api/markets")).json();
  $("#markets").innerHTML = markets
    .map((m) => `<button data-m="${m}" class="${m === market ? "on" : ""}">${m}</button>`).join("");
  $("#markets").querySelectorAll("button").forEach((b) =>
    b.onclick = () => {
      market = b.dataset.m;
      loadMarkets();
      loadWatchlist();
      // The wire is regional, so a market switch invalidates what is on screen.
      if ($("#tab-news").classList.contains("on")) loadNews();
      else $("#news").innerHTML = "";
    });
}

async function loadWatchlist() {
  $("#wl-body").innerHTML = `<tr><td colspan="10" class="loading">scanning ${market}…</td></tr>`;
  const t0 = performance.now();
  const d = await (await fetch(`/api/watchlist/${market}`)).json();
  if (d.error) { $("#wl-body").innerHTML = `<tr><td colspan="10" class="loading">${d.error}</td></tr>`; return; }
  rows = d.rows;
  const stale = rows.filter((r) => r.levels_stale).length;
  $("#wl-meta").innerHTML = `${d.count} names · ${((performance.now() - t0) / 1000).toFixed(1)}s`
    + (stale ? ` · <span class="warn">${stale} STALE LEVELS</span>` : "");

  $("#wl-body").innerHTML = rows.map((r) => {
    const c = r.change_pct === null ? "dim" : r.change_pct >= 0 ? "up" : "dn";
    const coil = r.cpr_pctile !== null && r.cpr_pctile <= 35 ? "coil" : "dim";
    return `<tr data-s="${r.symbol}">
      <td class="sym">${r.symbol}</td><td class="r">${fmt(r.price)}</td>
      <td class="r ${c}">${r.change_pct === null ? "—" : (r.change_pct >= 0 ? "+" : "") + r.change_pct.toFixed(2)}</td>
      <td class="r">${r.score.toFixed(3)}</td>
      <td class="r ${coil}">${r.cpr_pctile === null ? "—" : r.cpr_pctile + "%"}</td>
      <td class="r ${r.to_pdh >= 0 ? "dim" : "up"}">${r.to_pdh >= 0 ? "+" : ""}${r.to_pdh.toFixed(2)}</td>
      <td class="r ${r.to_pdl <= 0 ? "dim" : "dn"}">${r.to_pdl >= 0 ? "+" : ""}${r.to_pdl.toFixed(2)}</td>
      <td class="r dim">${fmt(r.atr_pct)}</td>
      <td class="r dim">${r.max_lev ?? "—"}x</td>
      <td>${badge(r.levels_stale ? "stale" : r.freshness)}</td></tr>`;
  }).join("");

  $("#wl-body").querySelectorAll("tr[data-s]").forEach((tr) =>
    tr.onclick = () => { panels[focus].ko = null; loadPanel(panels[focus], tr.dataset.s); });

  if (panels.length && !panels[0].symbol && rows.length)
    panels.forEach((p, i) => loadPanel(p, (rows[i] || rows[0]).symbol));
  syncWs();
}

/* ----------------------------------------------------------- chart loading */
async function loadPanel(p, sym) {
  if (!p || !sym) return;
  // "AV:<orderbookId>" charts the Avanza instrument ITSELF rather than its
  // underlying. Routed through the same loader so the layout, refresh timer
  // and drawing tools all keep working without a parallel code path.
  if (String(sym).startsWith("AV:")) return loadAvanzaPanel(p, String(sym).slice(3));
  p.symbol = sym;
  p.wrap.querySelector(".cpsym").textContent = sym;
  markSelectedRows();

  const ind = [...active].join(",");
  const d = await (await fetch(
    `/api/chart/${encodeURIComponent(sym)}?interval=${tf.i}&lookback=${tf.l}&ind=${ind}`)).json();
  if (d.error) { p.wrap.querySelector(".cpmeta").innerHTML = `<span class="warn">${d.error}</span>`; return; }

  p.series.setData(d.candles);

  p.overlays.forEach((s) => { try { p.chart.removeSeries(s); } catch (e) {} });
  p.overlays = [];
  Object.values(p.subs).forEach((s) => { try { s.chart.remove(); } catch (e) {} s.div.remove(); });
  p.subs = {};
  p.wrap.querySelector(".cppanes").innerHTML = "";

  let markers = [];
  (d.series || []).forEach((sr) => {
    if (sr.kind === "markers") { markers = markers.concat(sr.data); return; }
    const isOverlay = sr.pane === "overlay";
    const target = isOverlay ? null : (p.subs[sr.pane] || makeSub(p, sr.pane));
    const ch = isOverlay ? p.chart : target.chart;
    const s2 = sr.kind === "histogram"
      ? ch.addHistogramSeries({ title: sr.title, priceScaleId: isOverlay ? "" : "right" })
      : ch.addLineSeries({ color: sr.color, lineWidth: sr.lineWidth || 1, title: sr.title,
                           priceLineVisible: false, lastValueVisible: false });
    s2.setData(sr.data);
    if (isOverlay) p.overlays.push(s2);
  });
  p.series.setMarkers(markers);

  p.priceLines.forEach((l) => { try { p.series.removePriceLine(l); } catch (e) {} });
  p.priceLines = d.levels.map((l) => p.series.createPriceLine({
    price: l.price, color: l.color, lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: l.label }));

  // Re-draw the knockout barrier. It is pinned to the panel rather than to the
  // response, so the 60s auto-refresh cannot quietly erase the one line that
  // decides whether the position survives.
  if (p.ko && p.ko.symbol === sym) {
    p.priceLines.push(p.series.createPriceLine({
      price: p.ko.price, color: p.ko.near ? "#ef5350" : "#f0a020", lineWidth: 2,
      lineStyle: LightweightCharts.LineStyle.Solid, axisLabelVisible: true,
      title: p.ko.title }));
  }

  const q = d.quote;
  p.wrap.querySelector(".cpmeta").innerHTML =
    (q ? `${fmt(q.price)} ${badge(q.freshness)} <span class="dim">${q.age_min}m</span> · ` : "")
    + `<span class="dim">lv ${d.levels_from}</span> `
    + (d.levels_stale ? `<span class="warn">STALE</span>` : "")
    + (d.cpr_verdict ? ` · <span class="coil">${d.cpr_verdict}</span>` : "");

  if (p.idx === focus) {
    $("#levels").innerHTML = d.levels.map((l) =>
      `<span class="lv" style="border-color:${l.color}44"><b>${l.label}</b>${fmt(l.price)}</span>`).join("");
    const cnt = $("#indcnt");
    if (cnt) cnt.textContent = `${active.size} indicators · ${(d.series || []).length} series`;
    loadStrategies(sym);
  }
  redraw(p);
  syncWs();
}

async function loadAvanzaPanel(p, oid) {
  p.symbol = "AV:" + oid;
  const head = p.wrap.querySelector(".cpsym");
  head.textContent = "loading…";
  let d;
  try {
    const res = await fetch(`/api/avanza/chart/${encodeURIComponent(oid)}`);
    const txt = await res.text();
    try { d = JSON.parse(txt); } catch { throw new Error(`HTTP ${res.status}`); }
  } catch (e) {
    head.textContent = oid;
    p.wrap.querySelector(".cpmeta").innerHTML = `<span class="warn">${e.message}</span>`;
    return;
  }
  if (d.error) {
    head.textContent = oid;
    p.wrap.querySelector(".cpmeta").innerHTML = `<span class="warn">${d.error}</span>`;
    return;
  }

  head.textContent = d.name;
  p.series.setData(d.candles);
  p.series.setMarkers([]);

  // Indicators are computed server-side from yfinance and have no meaning on an
  // Avanza orderbook id, so the panel is cleared rather than left showing the
  // previous symbol's overlays next to a different instrument's prices.
  p.overlays.forEach((x) => { try { p.chart.removeSeries(x); } catch (e) {} });
  p.overlays = [];
  Object.values(p.subs).forEach((x) => { try { x.chart.remove(); } catch (e) {} x.div.remove(); });
  p.subs = {};
  p.wrap.querySelector(".cppanes").innerHTML = "";
  p.priceLines.forEach((l) => { try { p.series.removePriceLine(l); } catch (e) {} });
  p.priceLines = [];

  if (d.barrier != null) {
    p.priceLines.push(p.series.createPriceLine({
      price: d.barrier, color: "#ef5350", lineWidth: 2,
      lineStyle: LightweightCharts.LineStyle.Solid,
      axisLabelVisible: true, title: "KNOCKOUT" }));
  }
  p.chart.timeScale().fitContent();

  const last = d.candles[d.candles.length - 1].close;
  const first = d.candles[0].close;
  p.wrap.querySelector(".cpmeta").innerHTML =
    `${fmt(last)} ${d.currency} ${badge(d.is_realtime ? "realtime" : "delayed")} `
    + `<span class="dim">${d.candles.length} bars · `
    + `${((last / first - 1) * 100).toFixed(1)}% over the window</span>`
    + (d.leverage != null ? ` <span class="coil">${d.leverage}x</span>` : "")
    + (d.underlying ? ` <span class="dim">on ${d.underlying}</span>` : "");

  if (p.idx === focus) {
    $("#levels").innerHTML =
      `<span class="lv"><b>LAST</b>${fmt(last)} ${d.currency}</span>`
      + (d.barrier != null ? `<span class="lv"><b>KO</b>${fmt(d.barrier)}</span>` : "")
      + (d.underlying ? `<span class="lv"><b>UNDERLYING</b>${d.underlying}</span>` : "");
  }
  redraw(p);
}

function makeSub(p, id) {
  const h = layout === 1 ? 100 : 70;
  const div = document.createElement("div");
  div.className = "pane"; div.style.height = h + "px";
  div.innerHTML = `<span class="lbl">${id.toUpperCase()}</span>`;
  p.wrap.querySelector(".cppanes").appendChild(div);
  const ch = LightweightCharts.createChart(div, {
    height: h, width: div.clientWidth,
    layout: { background: { color: "#0b0e11" }, textColor: "#7b8794", fontSize: 10 },
    grid: { vertLines: { color: "#12161b" }, horzLines: { color: "#12161b" } },
    rightPriceScale: { borderColor: "#1e242c" },
    timeScale: { borderColor: "#1e242c", visible: false },
  });
  new ResizeObserver(() => ch.applyOptions({ width: div.clientWidth })).observe(div);
  p.subs[id] = { chart: ch, div };
  return p.subs[id];
}

function markSelectedRows() {
  const syms = panels.map((p) => p.symbol);
  document.querySelectorAll("#wl-body tr[data-s]").forEach((tr) =>
    tr.classList.toggle("sel", syms.includes(tr.dataset.s)));
}

/* -------------------------------------------------------------- strategies */
async function loadStrategies(sym) {
  $("#tab-meta").textContent = "running…";
  const d = await (await fetch(`/api/strategies/${encodeURIComponent(sym)}?interval=${tf.i}`)).json();
  if (d.error) { $("#strat").innerHTML = ""; $("#tab-meta").textContent = d.error; return; }
  $("#tab-meta").innerHTML = `<span class="dim">${sym} · </span>` + (d.fired
    ? `<span class="coil">${d.fired} of ${d.total} firing</span>`
    : `<span class="dim">0 of ${d.total} firing</span>`);
  $("#strat").innerHTML = "<table>" + d.signals.map((s) =>
    `<tr class="${s.fired ? "fired" : ""}"><td>${s.name}</td>
     <td class="side-${s.side}">${s.side}</td><td class="dim">${s.reason}</td></tr>`).join("") + "</table>";
}

/* -------------------------------------------------------------- indicators */
async function loadCatalog() {
  const { indicators } = await (await fetch("/api/indicators")).json();
  $("#indbar").innerHTML = indicators.map((i) =>
    `<button data-id="${i.id}" class="${active.has(i.id) ? "on" : ""}">${i.label}</button>`
  ).join("") + `<span class="cnt" id="indcnt"></span>`;
  $("#indbar").querySelectorAll("button").forEach((b) =>
    b.onclick = () => {
      active.has(b.dataset.id) ? active.delete(b.dataset.id) : active.add(b.dataset.id);
      b.classList.toggle("on");
      panels.forEach((p) => p.symbol && loadPanel(p, p.symbol));
    });
}

/* ----------------------------------------------------------------- drawing */
function redraw(p) {
  const c = p.canvas; if (!c) return;
  const w = p.host.clientWidth, h = p.host.clientHeight;
  if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
  const g = c.getContext("2d"); g.clearRect(0, 0, w, h);
  for (const s of p.shapes) {
    if (s.type === "hline") {
      const y = p.series.priceToCoordinate(s.p1); if (y === null) continue;
      g.strokeStyle = "#f0a020"; g.lineWidth = 1; g.setLineDash([4, 3]);
      g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke(); g.setLineDash([]);
      g.fillStyle = "#f0a020"; g.font = "10px monospace"; g.fillText(s.p1.toFixed(2), 4, y - 3);
      continue;
    }
    const ax = p.chart.timeScale().timeToCoordinate(s.t1), ay = p.series.priceToCoordinate(s.p1);
    const bx = p.chart.timeScale().timeToCoordinate(s.t2), by = p.series.priceToCoordinate(s.p2);
    if (ax === null || bx === null || ay === null || by === null) continue;
    if (s.type === "trend") {
      g.strokeStyle = "#4fd6c0"; g.lineWidth = 1.5;
      g.beginPath(); g.moveTo(ax, ay); g.lineTo(bx, by); g.stroke();
    } else {
      g.fillStyle = "#f0a02022"; g.strokeStyle = "#f0a02088"; g.lineWidth = 1;
      g.fillRect(ax, ay, bx - ax, by - ay); g.strokeRect(ax, ay, bx - ax, by - ay);
    }
  }
}

function initDraw(p) {
  const c = p.canvas;
  c.onmousedown = (e) => {
    if (tool === "none") return;
    const r = c.getBoundingClientRect();
    const t = p.chart.timeScale().coordinateToTime(e.clientX - r.left);
    const pr = p.series.coordinateToPrice(e.clientY - r.top);
    if (t === null || pr === null) return;
    if (tool === "hline") { p.shapes.push({ type: "hline", p1: pr }); redraw(p); return; }
    p.pending = { type: tool, t1: t, p1: pr };
  };
  c.onmouseup = (e) => {
    if (!p.pending) return;
    const r = c.getBoundingClientRect();
    const t = p.chart.timeScale().coordinateToTime(e.clientX - r.left);
    const pr = p.series.coordinateToPrice(e.clientY - r.top);
    if (t !== null && pr !== null) { p.pending.t2 = t; p.pending.p2 = pr; p.shapes.push(p.pending); }
    p.pending = null; redraw(p);
  };
}

/* ------------------------------------------------------------- live socket */
function syncWs() {
  if (ws && ws.readyState === 1) {
    // Avanza orderbook ids are not Yahoo symbols; subscribing to one would just
    // add a permanently silent entry to the stream's subscription set.
    const syms = [...new Set([...rows.map((r) => r.symbol), ...panels.map((p) => p.symbol)])]
      .filter((x) => x && !String(x).startsWith("AV:"));
    if (syms.length) ws.send(JSON.stringify({ symbols: syms }));
  }
}

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => { $("#live").className = "live on"; $("#live").textContent = "LIVE"; syncWs(); };
  ws.onclose = () => { $("#live").className = "live off"; $("#live").textContent = "OFFLINE"; setTimeout(connect, 3000); };
  ws.onmessage = (e) => {
    const d = JSON.parse(e.data);
    (d.quotes || []).forEach(applyQuote);
    if (d.stream) {
      const st = d.stream;
      $("#live").textContent = st.ticking ? `LIVE ${st.ticking}` : "LIVE";
      $("#live").title = `streaming ${st.ticking}/${st.subscribed} · `
        + (st.connected ? "socket up" : "socket down") + ` · reconnects ${st.reconnects}`;
    }
    (d.alerts || []).forEach((a) => console.log(`ALERT ${a.symbol} ${a.direction} ${a.label} ${a.level}`));
  };
}

function applyQuote(q) {
  const tr = document.querySelector(`#wl-body tr[data-s="${CSS.escape(q.symbol)}"]`);
  if (tr) {
    const td = tr.children;
    const prev = parseFloat(td[1].textContent.replace(/,/g, ""));
    td[1].textContent = fmt(q.price);
    if (q.change_pct !== null) {
      td[2].textContent = (q.change_pct >= 0 ? "+" : "") + q.change_pct.toFixed(2);
      td[2].className = "r " + (q.change_pct >= 0 ? "up" : "dn");
    }
    td[9].innerHTML = badge(q.freshness);
    if (!Number.isNaN(prev) && Math.abs(q.price - prev) > 1e-9) {
      tr.classList.remove("flash"); void tr.offsetWidth; tr.classList.add("flash");
    }
  }
}

/* ------------------------------------------------------------------ toolbar */
$("#tf").querySelectorAll("button").forEach((b) => b.onclick = () => {
  $("#tf").querySelectorAll("button").forEach((x) => x.classList.remove("on"));
  b.classList.add("on");
  tf = { i: b.dataset.i, l: b.dataset.l };
  panels.forEach((p) => p.symbol && loadPanel(p, p.symbol));
});

$("#draw").querySelectorAll("button").forEach((b) => b.onclick = () => {
  const t = b.dataset.t;
  if (t === "clear") { panels[focus].shapes = []; redraw(panels[focus]); return; }
  tool = t;
  $("#draw").querySelectorAll("button").forEach((x) => x.classList.remove("on"));
  b.classList.add("on");
  panels.forEach((p) => p.canvas.classList.toggle("armed", tool !== "none"));
});

$("#layout").querySelectorAll("button").forEach((b) => b.onclick = () => {
  $("#layout").querySelectorAll("button").forEach((x) => x.classList.remove("on"));
  b.classList.add("on");
  setLayout(parseInt(b.dataset.n, 10));
});

$("#arm").onclick = async () => {
  const p = panels[focus]; if (!p || !p.symbol) return;
  if (armed) {
    await fetch("/api/alerts", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ watches: [] }) });
    armed = false; $("#arm").classList.remove("on"); $("#arm").textContent = "ARM ALERTS"; return;
  }
  const d = await (await fetch(`/api/chart/${encodeURIComponent(p.symbol)}`)).json();
  const px = d.quote ? d.quote.price : null;
  const watches = d.levels.filter((l) => ["PDH", "PDL", "R1", "S1"].includes(l.label))
    .map((l) => ({ symbol: p.symbol, label: l.label, price: l.price,
                   direction: px !== null && l.price > px ? "above" : "below" }));
  const r = await (await fetch("/api/alerts", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ watches }) })).json();
  armed = true; $("#arm").classList.add("on"); $("#arm").textContent = `ARMED ${r.count}`;
};

/* ------------------------------------------------------------------ avanza */
let avTimer, avRows = [];

async function avSearch(q) {
  $("#av-meta").textContent = "searching…";
  // No spread cap. The sort already puts the tradeable ones first, and seeing
  // that the same underlying also quotes 5,000% wide is information.
  const d = await (await fetch(`/api/avanza/find?q=${encodeURIComponent(q)}`)).json();
  avRows = d.rows || [];
  const dead = avRows.filter((r) => r.spread_known && r.spread_pct > 5).length;
  const unpriced = avRows.filter((r) => !r.spread_known).length;
  $("#av-meta").innerHTML = `${d.count} tradeable · cheapest first`
    + (dead ? ` · <span class="warn">${dead} untradeable-wide</span>` : "")
    + (unpriced ? ` · <span class="dim">${unpriced} unpriced (market closed)</span>` : "");
  $("#av").innerHTML = "<table>" + avRows.map((r, i) => {
    // No spread outside market hours. Show the row, but never render a missing
    // spread as a number — an unknown cost must not look like a cheap one.
    const sp = !r.spread_known ? `<span class="dim">—</span>`
      : `<span class="${r.spread_pct < 0.5 ? "tight" : r.spread_pct < 1.5 ? "" : "wide"}">${
          r.spread_pct > 1000 ? r.spread_pct.toExponential(1) : r.spread_pct.toFixed(3)}%</span>`;
    return `<tr data-i="${i}" data-oid="${r.orderbook_id}">
      <td>${r.name}</td><td class="r dim">${r.orderbook_id}</td>
      <td class="r">${fmt(r.last, 3)}</td>
      <td class="r">${sp}</td></tr>`;
  }).join("") + "</table>";
  $("#av").querySelectorAll("tr[data-oid]").forEach((tr) =>
    tr.onclick = () => avOpen(tr.dataset.oid, tr));
  // Cheapest line is the one you would actually trade — open it immediately.
  const first = $("#av").querySelector("tr[data-oid]");
  if (first) avOpen(first.dataset.oid, first);
}

async function avOpen(oid, tr) {
  $("#av").querySelectorAll("tr").forEach((x) => x.classList.remove("selav"));
  if (tr) tr.classList.add("selav");
  const box = $("#av-detail");
  box.className = "avdetail on";
  box.innerHTML = `<span class="dim">loading ${oid}…</span>`;

  // A non-JSON error body (a 500 renders as plain text) made .json() throw,
  // which aborted this function and left "loading…" on screen forever. An
  // error must always replace the loading state, never outlive it.
  let d;
  try {
    const res = await fetch(`/api/avanza/instrument/${oid}`);
    const txt = await res.text();
    try { d = JSON.parse(txt); }
    catch { throw new Error(`HTTP ${res.status}: ${txt.slice(0, 120)}`); }
  } catch (e) {
    box.innerHTML = `<span class="warn">could not open ${oid} — ${e.message}</span>`;
    return;
  }
  if (d.error) { box.innerHTML = `<span class="warn">${d.error}</span>`; return; }

  // 3.5 ATRs is the survivability threshold behind the leverage rule; inside
  // that, ordinary noise can knock the position out before the thesis plays.
  const near = d.atrs_to_barrier !== null && d.atrs_to_barrier < 3.5;
  const kv = [];
  if (d.sub_type) kv.push(["type", d.sub_type.replace("_", " ")]);
  if (d.direction) kv.push(["dir", d.direction]);
  if (d.leverage != null) kv.push(["lev", d.leverage + "x"]);
  kv.push(["spread", d.spread_pct == null ? "unavailable (market closed)"
                                           : d.spread_pct.toFixed(3) + "%"]);
  kv.push(["quote", d.is_realtime ? "REALTIME" : "delayed"]);
  if (d.bid != null) kv.push(["bid/ask", `${fmt(d.bid, 3)} / ${fmt(d.ask, 3)}`]);

  // ONE compact line. The previous version explained the certificate-vs-
  // underlying charting decision in full paragraphs here, which ate the dock
  // height and pushed the instrument LIST off screen with nothing to scroll.
  // The list is the thing being used; the explanation belongs in the docs.
  box.innerHTML =
    `<span class="nm">${d.name}</span>`
    + kv.map(([k, v]) => `<span class="kv">${k}<b>${v}</b></span>`).join("")
    + (d.barrier != null
        ? `<span class="kv ${near ? "danger" : "ok"}">KO<b>${fmt(d.barrier)}`
          + (d.barrier_distance_pct !== null
              ? ` · ${d.atrs_to_barrier ?? "?"} ATR` : "") + `</b></span>`
        : `<span class="kv">KO<b>none</b></span>`)
    + (d.underlying
        ? `<span class="kv">chart<b>${d.underlying}</b></span>`
        : `<span class="kv warn">underlying ?</span>`)
    + (near ? ` <span class="warn">barrier inside 3.5 ATR</span>` : "")
    + (d.underlying
        ? ` <button class="newsbtn" id="av-under">chart ${d.underlying} instead</button>` : "");
  const ub = $("#av-under");
  if (ub) ub.onclick = () => {
    const p = panels[focus];
    if (!p) return;
    p.ko = d.barrier != null
      ? { symbol: d.underlying, price: d.barrier, near, title: `KO ${d.name.slice(0, 18)}` }
      : null;
    loadPanel(p, d.underlying);
  };

  // Chart the INSTRUMENT, which is what was clicked and what would be bought.
  // Its own history is only usable because the session is authenticated.
  if (panels[focus]) {
    panels[focus].ko = null;
    await loadPanel(panels[focus], "AV:" + oid);
  }
}

$("#avq").oninput = (e) => {
  clearTimeout(avTimer);
  const q = e.target.value.trim();
  if (q.length < 3) {
    $("#av").innerHTML = ""; $("#av-meta").textContent = "";
    $("#av-detail").className = "avdetail"; $("#av-detail").innerHTML = ""; return;
  }
  avTimer = setTimeout(() => avSearch(q), 400);
};

/* ---------------------------------------------------------------- ask AI */
function mdLite(s) {
  return s
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/^### (.*)$/gm, "<h3>$1</h3>")
    .replace(/^## (.*)$/gm, "<h3>$1</h3>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}

async function aiAsk() {
  const q = $("#aiq").value.trim();
  if (!q) return;
  // Ask about what is actually on screen: the open charts, else the watchlist.
  const syms = [...new Set(panels.map((p) => p.symbol).filter(Boolean))];
  const use = syms.length ? syms : rows.slice(0, 5).map((r) => r.symbol);
  $("#aisend").disabled = true;
  $("#aisend").textContent = "THINKING…";
  const t0 = performance.now();

  // A live counter, because the honest answer is that this takes about a
  // minute: ~5s to compute the context and ~60s for claude -p to think. A
  // motionless "running…" for that long reads as broken, which is exactly how
  // this got reported as not working when nothing was actually failing.
  $("#ai-out").innerHTML =
    `<span class="dim">Gathering context for ${use.join(", ")} — levels, strategies,
     quotes and headlines — then asking claude -p.<br/>
     Typically ~60s. The answer replaces this text when it lands.</span>`;
  if (aiTimer) clearInterval(aiTimer);
  aiTimer = setInterval(() => {
    const s = (performance.now() - t0) / 1000;
    $("#ai-meta").innerHTML = `<span class="coil">${s.toFixed(0)}s</span> `
      + `<span class="dim">· ${s < 6 ? "building context" : "claude is thinking"}`
      + ` · ${use.length} symbol${use.length > 1 ? "s" : ""}</span>`;
  }, 250);
  try {
    const d = await (await fetch("/api/ai/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, symbols: use, market }),
    })).json();
    clearInterval(aiTimer); aiTimer = null;
    const secs = ((performance.now() - t0) / 1000).toFixed(1);
    if (d.error) {
      $("#ai-out").innerHTML = `<span class="warn">${d.error}</span>`
        + (d.detail ? `<div class="dim">${d.detail}</div>` : "");
      $("#ai-meta").textContent = `failed in ${secs}s`;
    } else {
      $("#ai-out").innerHTML = mdLite(d.answer);
      $("#ai-meta").innerHTML = `<span class="dim">${secs}s · context: ${
        (d.symbols || []).join(", ") || "<span class='warn'>EMPTY</span>"}</span>`;
    }
  } catch (e) {
    clearInterval(aiTimer); aiTimer = null;
    $("#ai-out").innerHTML = `<span class="warn">${e}</span>`;
    $("#ai-meta").textContent = "";
  }
  clearInterval(aiTimer); aiTimer = null;
  $("#aisend").disabled = false;
  $("#aisend").textContent = "ASK";
}
$("#aisend").onclick = aiAsk;
$("#aiq").onkeydown = (e) => { if (e.key === "Enter") aiAsk(); };

/* -------------------------------------------------------------------- news */
let newsMode = "market", newsTimer = null;
let aiTimer = null;

const esc = (t) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
                    .replace(/"/g, "&quot;");

function age(m) {
  if (m === null || m === undefined) return "—";
  if (m < 60) return m + "m";
  if (m < 1440) return Math.floor(m / 60) + "h";
  return Math.floor(m / 1440) + "d";
}

function newsRows(items) {
  if (!items.length) return `<div class="loading">nothing on the wire</div>`;
  return items.map((n) => {
    // Under 30 minutes is the window where a headline still has edge left.
    const fresh = n.age_min !== null && n.age_min <= 30 ? "fresh" : "";
    return `<div class="nrow">
      <span class="nage ${fresh}">${age(n.age_min)}</span>
      ${n.score >= 3 ? '<span class="nhot">HOT</span>' : ""}
      <a class="ntitle" href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a>
      <span class="nsrc">${esc(n.source)}</span></div>`;
  }).join("");
}

async function loadNews(mode) {
  if (mode) newsMode = mode;
  const box = $("#news");
  if (newsMode === "market") {
    $("#news-meta").textContent = "fetching wire…";
    const d = await (await fetch(`/api/news/market?limit=30&market=${market}`)).json();
    box.innerHTML = newsRows(d.items || []);
    $("#news-meta").innerHTML = `<span class="dim">${market.toUpperCase()} · ${
      (d.items || []).length} stories · ${d.feeds} feed${d.feeds > 1 ? "s" : ""}</span>`;
  } else if (newsMode === "sym") {
    const sym = panels[focus] && panels[focus].symbol;
    if (!sym) { box.innerHTML = `<div class="loading">no symbol charted</div>`; return; }
    $("#news-meta").textContent = `fetching ${sym}…`;
    const d = await (await fetch(
      `/api/news/ticker/${encodeURIComponent(sym)}?limit=15&market=${market}`)).json();
    box.innerHTML = newsRows(d.items || []);
    $("#news-meta").innerHTML = `<span class="dim">${sym} · ${(d.items || []).length} stories</span>`;
  }
}

async function runBot() {
  const btn = $("#news-bot");
  btn.disabled = true;
  newsMode = "bot";
  $("#news").innerHTML = `<div class="loading">scanning ${market} for unusual moves,
    then pulling the headlines next to them…</div>`;
  $("#news-meta").textContent = "scanning…";
  try {
    const d = await (await fetch("/api/news/bot/scan", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ market }),
    })).json();
    if (d.error) { $("#news").innerHTML = `<div class="loading warn">${d.error}</div>`; return; }
    const hits = d.hits || [];
    $("#news-meta").innerHTML = `<span class="dim">${d.scanned} scanned · ${
      hits.length} unusual movers</span>`;
    if (!hits.length) {
      $("#news").innerHTML = `<div class="loading">nothing moved more than 1 ATR.
        That is the honest answer on most days.</div>`;
      return;
    }
    $("#news").innerHTML = hits.map((h) => {
      const c = h.change_pct >= 0 ? "up" : "dn";
      return `<div class="bhit">
        <span class="bsym">${h.symbol}</span>
        <span class="bmove ${c}">${h.change_pct >= 0 ? "+" : ""}${h.change_pct.toFixed(2)}%</span>
        <span class="batr">${h.move_atr >= 0 ? "+" : ""}${h.move_atr} ATR</span>
        ${h.explained ? "" : `<span class="bunexp">— no news found; move is unexplained</span>`}
        <div class="bnews">${h.news.length ? newsRows(h.news.slice(0, 3)) : ""}</div></div>`;
    }).join("");
  } catch (e) {
    $("#news").innerHTML = `<div class="loading warn">${e}</div>`;
  }
  btn.disabled = false;
}

$("#news-mkt").onclick = () => {
  $("#tab-news").querySelectorAll(".newsbtn").forEach((b) => b.classList.remove("on"));
  $("#news-mkt").classList.add("on"); loadNews("market");
};
$("#news-sym").onclick = () => {
  $("#tab-news").querySelectorAll(".newsbtn").forEach((b) => b.classList.remove("on"));
  $("#news-sym").classList.add("on"); loadNews("sym");
};
$("#news-bot").onclick = runBot;

// The wire only refreshes while its tab is visible. A background poll of six
// feeds nobody is reading is exactly the kind of waste that got the price feed
// rate-limited.
setInterval(() => {
  if (!$("#news-auto").checked) return;
  if (!$("#tab-news").classList.contains("on")) return;
  if (newsMode === "market" || newsMode === "sym") loadNews();
}, 60000);

/* -------------------------------------------------------------------- tabs */
$(".panel-head.tabs").querySelectorAll("button").forEach((b) => b.onclick = () => {
  $(".panel-head.tabs").querySelectorAll("button").forEach((x) => x.classList.remove("on"));
  b.classList.add("on");
  document.querySelectorAll(".tabpane").forEach((p) => p.classList.remove("on"));
  $(`#tab-${b.dataset.tab}`).classList.add("on");
  if (b.dataset.tab === "av") $("#avq").focus();
  if (b.dataset.tab === "ai") $("#aiq").focus();
  if (b.dataset.tab === "news" && $("#news").children.length <= 1) loadNews("market");
});

/* --------------------------------------------------------------- splitters */
function relayout() {
  panels.forEach((p) => {
    p.chart.applyOptions({ width: p.host.clientWidth, height: p.host.clientHeight });
    Object.values(p.subs).forEach((s) => s.chart.applyOptions({ width: s.div.clientWidth }));
    redraw(p);
  });
}

// Clamp the watchlist so the right pane can never be squeezed out of existence.
// This is not defensive padding — an unclamped restore is exactly how the whole
// right side (charts, Avanza, AI, news) vanished off-screen and looked like
// "Avanza is broken": #right has min-width:0, so it collapses silently rather
// than pushing back. Applied on restore AND on window resize, since shrinking
// the window is the other way to reach the same state.
const MIN_RIGHT = 420;
function clampSplit() {
  const left = $("#left");
  const max = Math.max(150, window.innerWidth - MIN_RIGHT);
  const w = left.getBoundingClientRect().width;
  if (w > max) { left.style.width = max + "px"; return true; }
  return false;
}

// Watchlist width. Persisted, because re-dragging it every session is exactly
// the kind of small friction that makes a tool go unused.
(function initVSplit() {
  const left = $("#left"), h = $("#vsplit");
  const saved = parseFloat(localStorage.getItem("splitV"));
  if (saved > 0) left.style.width = Math.min(saved, window.innerWidth - MIN_RIGHT) + "px";
  clampSplit();
  h.onmousedown = (e) => {
    e.preventDefault();
    h.classList.add("drag"); document.body.classList.add("resizing");
    const x0 = e.clientX, w0 = left.getBoundingClientRect().width;
    const move = (ev) => {
      const w = Math.max(150, Math.min(window.innerWidth - MIN_RIGHT, w0 + ev.clientX - x0));
      left.style.width = w + "px";
      applyCompact();
      relayout();
    };
    const up = () => {
      h.classList.remove("drag"); document.body.classList.remove("resizing");
      localStorage.setItem("splitV", left.getBoundingClientRect().width);
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      relayout();
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  };
})();

// Chart / dock height.
(function initHSplit() {
  const dock = $("#dock"), h = $("#hsplit");
  const saved = parseFloat(localStorage.getItem("splitH"));
  if (saved > 0) dock.style.height = saved + "px";
  h.onmousedown = (e) => {
    e.preventDefault();
    h.classList.add("drag"); document.body.classList.add("resizing-v");
    const y0 = e.clientY, h0 = dock.getBoundingClientRect().height;
    const move = (ev) => {
      dock.style.height = Math.max(60, Math.min(window.innerHeight - 220, h0 - (ev.clientY - y0))) + "px";
      relayout();
    };
    const up = () => {
      h.classList.remove("drag"); document.body.classList.remove("resizing-v");
      localStorage.setItem("splitH", dock.getBoundingClientRect().height);
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      relayout();
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  };
})();

/* Compact watchlist. Driven by the PANE's width, not the viewport, so it reacts
 * to the drag handle as well as to the window — below ~430px only symbol, price
 * and change survive, which is what you actually scan. */
function applyCompact() {
  const left = $("#left");
  left.classList.toggle("compact", left.getBoundingClientRect().width < 430);
}
new ResizeObserver(applyCompact).observe($("#left"));
window.addEventListener("resize", () => { clampSplit(); applyCompact(); relayout(); });

/* ---------------------------------------------------------------- bootstrap */
setLayout(1);
applyCompact();
loadCatalog();
loadMarkets().then(loadWatchlist);
connect();
setInterval(() => panels.forEach((p) => p.symbol && loadPanel(p, p.symbol)), 60000);
