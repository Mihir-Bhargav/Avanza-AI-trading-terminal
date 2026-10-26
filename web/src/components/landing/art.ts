/**
 * Deterministic generative artwork for the landing page, ported verbatim from
 * Landing.dc.html (rng = mulberry32). Pure functions: same output on server and
 * client, so the SVG renders at build time with no hydration drift.
 */

export function rng(seed: number): () => number {
  return function () {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface OHLC {
  o: number;
  c: number;
  h: number;
  l: number;
}

function walk(n: number, seed: number, lo: number, last: number, bias: number): OHLC[] {
  const r = rng(seed);
  let v = 0;
  const raw: OHLC[] = [];
  for (let i = 0; i < n; i++) {
    const o = v;
    const c = v + (r() - 0.5 + bias) * 2;
    raw.push({ o, c, h: Math.max(o, c) + r() * 0.8, l: Math.min(o, c) - r() * 0.8 });
    v = c;
  }
  const mn = Math.min(...raw.map((d) => d.l));
  const b = (last - lo) / (raw[n - 1].c - mn);
  const a = lo - b * mn;
  return raw.map((d) => ({ o: a + b * d.o, c: a + b * d.c, h: a + b * d.h, l: a + b * d.l }));
}

export interface RangeChartPaths {
  up: string;
  dn: string;
  wickUp: string;
  wickDn: string;
  ema: string;
  todayX: string;
  bandW: string;
  upperY: string;
  upperH: string;
  lowerY: string;
  lowerH: string;
}

/** Illustrative "range, drawn properly" chart: yesterday + today with zones shaded over today. */
export function chart(W: number, H: number, prevN: number, todayN: number, seedA: number, seedB: number): RangeChartPaths {
  const data = walk(prevN, seedA, 918, 934, -0.02).concat(walk(todayN, seedB, 953, 982, 0.08));
  const pad = 14,
    lo = 908,
    hi = 992,
    n = data.length,
    cw = W / n,
    bw = cw * 0.62;
  const Y = (p: number) => pad + ((hi - p) / (hi - lo)) * (H - 2 * pad);
  const o = { up: "", dn: "", wickUp: "", wickDn: "" };
  const ema: string[] = [];
  const k = 2 / 21;
  let e = data[0].c;
  data.forEach((d, i) => {
    const x = i * cw + cw / 2,
      yo = Y(d.o),
      yc = Y(d.c),
      top = Math.min(yo, yc),
      bh = Math.max(1, Math.abs(yc - yo));
    const wick = "M" + x.toFixed(1) + " " + Y(d.h).toFixed(1) + "V" + Y(d.l).toFixed(1);
    const body =
      "M" + (x - bw / 2).toFixed(1) + " " + top.toFixed(1) + "h" + bw.toFixed(1) + "v" + bh.toFixed(1) + "h" + (-bw).toFixed(1) + "Z";
    if (d.c >= d.o) {
      o.up += body;
      o.wickUp += wick;
    } else {
      o.dn += body;
      o.wickDn += wick;
    }
    e = i === 0 ? d.c : d.c * k + e * (1 - k);
    ema.push((i ? "L" : "M") + x.toFixed(1) + " " + Y(e).toFixed(1));
  });
  return {
    ...o,
    ema: ema.join(""),
    todayX: (prevN * cw).toFixed(1),
    bandW: (W - prevN * cw).toFixed(1),
    upperY: Y(968.01).toFixed(1),
    upperH: (Y(961) - Y(968.01)).toFixed(1),
    lowerY: Y(948.5).toFixed(1),
    lowerH: (Y(942) - Y(948.5)).toFixed(1),
  };
}

export interface HeroArt {
  cool: string;
  amber: string;
  bandX: number;
  bandY: number;
  bandW: number;
  bandH: number;
  edges: string;
  hiLabelY: number;
  loLabelY: number;
  kesY: number;
}

/** Hero line-art: 64 lines converging into the day's range band on the right. */
export function art(): HeroArt {
  const r = rng(97),
    N = 64,
    C = 440;
  let cool = "",
    amber = "";
  for (let i = 0; i < N; i++) {
    const base = 40 + i * (800 / (N - 1)),
      f1 = 0.006 + r() * 0.008,
      f2 = 0.018 + r() * 0.014,
      p1 = r() * 6.28,
      p2 = r() * 6.28;
    let d = "";
    for (let x = 380; x <= 1440; x += 12) {
      const sp = 0.09 + 0.91 / (1 + Math.exp((x - 840) / 85));
      const amp = 4 + 22 * sp;
      const y = C + (base - C) * sp + amp * (0.6 * Math.sin(x * f1 + p1) + 0.4 * Math.sin(x * f2 + p2));
      d += (x === 380 ? "M" : "L") + x + " " + y.toFixed(1);
    }
    if (Math.abs(base - C) < 95) amber += d;
    else cool += d;
  }
  const hi = C - 42,
    lo = C + 42;
  return {
    cool,
    amber,
    bandX: 900,
    bandY: hi,
    bandW: 540,
    bandH: lo - hi,
    edges: "M900 " + hi + "H1440M900 " + lo + "H1440",
    hiLabelY: hi - 10,
    loLabelY: lo + 20,
    kesY: hi - 46,
  };
}

export interface LadderRow {
  name: string;
  price: string;
  swatch: string;
  dist: string;
  current: boolean;
}

/** Levels ladder beside the illustrative chart (sorted by price, distance in ATR). */
export function ladder(): LadderRow[] {
  const last = 982,
    atr = 50.05;
  const rows: [string, number, string, boolean?][] = [
    ["Last", 982.0, "#F5A623", true],
    ["Z1", 968.01, "#F5A623"],
    ["Z2", 961.0, "#F5A623"],
    ["Z4", 948.5, "#5AA9FF"],
    ["PDH", 946.2, "#5C6773"],
    ["Z3", 942.0, "#5AA9FF"],
    ["Pivot", 932.6, "#5C6773"],
    ["PDL", 917.6, "#5C6773"],
  ];
  return rows.map(([name, price, swatch, current]) => ({
    name,
    price: price.toFixed(2),
    swatch,
    current: !!current,
    dist: current ? "now" : "−" + Math.abs((price - last) / atr).toFixed(2) + " ATR",
  }));
}
