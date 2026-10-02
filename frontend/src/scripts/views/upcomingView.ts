// "Próximos": upcoming events grouped by day.

import type { AppState, DanceEvent } from "../types";
import { escapeHtml } from "../lib/dom";
import { formatDayHeading } from "../lib/format";
import { eventsInView, groupByDay, matchesFilters } from "../state";
import { eventCardGridHtml } from "./eventCard";

/** Renders the list and returns how many events it shows. */
export function renderUpcomingView(container: HTMLElement, events: DanceEvent[], state: AppState): number {
  const upcoming = eventsInView(events, state).filter((event) => matchesFilters(event, state));

  if (!upcoming.length) {
    container.innerHTML = `
      <div class="empty-state">
        <p>No hay eventos próximos con estos filtros.</p>
        <p>Prueba otro filtro o revisa el calendario.</p>
      </div>`;
    return 0;
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
  return upcoming.length;
}
