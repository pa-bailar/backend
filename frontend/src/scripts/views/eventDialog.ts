// Event detail dialog on the home page.
// Opening it puts the event's own URL in the address bar (/evento/<id>/) with history.pushState, so:
//   - the phone's back button closes it instead of leaving the site;
//   - the address bar shows a link that works when copied (that page exists, see pages/evento/[id].astro).

import type { DanceEvent } from "../types";
import { byId } from "../lib/dom";
import { eventPath } from "../lib/links";
import { eventDetailHtml, handleMediaTabClick } from "./eventDetail";

let currentEvent: DanceEvent | null = null;
let findEvent: (id: string) => DanceEvent | undefined = () => undefined;

interface HistoryState {
  eventId?: string;
}

function dialog(): HTMLDialogElement {
  return byId<HTMLDialogElement>("event-dialog");
}

function render(selected: number) {
  if (!currentEvent) return;
  byId("event-dialog-body").innerHTML = eventDetailHtml(currentEvent, selected, { closeButton: true, headingLevel: 2 });
}

function show(event: DanceEvent) {
  currentEvent = event;
  render(0);
  if (!dialog().open) dialog().showModal();
}

export function openEventDialog(event: DanceEvent) {
  show(event);
  history.pushState({ eventId: event.id } satisfies HistoryState, "", eventPath(event));
}

/** `find` looks an event up by id, to reopen it when the visitor goes forward in history. */
export function initEventDialog(find: (id: string) => DanceEvent | undefined) {
  findEvent = find;
  const element = dialog();

  element.addEventListener("click", (domEvent) => {
    const target = domEvent.target as HTMLElement;
    if (handleMediaTabClick(byId("event-dialog-body"), target, render)) return;
    // Close on the × button or a click on the backdrop (the dialog element itself).
    if (target === element || target.closest("[data-close-dialog]")) element.close();
  });

  // Closed by ×, backdrop or Escape: leave the event's URL the same way the back button would.
  element.addEventListener("close", () => {
    currentEvent = null;
    if ((history.state as HistoryState | null)?.eventId) history.back();
  });

  // Back (or forward) button: follow the URL.
  window.addEventListener("popstate", (domEvent) => {
    const eventId = (domEvent.state as HistoryState | null)?.eventId;
    const event = eventId ? findEvent(eventId) : undefined;
    if (event) show(event);
    else if (element.open) element.close();
  });
}
