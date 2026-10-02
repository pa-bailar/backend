// UI state and the event filtering that depends on it.

import type { AppState, DanceEvent } from "./types";
import { addDays, endOfWeek, startOfMonth, todayIso, toIsoDate } from "./lib/dates";
import { capitalize, formatMonthName } from "./lib/format";

export function createInitialState(): AppState {
  return {
    view: "upcoming",
    typeFilter: "all",
    styleFilter: "all",
    month: startOfMonth(new Date()),
    selectedDay: todayIso(),
  };
}

/** Styles with variants: filtering by the family ("salsa") also matches its variants ("salsa caleña"). */
export const STYLE_FAMILIES = ["salsa", "bachata"];

export function styleMatches(eventStyle: string, filter: string): boolean {
  return eventStyle === filter || (STYLE_FAMILIES.includes(filter) && eventStyle.startsWith(`${filter} `));
}

export function matchesFilters(event: DanceEvent, state: AppState): boolean {
  const typeOk = state.typeFilter === "all" || event.event_type === state.typeFilter;
  const styleOk = state.styleFilter === "all" || event.styles.some((style) => styleMatches(style, state.styleFilter));
  return typeOk && styleOk;
}

function monthPrefix(month: Date): string {
  return toIsoDate(month).slice(0, 7); // "YYYY-MM"
}

/** Events the current view can show before filtering: upcoming ones, or the displayed month's. */
export function eventsInView(events: DanceEvent[], state: AppState): DanceEvent[] {
  if (state.view === "upcoming") {
    const today = todayIso();
    return events.filter((event) => event.date >= today);
  }
  const prefix = monthPrefix(state.month);
  return events.filter((event) => event.date.startsWith(prefix));
}

/** Day to select after moving to another month: today in the current month, else its first event day. */
export function defaultDayForMonth(events: DanceEvent[], month: Date): string {
  const prefix = monthPrefix(month);
  const today = todayIso();
  if (today.startsWith(prefix)) return today;
  const firstEvent = events.find((event) => event.date.startsWith(prefix));
  return firstEvent ? firstEvent.date : toIsoDate(month);
}

export interface AgendaGroup {
  label: string;
  events: DanceEvent[];
}

/**
 * Upcoming events grouped by period instead of by day, so days with one or two events don't each
 * leave a mostly empty row. Non-overlapping buckets, in the style of calendar "date range" grouping
 * (This week, Next week, Later this month, Next month…), with the weekend split out because it's
 * when most socials happen:
 *
 *   "Esta semana"            today … Thursday of this week (only Monday–Thursday)
 *   "Este fin de semana"     Friday … Sunday of this week (Friday night counts as weekend)
 *   "Próxima semana"         next Monday … Sunday
 *   "Más adelante en <mes>"  the rest of the current month
 *   "<Mes>" / "<Mes> de <año>"  one group per later month (year shown when it's not this year)
 *
 * Weeks run Monday to Sunday, as in Colombian calendars. Hoy/Mañana are shown on each card.
 * Input must be sorted by date.
 */
export function groupByPeriod(events: DanceEvent[], today = todayIso()): AgendaGroup[] {
  const thisWeekEnd = endOfWeek(today);
  const weekendStart = addDays(thisWeekEnd, -2); // Friday
  const nextWeekEnd = addDays(thisWeekEnd, 7);
  const currentMonth = today.slice(0, 7);

  const groups = new Map<string, DanceEvent[]>();
  for (const event of events) {
    let label: string;
    if (event.date < weekendStart) label = "Esta semana";
    else if (event.date <= thisWeekEnd) label = "Este fin de semana";
    else if (event.date <= nextWeekEnd) label = "Próxima semana";
    else if (event.date.startsWith(currentMonth)) label = `Más adelante en ${formatMonthName(event.date)}`;
    else label = capitalize(formatMonthName(event.date, !event.date.startsWith(today.slice(0, 4))));
    groups.set(label, [...(groups.get(label) ?? []), event]);
  }
  return [...groups].map(([label, grouped]) => ({ label, events: grouped }));
}

/** Events grouped by date, keeping the input order (events.json is already sorted). */
export function groupByDay(events: DanceEvent[]): Map<string, DanceEvent[]> {
  const groups = new Map<string, DanceEvent[]>();
  for (const event of events) {
    groups.set(event.date, [...(groups.get(event.date) ?? []), event]);
  }
  return groups;
}
