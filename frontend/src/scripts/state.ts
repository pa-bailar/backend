// UI state and the event filtering that depends on it.

import type { AppState, DanceEvent } from "./types";
import { startOfMonth, todayIso } from "./lib/dates";

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

/** Events grouped by date, keeping the input order (events.json is already sorted). */
export function groupByDay(events: DanceEvent[]): Map<string, DanceEvent[]> {
  const groups = new Map<string, DanceEvent[]>();
  for (const event of events) {
    groups.set(event.date, [...(groups.get(event.date) ?? []), event]);
  }
  return groups;
}
