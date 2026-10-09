// Helpers over a snapshot of the site's events (tools/events.py writes projects/<video>/data/events.json and the
// flyers to public/<video>/flyers/). The shape is the site's data contract (pa-bailar-web docs/DATA.md), trimmed
// to what videos use.

export type Session = { date: string; start_time: string | null; end_time: string | null };
export type Price = { label: string | null; amount_cop: number; condition: string | null };
export type VideoEvent = {
  id: string;
  title: string;
  event_type: string;
  styles: string[];
  organizer: string | null;
  venue: string | null;
  area: string | null;
  date: string;
  end_date?: string | null;
  sessions?: Session[] | null;
  start_time: string | null;
  end_time: string | null;
  prices: Price[];
  account: string;
  /** Added by tools/events.py: the cover flyer, relative to public/<video>/ ("flyers/<file>.webp"), and its ratio. */
  flyer: string | null;
  ratio: number | null;
  /**
   * Added by tools/events.py: the occurrence a video shows, the event's first day inside the snapshot's range and that
   * day's times (a run of days or a workshop series has its own per session). Show these, not date/start_time.
   */
  day: string;
  day_start: string | null;
  day_end: string | null;
};

/** projects/<video>/data/events.json: `import snapshot from "./data/events.json"; const events = snapshot.events as VideoEvent[]`. */
export type EventsSnapshot = { from: string; to: string; styles: string[]; source: string; events: VideoEvent[] };

const DAYS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const day = (iso: string) => new Date(`${iso}T12:00:00Z`);

/** Every day an event is on: its sessions, its run of days (date…end_date), or its one date. */
export function daysOf(e: VideoEvent): string[] {
  if (e.sessions?.length) return e.sessions.map((s) => s.date);
  if (!e.end_date) return [e.date];
  const out: string[] = [];
  for (let d = day(e.date); d <= day(e.end_date); d.setUTCDate(d.getUTCDate() + 1)) out.push(d.toISOString().slice(0, 10));
  return out;
}

/** Events on any day from `from` to `to` (inclusive, YYYY-MM-DD), optionally of some styles ("salsa" matches its variants). */
export function between(events: VideoEvent[], from: string, to: string, styles: string[] = []): VideoEvent[] {
  const wanted = styles.map((s) => s.toLowerCase());
  return events.filter(
    (e) =>
      daysOf(e).some((d) => d >= from && d <= to) &&
      (!wanted.length || e.styles.some((s) => wanted.some((w) => s.startsWith(w)))),
  );
}

/** The weekend (Friday to Sunday) of the week of `today` (YYYY-MM-DD); on a weekend day, that weekend. */
export function weekend(today: string): { from: string; to: string } {
  const d = day(today);
  const dow = d.getUTCDay();
  const toFriday = dow === 0 ? -2 : dow === 6 ? -1 : 5 - dow;
  const fri = new Date(d);
  fri.setUTCDate(d.getUTCDate() + toFriday);
  const sun = new Date(fri);
  sun.setUTCDate(fri.getUTCDate() + 2);
  return { from: fri.toISOString().slice(0, 10), to: sun.toISOString().slice(0, 10) };
}

/** A label that starts a line, with its first letter in capitals: "sábado 10 oct" → "Sábado 10 oct". */
export function capital(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** "sábado 10 oct" (the site's short form). */
export function dateLabel(iso: string, withWeekday = true): string {
  const d = day(iso);
  const text = `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
  return withWeekday ? `${DAYS[d.getUTCDay()]} ${text}` : text;
}

/** A range as the site says it (format.ts spanLabel): "sáb 10", "9–11 oct", "30 oct – 1 nov". */
export function spanLabel(from: string, to: string): string {
  const a = day(from);
  const b = day(to);
  if (from === to) return `${DAYS[a.getUTCDay()].slice(0, 3)} ${a.getUTCDate()}`;
  if (from.slice(0, 7) === to.slice(0, 7)) return `${a.getUTCDate()}–${b.getUTCDate()} ${MONTHS[b.getUTCMonth()]}`;
  return `${a.getUTCDate()} ${MONTHS[a.getUTCMonth()]} – ${b.getUTCDate()} ${MONTHS[b.getUTCMonth()]}`;
}

/** "7:00 p. m." (es-CO). */
export function timeLabel(hhmm: string | null): string | null {
  if (!hhmm) return null;
  const [h, m] = hhmm.split(":").map(Number);
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${h < 12 ? "a. m." : "p. m."}`;
}

const MONEY = new Intl.NumberFormat("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 });

/**
 * The price as the site says it (format.ts priceSummary): the lowest, "Gratis" when it's 0, "Desde $ 20.000" when
 * there are several and the lowest isn't free.
 */
export function priceLabel(prices: Price[]): string | null {
  if (!prices.length) return null;
  const low = Math.min(...prices.map((p) => p.amount_cop));
  const amount = low === 0 ? "Gratis" : MONEY.format(low);
  return prices.length > 1 && low > 0 ? `Desde ${amount}` : amount;
}
