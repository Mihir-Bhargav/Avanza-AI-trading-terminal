/**
 * Series primitive that shades the TTM zones as price bands limited to one
 * session: zone1–zone2 amber, zone3–zone4 blue, from the first to the last
 * candle of the session the zones were computed for. Drawn behind the candles,
 * with a hairline at each zone edge. No text is drawn on the chart: the levels
 * ladder beside it carries the labels.
 */
import type {
  AutoscaleInfo,
  Logical,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  Time,
} from "lightweight-charts";
import type { ZoneWindow } from "./chartUtils";

type Target = Parameters<IPrimitivePaneRenderer["draw"]>[0];

const AMBER_FILL = "rgba(245,166,35,0.13)";
const AMBER_EDGE = "rgba(245,166,35,0.55)";
const BLUE_FILL = "rgba(90,169,255,0.13)";
const BLUE_EDGE = "rgba(90,169,255,0.55)";

interface Rect {
  x0: number;
  x1: number;
  yA: number;
  yB: number;
  fill: string;
  edge: string;
}

class BandRenderer implements IPrimitivePaneRenderer {
  constructor(private readonly rects: Rect[]) {}
  draw() {}
  drawBackground(target: Target) {
    target.useBitmapCoordinateSpace(({ context: ctx, horizontalPixelRatio: hr, verticalPixelRatio: vr }) => {
      for (const r of this.rects) {
        const x = Math.round(r.x0 * hr);
        const w = Math.max(1, Math.round((r.x1 - r.x0) * hr));
        const top = Math.round(Math.min(r.yA, r.yB) * vr);
        const h = Math.max(1, Math.round(Math.abs(r.yB - r.yA) * vr));
        ctx.fillStyle = r.fill;
        ctx.fillRect(x, top, w, h);
        ctx.fillStyle = r.edge;
        const lw = Math.max(1, Math.round(vr));
        ctx.fillRect(x, top, w, lw);
        ctx.fillRect(x, top + h - lw, w, lw);
      }
    });
  }
}

class BandView implements IPrimitivePaneView {
  private rects: Rect[] = [];
  constructor(private readonly source: ZoneBands) {}
  zOrder() {
    return "bottom" as const;
  }
  update() {
    this.rects = this.source.computeRects();
  }
  renderer() {
    return new BandRenderer(this.rects);
  }
}

export class ZoneBands implements ISeriesPrimitive<Time> {
  private params: SeriesAttachedParameter<Time> | null = null;
  private readonly views: BandView[];
  private win: ZoneWindow | null;

  constructor(win: ZoneWindow | null) {
    this.win = win;
    this.views = [new BandView(this)];
  }

  attached(p: SeriesAttachedParameter<Time>) {
    this.params = p;
  }
  detached() {
    this.params = null;
  }
  setWindow(win: ZoneWindow | null) {
    this.win = win;
    this.params?.requestUpdate();
  }
  updateAllViews() {
    this.views.forEach((v) => v.update());
  }
  paneViews() {
    return this.views;
  }
  /** Keep the bands in view when the session they cover is visible. */
  autoscaleInfo(start: Logical, end: Logical): AutoscaleInfo | null {
    const w = this.win;
    if (!w || end < w.from || start > w.to) return null;
    const zs = [w.z1, w.z2, w.z3, w.z4];
    return { priceRange: { minValue: Math.min(...zs), maxValue: Math.max(...zs) } };
  }

  computeRects(): Rect[] {
    const p = this.params;
    const w = this.win;
    if (!p || !w) return [];
    const ts = p.chart.timeScale();
    const spacing = ts.options().barSpacing;
    const a = ts.logicalToCoordinate(w.from as never);
    const b = ts.logicalToCoordinate(w.to as never);
    if (a == null || b == null) return [];
    const x0 = a - spacing / 2;
    const x1 = b + spacing / 2;
    const y = (price: number) => p.series.priceToCoordinate(price);
    const out: Rect[] = [];
    const y1 = y(w.z1);
    const y2 = y(w.z2);
    const y3 = y(w.z3);
    const y4 = y(w.z4);
    if (y1 != null && y2 != null) out.push({ x0, x1, yA: y1, yB: y2, fill: AMBER_FILL, edge: AMBER_EDGE });
    if (y3 != null && y4 != null) out.push({ x0, x1, yA: y3, yB: y4, fill: BLUE_FILL, edge: BLUE_EDGE });
    return out;
  }
}
