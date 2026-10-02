// "Próximos": upcoming events grouped by day.

import type { AppState, DanceEvent } from "../types";
import { escapeHtml } from "../lib/dom";
import { todayIso } from "../lib/dates";
import { formatDayHeading } from "../lib/format";
import { groupByDay, matchesFilters } from "../state";
import { eventCardGridHtml } from "./eventCard";

export function renderUpcomingView(container: HTMLElement, events: DanceEvent[], state: AppState) {
  const today = todayIso();
  const upcoming = events.filter((event) => event.date >= today && matchesFilters(event, state));

  if (!upcoming.length) {
    container.innerHTML = `
      <div class="empty-state">
        <p>No hay eventos próximos con estos filtros.</p>
        <p>Prueba otro filtro o revisa el calendario.</p>
      </div>`;
    return;
  }

  container.innerHTML = [...groupByDay(upcoming)]
    .map(
      ([day, dayEvents]) => `
        <section class="day-group">
          <h2 class="day-heading">${escapeHtml(formatDayHeading(day))}</h2>
          ${eventCardGridHtml(dayEvents)}
        </section>`,
    )
    .join("");
}
