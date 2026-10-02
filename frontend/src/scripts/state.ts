// UI state and the event filtering that depends on it.

import type { AppState, DanceEvent } from "./types";
import { addDays, endOfWeek, startOfMonth, todayIso, toIsoDate } from "./lib/dates";
import { capitalize, formatMonthName } from "./lib/format";

export function createInitialState(): AppState {
  return {
    view: "upcoming",
    typeFilter: "all",
    styleFilter: "all",
    accountFilter: null,
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
  const accountOk = !state.accountFilter || event.account === state.accountFilter;
  return typeOk && styleOk && accountOk;
}

export function activeFilterCount(state: AppState): number {
  return [state.typeFilter !== "all", state.styleFilter !== "all", state.accountFilter !== null].filter(Boolean).length;
}

export function hasActiveFilters(state: AppState): boolean {
  return activeFilterCount(state) > 0;
}

export function clearFilters(state: AppState) {
  state.typeFilter = "all";
  state.styleFilter = "all";
  state.accountFilter = null;
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

/** The events on screen, in display order: the upcoming list, or the selected calendar day. Swiping in
 * the event viewer follows this order. */
export function visibleEvents(events: DanceEvent[], state: AppState): DanceEvent[] {
  const shown = eventsInView(events, state).filter((event) => matchesFilters(event, state));
  return state.view === "upcoming" ? shown : shown.filter((event) => event.date === state.selectedDay);
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
  key: string; // stable, for the section's id: "hoy", "fin-de-semana", "2026-11"…
  label: string; // heading: "Este fin de semana"
  shortLabel: string; // jump bar chip: "Finde"
  events: DanceEvent[];
}

/**
 * Upcoming events grouped by period instead of by day, so days with one or two events don't each
 * leave a mostly empty row. Non-overlapping buckets, in the style of calendar "date range" grouping
 * (This week, Next week, Later this month, Next month…), with the weekend split out because it's
 * when most socials happen:
 *
 *   "Hoy"                    today, first: what most visitors want to know (cf. hoy-milonga, Eventbrite)
 *   "Esta semana"            tomorrow … Thursday of this week (only Monday–Wednesday)
 *   "Este fin de semana"     Friday … Sunday of this week (Friday night counts as weekend)
 *   "Próxima semana"         next Monday … Sunday
 *   "Más adelante en <mes>"  the rest of the current month
 *   "<Mes>" / "<Mes> de <año>"  one group per later month (year shown when it's not this year)
 *
 * Weeks run Monday to Sunday, as in Colombian calendars. "Mañana" is shown on each card.
 * Input must be sorted by date.
 */
export function groupByPeriod(events: DanceEvent[], today = todayIso()): AgendaGroup[] {
  const thisWeekEnd = endOfWeek(today);
  const weekendStart = addDays(thisWeekEnd, -2); // Friday
  const nextWeekEnd = addDays(thisWeekEnd, 7);
  const currentMonth = today.slice(0, 7);

  const groups = new Map<string, AgendaGroup>();
  for (const event of events) {
    const [key, label, shortLabel] = periodOf(event.date);
    const group = groups.get(key) ?? { key, label, shortLabel, events: [] };
    group.events.push(event);
    groups.set(key, group);
  }
  return [...groups.values()];

  function periodOf(date: string): [string, string, string] {
    if (date === today) return ["hoy", "Hoy", "Hoy"];
    if (date < weekendStart) return ["esta-semana", "Esta semana", "Esta semana"];
    if (date <= thisWeekEnd) return ["fin-de-semana", "Este fin de semana", "Finde"];
    if (date <= nextWeekEnd) return ["proxima-semana", "Próxima semana", "Próx. semana"];
    const month = formatMonthName(date);
    if (date.startsWith(currentMonth)) return ["resto-del-mes", `Más adelante en ${month}`, `Resto de ${month}`];
    const otherYear = !date.startsWith(today.slice(0, 4));
    return [date.slice(0, 7), capitalize(formatMonthName(date, otherYear)), capitalize(otherYear ? `${month} ${date.slice(0, 4)}` : month)];
  }
}

/** Events grouped by date, keeping the input order (events.json is already sorted). */
export function groupByDay(events: DanceEvent[]): Map<string, DanceEvent[]> {
  const groups = new Map<string, DanceEvent[]>();
  for (const event of events) {
    groups.set(event.date, [...(groups.get(event.date) ?? []), event]);
  }
  return groups;
}
