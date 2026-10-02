// Entry point: load the events embedded in the page, wire up interactions and render.

import type { DanceEvent, EventType, View } from "./types";
import { byId } from "./lib/dom";
import { addMonths, startOfMonth, todayIso } from "./lib/dates";
import { clearFilters, createInitialState, defaultDayForMonth, visibleEvents } from "./state";
import { initThemeToggle } from "./theme";
import { renderCalendarView } from "./views/calendarView";
import { initEventDialog, openEventDialog } from "./views/eventDialog";
import { renderFilters } from "./views/filters";
import { hideJumpBar, initJumpBar } from "./views/jumpBar";
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
  byId("filter-sheet-results").textContent = count ? `Ver ${count} ${noun}` : "Ver resultados";
}

/** Where re-rendered controls are looked up for focus: the open filter sheet, or else the page. */
function focusScope(): ParentNode {
  return document.querySelector("#filter-sheet[open]") ?? document;
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

  if (state.view !== "upcoming") hideJumpBar();
  const shown = state.view === "upcoming" ? renderUpcomingView(upcoming, events, state) : renderCalendarView(events, state);
  announce(shown);

  if (focused) focusScope().querySelector<HTMLElement>(focused)?.focus();
}

/** After filtering by academy from a card far down the list, move to the filter notice (and its "show all" button). */
function focusAccountFilter() {
  byId("account-filter").querySelector<HTMLElement>("button")?.focus();
}

/** One delegated listener for every data-* control rendered by the views. */
function handleClick(domEvent: MouseEvent) {
  const control = (domEvent.target as HTMLElement).closest<HTMLElement>(
    "[data-view],[data-type],[data-style],[data-account],[data-clear-filters],[data-day],[data-event],[data-month-step],[data-today]",
  );
  if (!control) return;
  const { view, type, style, account, day, event: eventId, monthStep } = control.dataset;

  if (eventId) {
    const event = events.find((item) => item.id === eventId);
    if (event) openEventDialog(event, visibleEvents(events, state));
    return;
  }
  if (view) state.view = view as View;
  else if (type) state.typeFilter = type as EventType | "all";
  else if (style) state.styleFilter = style;
  else if (account !== undefined) {
    state.accountFilter = account || null; // "" = show every academy again
  } else if ("clearFilters" in control.dataset) clearFilters(state);
  else if (day) state.selectedDay = day;
  else if (monthStep) {
    state.month = addMonths(state.month, Number(monthStep));
    state.selectedDay = defaultDayForMonth(events, state.month);
  } else if ("today" in control.dataset) {
    state.month = startOfMonth(new Date());
    state.selectedDay = todayIso();
  }
  render();

  // The control clicked was re-rendered away: put focus somewhere useful.
  if (account) focusAccountFilter();
  else if ("clearFilters" in control.dataset) {
    focusScope().querySelector<HTMLElement>('[data-filter-row="type"] button')?.focus();
  }
}

export function start() {
  events = JSON.parse(byId("events-data").textContent || "[]");
  initThemeToggle();
  initEventDialog((id) => events.find((event) => event.id === id));
  initJumpBar();
  document.addEventListener("click", handleClick);
  render();
}
