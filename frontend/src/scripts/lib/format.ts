// Spanish (Colombia) display formatting.

import type { DanceEvent, EventType, MediaType } from "../types";
import { addDays, daysBetween, parseIsoDate, todayIso } from "./dates";

const LOCALE = "es-CO";

const TYPE_LABELS: Record<EventType, string> = {
  social: "Social",
  workshop: "Taller",
  concert: "Concierto",
  festival: "Festival",
  competition: "Competencia",
  show: "Show",
  other: "Otro",
};

const money = new Intl.NumberFormat(LOCALE, { style: "currency", currency: "COP", maximumFractionDigits: 0 });
const longDay = new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "long" });
const monthYear = new Intl.DateTimeFormat(LOCALE, { month: "long", year: "numeric" });
const shortMonth = new Intl.DateTimeFormat(LOCALE, { month: "short" });

export function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function typeLabel(type: EventType): string {
  return TYPE_LABELS[type] ?? type;
}

const MEDIA_LABELS: Record<MediaType, string> = {
  IMAGE: "Flyer",
  CAROUSEL_ALBUM: "Carrusel",
  VIDEO: "Video",
};

export function mediaLabel(type: MediaType): string {
  return MEDIA_LABELS[type] ?? "Publicación";
}

/**
 * "salsa · mambo · afro". The no-break space glues each dot to the word before it, so a wrapped line
 * never starts with a dot.
 */
export function stylesLabel(styles: string[], max = styles.length): string {
  return styles.slice(0, max).join(" · ");
}

/** "1 publicación" / "2 publicaciones" */
export function postCountLabel(count: number): string {
  return `${count} ${count === 1 ? "publicación" : "publicaciones"}`;
}

export function formatMoney(amountCop: number): string {
  return amountCop === 0 ? "Gratis" : money.format(amountCop);
}

/** "21:00" -> "9:00 p. m." */
export function formatTime(time: string | null): string {
  if (!time) return "";
  const [hours, minutes] = time.split(":").map(Number);
  const suffix = hours >= 12 ? "p. m." : "a. m.";
  return `${((hours + 11) % 12) + 1}:${String(minutes).padStart(2, "0")} ${suffix}`;
}

/** "Sábado, 3 de octubre" */
export function formatLongDate(iso: string): string {
  return capitalize(longDay.format(parseIsoDate(iso)));
}

/** "Hoy · Jueves, 1 de octubre", "Mañana · …" or just the long date. */
export function formatDayHeading(iso: string): string {
  const label = formatLongDate(iso);
  if (iso === todayIso()) return `Hoy · ${label}`;
  if (iso === addDays(todayIso(), 1)) return `Mañana · ${label}`;
  return label;
}

const weekdayName = new Intl.DateTimeFormat(LOCALE, { weekday: "long" });
const dayAndMonth = new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "short" });

/**
 * When an event happens, as shown on its card: "Hoy · 8:00 p. m.", "Mañana · 6:00 p. m.",
 * "Sábado · 8:00 p. m." within a week, "Martes 20 oct. · 7:00 p. m." further away.
 */
export function cardWhenLabel(event: DanceEvent): string {
  const days = daysBetween(todayIso(), event.date);
  const date = parseIsoDate(event.date);
  let day: string;
  if (days === 0) day = "Hoy";
  else if (days === 1) day = "Mañana";
  else if (days > 1 && days < 7) day = capitalize(weekdayName.format(date));
  else day = capitalize(dayAndMonth.format(date).replace(",", ""));
  const time = formatTime(event.start_time);
  return time ? `${day} · ${time}` : day;
}

const monthOnly = new Intl.DateTimeFormat(LOCALE, { month: "long" });

/** "octubre", or "octubre de 2027" with the year. */
export function formatMonthName(iso: string, withYear = false): string {
  const date = parseIsoDate(iso);
  return withYear ? monthYear.format(date) : monthOnly.format(date);
}

/** "Octubre de 2026" */
export function formatMonthTitle(month: Date): string {
  return capitalize(monthYear.format(month));
}

/** Parts for the round date sticker: { day: "03", month: "OCT" } */
export function stickerDate(iso: string): { day: string; month: string } {
  const date = parseIsoDate(iso);
  return {
    day: String(date.getDate()).padStart(2, "0"),
    month: shortMonth.format(date).replace(".", "").toUpperCase(),
  };
}

/** "Desde $ 20.000", "$ 15.000", "Gratis" or "" when there are no prices. */
export function priceSummary(event: DanceEvent): string {
  if (!event.prices.length) return "";
  const lowest = Math.min(...event.prices.map((price) => price.amount_cop));
  const amount = formatMoney(lowest);
  return event.prices.length > 1 && lowest > 0 ? `Desde ${amount}` : amount;
}

/** Venue (when different from the organizer), address and area joined with dots. */
export function placeLabel(event: DanceEvent): string {
  const venue = event.venue && event.venue !== event.organizer ? event.venue : null;
  return [venue, event.address, event.area].filter(Boolean).join(" · ");
}
