// "Próximos": upcoming events grouped by period (today, this week, the weekend, next week, by month).
// On phones it reads like an Instagram feed (event-card.css); the jump bar (jumpBar.ts) moves between periods.

import type { AppState, DanceEvent } from "../types";
import { escapeHtml } from "../lib/dom";
import { eventsInView, groupByPeriod, hasActiveFilters, matchesFilters } from "../state";
import { eventCardGridHtml } from "./eventCard";
import type { AgendaGroup } from "../state";
import { sectionId } from "./jumpBar";

/** Renders the list; returns how many events it shows and their periods (for the jump bar). */
export function renderUpcomingView(
  container: HTMLElement,
  events: DanceEvent[],
  state: AppState,
): { shown: number; groups: AgendaGroup[] } {
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
  return { shown: upcoming.length, groups };
}
