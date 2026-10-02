// Filter chips for event type and dance style. Only values present in the data are shown.

import type { AppState, DanceEvent, EventType } from "../types";
import { byId, escapeHtml } from "../lib/dom";
import { capitalize, typeLabel } from "../lib/format";

function chipHtml(attribute: "type" | "style", value: string, label: string, active: boolean): string {
  return `<button class="chip" data-${attribute}="${escapeHtml(value)}" aria-pressed="${active}">${escapeHtml(label)}</button>`;
}

export function renderFilters(events: DanceEvent[], state: AppState) {
  const types = [...new Set(events.map((event) => event.event_type))] as EventType[];
  const styles = [...new Set(events.flatMap((event) => event.styles))].sort();

  byId("type-filters").innerHTML = [
    chipHtml("type", "all", "Todo", state.typeFilter === "all"),
    ...types.map((type) => chipHtml("type", type, typeLabel(type), state.typeFilter === type)),
  ].join("");

  byId("style-filters").innerHTML = [
    chipHtml("style", "all", "Todos los ritmos", state.styleFilter === "all"),
    ...styles.map((style) => chipHtml("style", style, capitalize(style), state.styleFilter === style)),
  ].join("");
}
