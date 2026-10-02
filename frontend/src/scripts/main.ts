// Entry point: load the events embedded in the page, wire up interactions and render.

import type { DanceEvent, EventType, View } from "./types";
import { byId } from "./lib/dom";
import { addMonths, startOfMonth, todayIso } from "./lib/dates";
import { createInitialState, defaultDayForMonth } from "./state";
import { initThemeToggle } from "./theme";
import { renderCalendarView } from "./views/calendarView";
import { initEventDialog, openEventDialog } from "./views/eventDialog";
import { renderFilters } from "./views/filters";
import { renderUpcomingView } from "./views/upcomingView";

const state = createInitialState();
let events: DanceEvent[] = [];

/** data-* attributes that identify a re-rendered control, so focus can be put back on it. */
const FOCUS_KEYS = ["type", "style", "day"] as const;

function focusSelector(element: Element | null): string | null {
  if (!(element instanceof HTMLElement)) return null;
  const key = FOCUS_KEYS.find((name) => element.dataset[name] !== undefined);
  return key ? `[data-${key}="${CSS.escape(element.dataset[key]!)}"]` : null;
}

function announce(count: number) {
  const noun = count === 1 ? "evento" : "eventos";
  byId("results-status").textContent =
    state.view === "upcoming" ? `${count} ${noun} próximos` : `${count} ${noun} este día`;
}

function render() {
  // Re-rendering replaces chips and calendar days; remember which one had focus.
  const focused = focusSelector(document.activeElement);

  renderFilters(events, state);
  const upcoming = byId("view-upcoming");
  const calendar = byId("view-calendar");
  upcoming.hidden = state.view !== "upcoming";
  calendar.hidden = state.view !== "calendar";
  document.querySelectorAll<HTMLElement>("[data-view]").forEach((tab) => {
    tab.setAttribute("aria-selected", String(tab.dataset.view === state.view));
  });

  const shown = state.view === "upcoming" ? renderUpcomingView(upcoming, events, state) : renderCalendarView(events, state);
  announce(shown);

  if (focused) document.querySelector<HTMLElement>(focused)?.focus();
}

/** One delegated listener for every data-* control rendered by the views. */
function handleClick(domEvent: MouseEvent) {
  const control = (domEvent.target as HTMLElement).closest<HTMLElement>(
    "[data-view],[data-type],[data-style],[data-day],[data-event],[data-month-step],[data-today]",
  );
  if (!control) return;
  const { view, type, style, day, event: eventId, monthStep } = control.dataset;

  if (eventId) {
    const event = events.find((item) => item.id === eventId);
    if (event) openEventDialog(event);
    return;
  }
  if (view) state.view = view as View;
  else if (type) state.typeFilter = type as EventType | "all";
  else if (style) state.styleFilter = style;
  else if (day) state.selectedDay = day;
  else if (monthStep) {
    state.month = addMonths(state.month, Number(monthStep));
    state.selectedDay = defaultDayForMonth(events, state.month);
  } else if ("today" in control.dataset) {
    state.month = startOfMonth(new Date());
    state.selectedDay = todayIso();
  }
  render();
}

export function start() {
  events = JSON.parse(byId("events-data").textContent || "[]");
  initThemeToggle();
  initEventDialog();
  document.addEventListener("click", handleClick);
  render();
}
