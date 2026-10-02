// "Próximos": upcoming events grouped by period (this week, next week, then by month).

import type { AppState, DanceEvent } from "../types";
import { escapeHtml } from "../lib/dom";
import { eventsInView, groupByPeriod, matchesFilters } from "../state";
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

  container.innerHTML = groupByPeriod(upcoming)
    .map(
      (group) => `
        <section class="agenda-group">
          <h2 class="agenda-group__heading">${escapeHtml(group.label)}</h2>
          ${eventCardGridHtml(group.events)}
        </section>`,
    )
    .join("");
  return upcoming.length;
}
