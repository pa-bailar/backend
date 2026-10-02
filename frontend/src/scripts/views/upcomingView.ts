// "Próximos": upcoming events grouped by period (today, this week, the weekend, next week, by month).
// On phones it reads like an Instagram feed (event-card.css); the jump bar (jumpBar.ts) moves between periods.

import type { AppState, DanceEvent } from "../types";
import { escapeHtml } from "../lib/dom";
import { activeFilterCount, eventsInView, groupByPeriod, hasActiveFilters, matchesFilters } from "../state";
import { eventCardGridHtml } from "./eventCard";
import { renderJumpBar, sectionId } from "./jumpBar";

/** Renders the list and returns how many events it shows. */
export function renderUpcomingView(container: HTMLElement, events: DanceEvent[], state: AppState): number {
  const upcoming = eventsInView(events, state).filter((event) => matchesFilters(event, state));
  const groups = groupByPeriod(upcoming);

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
  } else {
    container.innerHTML = groups
      .map(
        (group) => `
        <section class="agenda-group" id="${sectionId(group)}" data-period="${escapeHtml(group.key)}">
          <h2 class="agenda-group__heading" tabindex="-1">${escapeHtml(group.label)}</h2>
          ${eventCardGridHtml(group.events)}
        </section>`,
      )
      .join("");
  }
  renderJumpBar(groups, activeFilterCount(state));
  return upcoming.length;
}
