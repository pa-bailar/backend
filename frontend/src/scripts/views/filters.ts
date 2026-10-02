// Filter chips for event type and dance style, and the notice of the academy filter (set from a card).
// Rendered into every [data-filter-row] container: the toolbar, and on phones the filter sheet too.
// Only values present in the current view's events are offered (plus the selected one), so a chip
// never leads to an empty list just because that style only appears in past events.

import type { AppState, DanceEvent, EventType } from "../types";
import { escapeHtml } from "../lib/dom";
import { capitalize, typeLabel } from "../lib/format";
import { STYLE_FAMILIES, eventsInView } from "../state";

function chipHtml(attribute: "type" | "style", value: string, label: string, active: boolean): string {
  return `<button class="chip" data-${attribute}="${escapeHtml(value)}" aria-pressed="${active}">${escapeHtml(label)}</button>`;
}

function withSelected<T extends string>(options: T[], selected: T | "all"): T[] {
  return selected === "all" || options.includes(selected) ? options : [...options, selected];
}

/** Styles present, plus the family chip ("Salsa", "Bachata") whenever one of its variants is present. */
function styleOptions(events: DanceEvent[]): string[] {
  const present = new Set(events.flatMap((event) => event.styles));
  for (const family of STYLE_FAMILIES) {
    if ([...present].some((style) => style.startsWith(`${family} `))) present.add(family);
  }
  return [...present].sort((a, b) => a.localeCompare(b, "es"));
}

export function renderFilters(events: DanceEvent[], state: AppState) {
  const visible = eventsInView(events, state);
  const types = withSelected([...new Set(visible.map((event) => event.event_type))], state.typeFilter);
  const styles = withSelected(styleOptions(visible), state.styleFilter);

  fill("type", [
    chipHtml("type", "all", "Todo", state.typeFilter === "all"),
    ...types.map((type: EventType) => chipHtml("type", type, typeLabel(type), state.typeFilter === type)),
  ].join(""));

  fill("style", [
    chipHtml("style", "all", "Todos los ritmos", state.styleFilter === "all"),
    ...styles.map((style) => chipHtml("style", style, capitalize(style), state.styleFilter === style)),
  ].join(""));

  const account = state.accountFilter
    ? `<span>Solo eventos de <b>@${escapeHtml(state.accountFilter)}</b></span>
       <button class="chip" data-account="">Ver todas las academias</button>`
    : "";
  fill("account", account, !state.accountFilter);
}

function fill(row: "type" | "style" | "account", html: string, hidden = false) {
  document.querySelectorAll<HTMLElement>(`[data-filter-row="${row}"]`).forEach((container) => {
    container.innerHTML = html;
    container.hidden = hidden;
  });
}
