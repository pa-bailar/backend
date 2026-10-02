// "Calendario": month grid plus the selected day's events.

import type { AppState, DanceEvent } from "../types";
import { byId, escapeHtml } from "../lib/dom";
import { daysInMonth, mondayOffset, todayIso, toIsoDate } from "../lib/dates";
import { formatDayHeading, formatMonthTitle } from "../lib/format";
import { groupByDay, matchesFilters } from "../state";
import { eventCardGridHtml } from "./eventCard";

const WEEKDAY_INITIALS = ["L", "M", "M", "J", "V", "S", "D"];
const MAX_PILLS_PER_DAY = 3;

function dayCellHtml(iso: string, dayNumber: number, dayEvents: DanceEvent[], state: AppState): string {
  const today = todayIso();
  const modifiers = [
    iso < today && "is-past",
    iso === today && "is-today",
    iso === state.selectedDay && "is-selected",
  ].filter(Boolean);
  const pills = dayEvents
    .slice(0, MAX_PILLS_PER_DAY)
    .map((event) => `<span class="cal-pill t-${escapeHtml(event.event_type)}">${escapeHtml(event.title)}</span>`)
    .join("");
  const more = dayEvents.length > MAX_PILLS_PER_DAY ? `<span class="cal-more">+${dayEvents.length - MAX_PILLS_PER_DAY}</span>` : "";
  const dots = dayEvents.map((event) => `<i class="cal-dot t-${escapeHtml(event.event_type)}"></i>`).join("");
  const count = dayEvents.length;
  const label = count ? `${dayNumber}, ${count} evento${count > 1 ? "s" : ""}` : String(dayNumber);

  return `
    <button class="cal-day ${modifiers.join(" ")}" data-day="${iso}" aria-label="${label}" aria-pressed="${iso === state.selectedDay}">
      <span class="cal-day__number">${dayNumber}</span>
      <span class="cal-day__pills">${pills}${more}</span>
      <span class="cal-day__dots">${dots}</span>
    </button>`;
}

export function renderCalendarView(events: DanceEvent[], state: AppState) {
  const { month } = state;
  const byDay = groupByDay(events.filter((event) => matchesFilters(event, state)));

  const cells = WEEKDAY_INITIALS.map((initial) => `<div class="cal-weekday" aria-hidden="true">${initial}</div>`);
  for (let i = 0; i < mondayOffset(month); i++) cells.push(`<div class="cal-day cal-day--blank"></div>`);
  for (let day = 1; day <= daysInMonth(month); day++) {
    const iso = toIsoDate(new Date(month.getFullYear(), month.getMonth(), day));
    cells.push(dayCellHtml(iso, day, byDay.get(iso) ?? [], state));
  }

  byId("cal-title").textContent = formatMonthTitle(month);
  byId("cal-grid").innerHTML = cells.join("");

  const selectedEvents = byDay.get(state.selectedDay) ?? [];
  byId("cal-selected-day").innerHTML = `
    <h2 class="day-heading">${escapeHtml(formatDayHeading(state.selectedDay))}</h2>
    ${selectedEvents.length ? eventCardGridHtml(selectedEvents) : `<p class="text-muted">No hay eventos este día.</p>`}`;
}
