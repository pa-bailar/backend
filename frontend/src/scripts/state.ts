// UI state and the event filtering that depends on it.

import type { AppState, DanceEvent } from "./types";
import { startOfMonth, todayIso, toIsoDate } from "./lib/dates";

export function createInitialState(): AppState {
  return {
    view: "upcoming",
    typeFilter: "all",
    styleFilter: "all",
    month: startOfMonth(new Date()),
    selectedDay: todayIso(),
  };
}

export function matchesFilters(event: DanceEvent, state: AppState): boolean {
  const typeOk = state.typeFilter === "all" || event.event_type === state.typeFilter;
  const styleOk = state.styleFilter === "all" || event.styles.includes(state.styleFilter);
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

/** Events grouped by date, keeping the input order (events.json is already sorted). */
export function groupByDay(events: DanceEvent[]): Map<string, DanceEvent[]> {
  const groups = new Map<string, DanceEvent[]>();
  for (const event of events) {
    groups.set(event.date, [...(groups.get(event.date) ?? []), event]);
  }
  return groups;
}
