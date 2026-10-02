// "Próximos": upcoming events grouped by period (this week, next week, then by month).

import type { AppState, DanceEvent } from "../types";
import { escapeHtml } from "../lib/dom";
import { eventsInView, groupByPeriod, hasActiveFilters, matchesFilters } from "../state";
import { eventCardGridHtml } from "./eventCard";

/** Renders the list and returns how many events it shows. */
export function renderUpcomingView(container: HTMLElement, events: DanceEvent[], state: AppState): number {
  const upcoming = eventsInView(events, state).filter((event) => matchesFilters(event, state));

  if (!upcoming.length) {
    container.innerHTML = hasActiveFilters(state)
      ? `<div class="empty-state">
          <p>No hay eventos próximos con estos filtros.</p>
          <button class="btn" data-clear-filters>Quitar filtros</button>
        </div>`
      : `<div class="empty-state">
          <p>No hay eventos próximos por ahora.</p>
          <p>Las academias publican casi a diario: vuelve en unos días.</p>
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
