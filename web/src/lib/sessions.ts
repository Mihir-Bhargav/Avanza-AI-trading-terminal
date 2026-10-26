/**
 * Exchange session state from the regular-hours schedule, in each venue's own
 * time zone. Weekends are closed; exchange holidays are NOT modelled, so the
 * pill reads "Open" on a holiday. Pills are labelled "schedule" for that reason.
 */

export interface Venue {
  code: string;
  name: string;
  tz: string;
  open: [number, number];
  close: [number, number];
}

export const VENUES: Venue[] = [
  { code: "STO", name: "Nasdaq Stockholm", tz: "Europe/Stockholm", open: [9, 0], close: [17, 30] },
  { code: "NYSE", name: "New York Stock Exchange", tz: "America/New_York", open: [9, 30], close: [16, 0] },
  { code: "XETRA", name: "Xetra Frankfurt", tz: "Europe/Berlin", open: [9, 0], close: [17, 30] },
];

function localParts(date: Date, tz: string) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: tz,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return { weekday: get("weekday"), minutes: Number(get("hour")) * 60 + Number(get("minute")) };
}

export function isVenueOpen(v: Venue, now: Date): boolean {
  const { weekday, minutes } = localParts(now, v.tz);
  if (weekday === "Sat" || weekday === "Sun") return false;
  return minutes >= v.open[0] * 60 + v.open[1] && minutes < v.close[0] * 60 + v.close[1];
}

/** "16:02:17 CEST" in the viewer's own time zone. */
export function fmtWallClock(now: Date): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZoneName: "short",
  }).formatToParts(now);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${get("hour")}:${get("minute")}:${get("second")} ${get("timeZoneName")}`.trim();
}
