// Entry point of an event's own page (pages/evento/[id].astro): theme toggle and the media tabs.
// The detail itself is already in the HTML, rendered at build time.

import type { DanceEvent } from "./types";
import { byId } from "./lib/dom";
import { initThemeToggle } from "./theme";
import { eventDetailHtml, handleMediaTabClick } from "./views/eventDetail";

export function initEventPage() {
  initThemeToggle();
  const event: DanceEvent = JSON.parse(byId("event-data").textContent || "null");
  const container = byId("event-detail");
  const render = (selected: number) => {
    container.innerHTML = eventDetailHtml(event, selected, { closeButton: false, headingLevel: 1 });
  };
  container.addEventListener("click", (domEvent) => handleMediaTabClick(container, domEvent.target as HTMLElement, render));
}
