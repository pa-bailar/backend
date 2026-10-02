// Entry point: load the events embedded in the page, wire up interactions and render.

import type { DanceEvent, EventType, View } from "./types";
import { byId } from "./lib/dom";
import { addMonths, startOfMonth, todayIso } from "./lib/dates";
import { createInitialState } from "./state";
import { initThemeToggle } from "./theme";
import { renderCalendarView } from "./views/calendarView";
import { initEventDialog, openEventDialog } from "./views/eventDialog";
import { renderFilters } from "./views/filters";
import { renderUpcomingView } from "./views/upcomingView";

const state = createInitialState();
let events: DanceEvent[] = [];

function render() {
  renderFilters(events, state);

  const upcoming = byId("view-upcoming");
  const calendar = byId("view-calendar");
  upcoming.hidden = state.view !== "upcoming";
  calendar.hidden = state.view !== "calendar";
  document.querySelectorAll<HTMLElement>("[data-view]").forEach((tab) => {
    tab.setAttribute("aria-selected", String(tab.dataset.view === state.view));
  });

  if (state.view === "upcoming") renderUpcomingView(upcoming, events, state);
  else renderCalendarView(events, state);
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
  else if (monthStep) state.month = addMonths(state.month, Number(monthStep));
  else if ("today" in control.dataset) {
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
